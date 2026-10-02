import base64
import io
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PIL import Image, ImageDraw
from pypdf import PdfReader
from . import adapters
from .finance import calculate
from .models import Run, RunInput, Property, Source, Claim, Media, Observation, Comparable, Assumptions, now
from .research import questions, search_queries, extract_claims, compare
from .story import template_story, editorial_story, generate_story, audit, script_markdown
from .storage import Store


RUBRIC = ["room and visible finishes", "visible condition without hidden diagnoses", "view and obstructions",
          "outdoor space", "storage", "lighting appearance and uncertainty", "staging", "useful scene composition"]


from .listing import normalized, identity_match, parse_listing, address_from_url, unit_of, without_unit, select_photos
from .defaults import apply_defaults
from .comps import screen


class Service:
    def __init__(self, settings):
        self.settings=settings
        self.store=Store(settings)
        self.worker=ThreadPoolExecutor(max_workers=1, thread_name_prefix="property")
        self.pending=set()
        self.cosmos=adapters.Cosmos(settings)
        self.llm=adapters.LanguageModel(settings)

    def create(self, request: RunInput):
        if request.mode=="synthetic":
            request=synthetic_input()
        run=Run(request=request,property=Property(address=request.address or "Address needs confirmation",unit=request.unit,
                association=request.association,identity_status="synthetic" if request.mode=="synthetic" else "user_confirmed" if request.confirm_identity and re.match(r"^\d+\s+\w",request.address) else "needs_review"))
        run.questions=questions(run)
        self.store.save(run)
        return run

    def submit(self, run_id, start="intake"):
        with self.store.lock:
            if run_id in self.pending: raise ValueError("This run is already processing")
            run=self.store.get(run_id)
            run.state="pending"
            self.store.save(run)
            self.pending.add(run_id)
        return self.worker.submit(self.execute,run_id,start)

    def stage(self,run,name,fn):
        run.stages[name]={"state":"running","started_at":now()}
        self.store.save(run)
        t=time.monotonic()
        try:
            message=fn(run)
            run.stages[name].update(state="completed",message=message or "Done")
        except Exception as exc:
            # Provider exceptions are deliberately scrubbed; do not log private payloads.
            message=str(exc) if isinstance(exc,(adapters.ProviderError,ValueError)) else type(exc).__name__+"; inspect the adapter configuration"
            run.stages[name].update(state="partial",message=message[:500])
        run.stages[name]["seconds"]=round(time.monotonic()-t,2)
        run.events.append({"stage":name,"at":now(),"state":run.stages[name]["state"],"seconds":run.stages[name]["seconds"]})
        self.store.save(run)

    def execute(self,run_id,start="intake"):
        try:
            run=self.store.get(run_id)
            run.state="running"
            self.store.save(run)
            stages=[("intake",self.intake),("research",self.research),("comparables",self.comparables),
                    ("vision",self.vision),("finance",self.finances),("story",self.story),("export",self.export)]
            if run.request.render_video or start=="video": stages.append(("video",self.video))
            begun=False
            dirty=False
            for name,fn in stages:
                if name==start: begun=True
                if not begun: continue
                if name!="intake" and run.property.identity_status=="needs_review":
                    run.state="blocked"
                    run.audit=audit(run)
                    self.store.save(run)
                    return
                if run.stages.get(name,{}).get("state")=="completed" and start=="intake" and not dirty: continue
                if not dirty:
                    if name=="video":
                        run.artifacts.pop("video",None);run.artifacts.pop("captions",None)
                    else: run.artifacts={}
                dirty=True
                self.stage(run,name,fn)
            run.audit=audit(run)
            run.state="demo" if run.request.mode=="synthetic" else "partial" if any(s["state"]=="partial" for s in run.stages.values()) else "draft"
            self.store.save(run)
            if 'dossier' in run.artifacts:
                (self.store.folder(run.id)/run.artifacts['dossier']).write_text(run.model_dump_json(indent=2))
            if self.settings.s3_bucket:
                self.stage(run,"storage",lambda r:self.store.sync(r))
                if run.stages["storage"]["state"]=="partial": run.state="partial"
                self.store.save(run)
        finally:
            with self.store.lock: self.pending.discard(run_id)

    def source_url(self,run,url,kind="public_record"):
        existing=next((s for s in run.sources if s.url==url),None)
        if existing: return existing
        data,mime,final=adapters.fetch_public(url)
        if "pdf" in mime or data.startswith(b"%PDF"):
            reader=PdfReader(io.BytesIO(data))
            if len(reader.pages)>100: raise ValueError("PDF exceeds 100 pages; upload a smaller document")
            text="\n".join(f"Page {i+1}: "+(p.extract_text() or "") for i,p in enumerate(reader.pages))[:50000]
            title=Path(final.split("?")[0]).name
        else:
            title,text,_=adapters.page_text(data)
        source=Source(title=title,url=final,kind=kind,excerpt=text,sha256=adapters.digest(data))
        source.artifact=f"source-{source.id}.txt"
        (self.store.folder(run.id)/source.artifact).write_text(text)
        (self.store.folder(run.id)/f"source-{source.id}.original").write_bytes(data)
        run.sources.append(source)
        return source

    def add_image(self,run,data,source,permission,original_url=None):
        sha=adapters.digest(data)
        if any(m.sha256==sha for m in run.media): return
        with Image.open(io.BytesIO(data)) as img:
            if img.width*img.height>30_000_000: raise ValueError("Image exceeds pixel limit")
            img=img.convert("RGB")
            img.thumbnail((1600,1600))
            media=Media(source_id=source.id,filename=f"photo-{sha[:20]}.jpg",sha256=sha,permission=permission,original_url=original_url)
            img.save(self.store.folder(run.id)/media.filename,"JPEG",quality=90)
        run.media.append(media)

    def apply_listing(self,run,record,source):
        desc=record.get("description") or {}; address=record.get("address") or {}
        for k in ["beds","sqft","year_built"]:
            if desc.get(k) is not None: run.property.facts[k]=desc[k]
        if desc.get("baths_full") is not None:
            run.property.facts["baths"]=desc["baths_full"]+0.5*(desc.get("baths_half") or 0)
        for key in ["city","state","zip","street"]:
            if address.get(key): run.property.facts[key]=address[key]
        for key in ["latitude","longitude","rent_estimate","property_tax_rate"]:
            if record.get(key) is not None: run.property.facts[key]=record[key]
        if desc.get("style"): run.property.kind=str(desc["style"]).lower()
        if desc.get("text"): run.property.facts["listing_description"]=desc["text"]
        for key,field in [("purchase_price","list_price"),("hoa_monthly","hoa_fee")]:
            if record.get(field) is not None and getattr(run.request.assumptions,key) is None:
                setattr(run.request.assumptions,key,record[field])
                run.request.assumptions.source_notes[key]=f"Listing-reported {field}; source {source.id}; retrieved {source.retrieved_at}"
        if record.get('list_price'): run.property.facts['asking_price']=record['list_price']
        facts=run.property.facts
        identity=f"The listing is for {run.property.address}."
        statements=[identity]
        for key in ['beds','baths','sqft','year_built']:
            if facts.get(key) is not None: statements.append(f"The listing reports {facts[key]:g} {key.replace('_',' ')}.")
        if desc.get('text'):
            # Attributed excerpts may enter the draft without a separate approval click.
            statements += ['The listing describes: '+sentence.strip()+'.' for sentence in re.split(r'(?<=[.!?])\s+',desc['text'])[:6] if sentence.strip()]
        for text in statements:
            if not any(c.text==text for c in run.claims):
                run.claims.append(Claim(property_id=run.property.id,text=text,kind='reported',status='supported',source_ids=[source.id],limitation='Attributed listing information; not an independent inspection.'))

    def intake(self,run):
        if run.request.mode=="synthetic":
            seed_synthetic(run,self)
            return "Synthetic inputs loaded; no live lookup or Cosmos inference"
        warnings=[]; image_jobs=[]
        if run.request.url:
            try:
                source=self.source_url(run,run.request.url,"listing")
                data=(self.store.folder(run.id)/f"source-{source.id}.original").read_bytes()
                record=parse_listing(data,source.url)
                resolved=record['address'].get('formatted_address')
                if resolved:
                    if run.request.address and not identity_match(run.request.address,run.request.unit,record):
                        raise ValueError("The URL and entered address refer to different properties. Start with one listing URL.")
                    run.property.address=resolved; run.property.unit=run.request.unit or record['address'].get('unit')
                    run.request.address=resolved;run.request.unit=run.property.unit
                    run.property.identity_status='resolved'
                    self.apply_listing(run,record,source)
                    image_jobs += [(url,source) for url in select_photos(record.get('description',{}).get('alt_photos',[]))]
            except (adapters.ProviderError,OSError) as exc: warnings.append(str(exc) if isinstance(exc,adapters.ProviderError) else "Listing page could not be reached; trying address lookup.")
            if not run.request.address:
                hint=address_from_url(run.request.url)
                if hint:
                    run.request.address=hint;run.property.address=hint
                    run.request.unit=run.request.unit or unit_of(hint);run.property.unit=run.request.unit
        if not run.request.address:
            run.property.identity_status='needs_review'
            return "The site did not expose an address. Enter the street address to continue."
        if run.request.use_homeharvest:
            try:
                location=run.property.address
                if run.property.unit and not unit_of(location): location += ' Unit '+run.property.unit
                records=adapters.homeharvest(location)
                matches=[r for r in records if identity_match(run.property.address,run.property.unit,r)]
                if len(matches)==1:
                    record=matches[0];address=record['address']
                    run.property.address=address['formatted_address'];run.request.address=run.property.address
                    run.property.unit=run.property.unit or unit_of(address.get('full_line',''))
                    run.request.unit=run.property.unit;run.property.identity_status='resolved'
                    raw=json.dumps(record,default=str)
                    source=Source(title="Realtor.com listing via HomeHarvest",url=str(record.get("property_url") or ""),kind="listing",feed="realtor.com",excerpt=raw[:50000],sha256=adapters.digest(raw.encode()))
                    source.artifact=f"source-{source.id}.txt"
                    (self.store.folder(run.id)/source.artifact).write_text(raw)
                    run.sources.append(source);self.apply_listing(run,record,source)
                    desc=record.get('description') or {}
                    image_jobs += [(url,source) for url in select_photos(([desc['primary_photo']] if desc.get('primary_photo') else [])+(desc.get('alt_photos') or []))]
                else: warnings.append("No unique matching Realtor.com unit; using the supplied listing.")
            except adapters.ProviderError as exc: warnings.append(str(exc))
        if run.property.identity_status=='needs_review':
            return "Enter the exact street address and unit; the supplied identity could not be resolved."
        if run.request.authorize_images:
            for url in run.request.image_urls:
                source=Source(title="Supplied listing photo",url=url,kind="user");run.sources.append(source);image_jobs.insert(0,(url,source))
            seen=set()
            for url,source in image_jobs:
                if url in seen: continue
                seen.add(url)
                if len(run.media)>=8: break
                try:
                    data,_,final=adapters.fetch_public(str(url))
                    self.add_image(run,data,source,"user_authorized",final)
                except Exception as exc: warnings.append('Photo unavailable: '+type(exc).__name__)
        if warnings: run.events.append({'stage':'intake','at':now(),'notes':warnings[:5]})
        if not run.property.facts and not run.sources: raise adapters.ProviderError("Listing data was unavailable; add a listing URL or document.")
        return f"Resolved {run.property.address}; {len(run.media)} listing photos saved."

    def research(self,run):
        if run.request.mode=="synthetic": return "Synthetic research fixture; all real HOA records remain unreviewed"
        notes=[];urls=list(run.request.source_urls)
        if self.settings.search_key:
            for query in search_queries(run)[:2]:
                try: urls += [r['url'] for r in adapters.search_web(self.settings,query) if r.get('url')]
                except adapters.ProviderError as exc: notes.append(str(exc))
        for url in list(dict.fromkeys(urls))[:6]:
            try: self.source_url(run,url)
            except Exception as exc: notes.append('Source unavailable: '+type(exc).__name__)
        if self.settings.llm_key and self.settings.llm_model:
            for source in run.sources[:4]:
                if source.excerpt and not any(source.id in c.source_ids for c in run.claims):
                    try: extract_claims(run,source,self.llm)
                    except Exception as exc: notes.append('Extraction unavailable: '+type(exc).__name__)
        run.questions=[{'question':'What changes the price-versus-rent story?', 'reason':'The Numbers tab includes editable mortgage, HOA, tax and rent scenarios.','status':'scenario_ready'},
                       {'question':'How do nearby homes compare?', 'reason':'Comparables are filtered by location, unit size, bedroom count and dates. Views, floor and condition still differ.','status':'context'}]
        if notes: run.events.append({'stage':'research','at':now(),'notes':notes})
        return f"{len(run.sources)} saved sources; listing facts and financial context ready." + (" Broader web search is optional and not configured." if not self.settings.search_key else '')

    def comparables(self,run):
        rejected={};notes=[]
        if run.request.mode!="synthetic" and run.request.use_homeharvest:
            # Rebuild fetched comps on retry; keep only user-supplied candidates.
            run.comparables=[c for c in run.comparables if c.feed!='realtor.com']
            run.claims=[c for c in run.claims if not c.limitation.startswith('Comparable context')]
            facts=run.property.facts
            if not all(facts.get(k) for k in ('city','state','latitude','longitude')):
                return "No comps shown: the subject location could not be verified."
            location=', '.join(str(facts[k]) for k in ('street','city','state','zip') if facts.get(k)) or without_unit(run.property.address)
            filters={'limit':60,'extra_property_data':False}
            if facts.get('beds') is not None: filters.update(beds_min=int(facts['beds']),beds_max=int(facts['beds']))
            if 'condo' in run.property.kind: filters['property_type']=['condos','condo_townhome']
            for category,query in [("sale","sold"),("rent","for_rent")]:
                try: records=adapters.homeharvest(location,query,1.0,**filters)
                except adapters.ProviderError as exc: notes.append(str(exc));continue
                candidates=[]
                for record in records:
                    candidate,reason=screen(record,run.property,category)
                    if reason: rejected[reason]=rejected.get(reason,0)+1;continue
                    candidates.append((candidate,record))
                candidates.sort(key=lambda pair:(pair[0]['distance_miles'],abs(pair[0]['sqft']-facts.get('sqft',pair[0]['sqft']))))
                for candidate,record in candidates[:6]:
                    if any(c.address==candidate['address'] and c.category==category for c in run.comparables): continue
                    source=Source(title='Nearby '+('sale' if category=='sale' else 'rental')+': '+candidate['address'],url=str(record.get('property_url') or ''),kind='listing',feed='realtor.com',event_date=candidate['event_date'],excerpt=json.dumps(record,default=str)[:40000])
                    run.sources.append(source);run.comparables.append(Comparable(source_id=source.id,**candidate))
                    if category=='sale':
                        from datetime import date
                        when=date.fromisoformat(candidate['event_date']).strftime('%B %-d, %Y')
                        place='In the same building, '+str(record['address'].get('unit')) if normalized(record['address'].get('street',''))==normalized(facts.get('street','')) else 'A nearby comparable at '+candidate['address']
                        text=f"{place} reportedly sold for ${candidate['price']:,.0f} on {when}."
                        run.claims.append(Claim(property_id=run.property.id,text=text,kind='reported',status='supported',source_ids=[source.id],limitation='Comparable context; no adjustment for floor, view, condition or transaction terms.'))
        conflicts=compare(run)
        (self.store.folder(run.id)/"comp-conflicts.json").write_text(json.dumps(conflicts,indent=2))
        run.events.append({'stage':'comparables','at':now(),'rejected':rejected,'notes':notes})
        return f"{len(run.comparables)} nearby, size-matched candidates; {sum(rejected.values())} unrelated, stale or incomplete records excluded."

    def vision(self,run):
        if run.request.mode=="synthetic": return "Synthetic observations; Cosmos was not called"
        if not run.media: raise adapters.ProviderError("No authorized photos yet; upload photographs to enable Cosmos analysis")
        failures=[]
        for media in run.media[:12]:
            if any(o.media_id==media.id for o in run.observations): continue
            if media.permission=="review_required": continue
            try:
                result,model=self.cosmos.analyze(self.store.folder(run.id)/media.filename,RUBRIC)
                observation=Observation(media_id=media.id,model=model,**result)
                run.observations.append(observation)
                run.claims.append(Claim(property_id=run.property.id,text=observation.description,kind="visual",status="supported",source_ids=[media.source_id],media_ids=[media.id],limitation="Cosmos observation; confirm against the photograph"))
                self.store.save(run)
            except Exception as exc: failures.append(str(exc) if isinstance(exc,adapters.ProviderError) else type(exc).__name__)
        if failures: raise adapters.ProviderError("; ".join(failures[:3]))
        return f"{len(run.observations)} photo observations recorded for review"

    def finances(self,run):
        if run.request.mode!="synthetic": apply_defaults(run)
        run.finance=calculate(run.request.assumptions)
        return "Calculated with explicit assumptions" if not run.finance["missing"] else "Missing inputs: "+", ".join(run.finance["missing"])

    def story(self,run):
        if run.request.mode=="synthetic":
            run.story=template_story(run)
            return "Template draft using synthetic assumptions"
        run.story=editorial_story(run)
        if self.settings.llm_key and self.settings.llm_model:
            try: run.story=generate_story(run,self.llm)
            except adapters.ProviderError as exc: run.events.append({'stage':'story','at':now(),'notes':[str(exc)]})
        return "Property-specific script, monthly-cost comparison and photo storyboard ready ("+run.story.provider+")."

    def video(self,run):
        from .video import render_video
        return render_video(run,self.store.folder(run.id),self.settings)

    def export(self,run):
        folder=self.store.folder(run.id)
        run.audit=audit(run)
        (folder/"script.md").write_text(script_markdown(run))
        run.artifacts["script"]="script.md"
        data=run.model_dump(mode="json")
        (folder/"dossier.json").write_text(json.dumps(data,indent=2))
        run.artifacts["dossier"]="dossier.json"
        from .workbook import export_workbook
        export_workbook(run,folder,self.settings)
        run.artifacts["workbook"]="analysis.xlsx"
        return "Script, dossier and editable financial workbook saved"

    def revise(self,run_id,assumptions):
        with self.store.lock:
            if run_id in self.pending: raise ValueError("Wait for this run to finish")
            run=self.store.get(run_id)
            run.request.assumptions=Assumptions.model_validate(assumptions)
            run.version+=1
            for key in ["finance","story","export","video"]: run.stages.pop(key,None)
            run.artifacts={}
            run.state="pending"
            self.store.save(run)
        self.submit(run_id,"finance")
        return run

    def upload(self,run_id,data,filename,image=False):
        with self.store.lock:
            if run_id in self.pending: raise ValueError("Wait for this run to finish")
            if len(data)>8_000_000: raise ValueError("File exceeds 8 MB")
            run=self.store.get(run_id)
            source=Source(title=Path(filename).name,kind="document",sha256=adapters.digest(data))
            if image:
                if len(run.media)>=12: raise ValueError("Initial analysis supports at most 12 photos")
                self.add_image(run,data,source,"user_authorized")
            else:
                if data.startswith(b"%PDF"):
                    reader=PdfReader(io.BytesIO(data))
                    if len(reader.pages)>100: raise ValueError("PDF exceeds 100 pages")
                    text="\n".join(f"Page {i+1}: "+(p.extract_text() or "") for i,p in enumerate(reader.pages))
                else: text=data.decode("utf-8")
                source.excerpt=text[:50000]
                source.artifact=f"source-{source.id}.txt"
                (self.store.folder(run_id)/source.artifact).write_text(text[:50000])
                (self.store.folder(run_id)/f"source-{source.id}.original").write_bytes(data)
            run.sources.append(source)
            run.version+=1
            run.artifacts={}
            for key in (["vision"] if image else ["research"])+["story","export","video"]: run.stages.pop(key,None)
            run.state="pending"
            self.store.save(run)
        self.submit(run_id,"vision" if image else "research")
        return run


def synthetic_input():
    return RunInput(mode="synthetic",address="123 Demo Avenue, Unit 5, Example City",confirm_identity=True,use_homeharvest=False,
        assumptions=Assumptions(purchase_price=800000,annual_rate="0.065",rent_monthly=3800,tax_annual=9600,
        insurance_annual=1200,hoa_monthly=650,repairs_monthly=150,utilities_monthly=0,capex_monthly=100,
        source_notes={"purchase_price":"Synthetic example, not a real listing","annual_rate":"Hypothetical fixed rate; not a current lender quote","rent_monthly":"Synthetic rent assumption; not a market comp"}))


def seed_synthetic(run,service):
    if run.sources: return
    source=Source(title="Synthetic demonstration fixture",kind="synthetic",excerpt="All property details and images in this run are invented for software testing.")
    run.sources.append(source)
    run.property.facts={"beds":2,"baths":2,"sqft":950}
    for label in ["KITCHEN", "LIVING ROOM", "BALCONY"]:
        image=Image.new("RGB",(1200,800),"#e6e2d9")
        draw=ImageDraw.Draw(image)
        draw.rectangle((120,170,1080,580),fill="#b9c9c5")
        draw.text((145,210),label,fill="#172c29",font_size=60)
        draw.text((145,340),"SYNTHETIC DEMO IMAGE",fill="#172c29",font_size=38)
        draw.text((145,630),"No real property or Cosmos inference",fill="#172c29",font_size=28)
        buffer=io.BytesIO(); image.save(buffer,"JPEG")
        service.add_image(run,buffer.getvalue(),source,"synthetic")
        media=run.media[-1]
        run.observations.append(Observation(media_id=media.id,description=f"Synthetic illustration labeled {label.lower()}.",room=label.lower(),criteria=[],limitations=["This is not a property photograph."],provider="synthetic",reviewed=True))
    run.claims.append(Claim(property_id=run.property.id,text="This is a synthetic property used to demonstrate how images, evidence and scenarios connect.",kind="reported",status="supported",source_ids=[source.id],media_ids=[run.media[0].id]))
    for price,date,status in [(3500,"2024-02-01","removed"),(4800,"2026-09-24","active")]:
        run.comparables.append(Comparable(address="45 Example Street, Unit 2",category="rent",price=price,price_type="historical_ask" if status=="removed" else "current_ask",event_date=date,status=status,source_id=source.id,beds=1,sqft=650,rationale="Synthetic conflict example; not included in underwriting."))
