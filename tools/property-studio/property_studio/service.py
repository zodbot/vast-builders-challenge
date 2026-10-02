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
from .story import template_story, generate_story, audit, script_markdown
from .storage import Store


RUBRIC = ["room and visible finishes", "visible condition without hidden diagnoses", "view and obstructions",
          "outdoor space", "storage", "lighting appearance and uncertainty", "staging", "useful scene composition"]


def normalized(text):
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).split()


def identity_match(address, unit, record):
    candidate=record.get("address") or {}
    expected=set(normalized(address))
    actual=set(normalized(candidate.get("formatted_address") or ""))
    # Conservative exact-token inclusion; aliases need explicit review.
    if not expected or not expected<=actual: return False
    if unit and str(candidate.get("unit", "")).lower().removeprefix("unit ")!=unit.lower(): return False
    return True


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
                association=request.association,identity_status="synthetic" if request.mode=="synthetic" else "user_confirmed" if request.confirm_identity and request.address else "needs_review"))
        run.questions=questions(run)
        self.store.save(run)
        return run

    def submit(self, run_id, start="intake"):
        with self.store.lock:
            if run_id in self.pending: raise ValueError("This run is already processing")
            run=self.store.get(run_id)
            if run.state!="pending":
                run.version+=1
                run.artifacts={}
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
                dirty=True
                self.stage(run,name,fn)
            run.audit=audit(run)
            run.state="demo" if run.request.mode=="synthetic" else "partial" if any(s["state"]=="partial" for s in run.stages.values()) else "draft"
            self.store.save(run)
            if self.settings.s3_bucket:
                self.stage(run,"storage",lambda r:self.store.sync(r))
                if run.stages["storage"]["state"]=="partial": run.state="partial"
                self.store.save(run)
        finally:
            with self.store.lock: self.pending.discard(run_id)

    def source_url(self,run,url,kind="public_record"):
        if any(s.url==url for s in run.sources): return
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

    def intake(self,run):
        if run.request.mode=="synthetic":
            seed_synthetic(run,self)
            return "Synthetic inputs loaded; no live lookup or Cosmos inference"
        if run.request.url:
            self.source_url(run,run.request.url,"listing")
        if run.property.identity_status=="needs_review":
            if run.request.url:
                source=run.sources[-1]
                run.questions.insert(0,{"question":"Confirm exact address and unit for this listing", "reason":source.title,"status":"needs_input"})
            return "Exact address and unit need user confirmation"
        errors=[]
        if run.request.use_homeharvest:
            try:
                records=adapters.homeharvest(run.property.address)
                matches=[r for r in records if identity_match(run.property.address,run.property.unit,r)]
                if len(matches)==1:
                    record=matches[0]
                    raw=json.dumps(record,default=str)
                    source=Source(title="HomeHarvest listing",url=str(record.get("property_url") or ""),kind="listing",feed="realtor.com",excerpt=raw[:50000],sha256=adapters.digest(raw.encode()))
                    run.sources.append(source)
                    desc=record.get("description") or {}
                    for k in ["beds","sqft","year_built","baths_full","baths_half"]:
                        if desc.get(k) is not None:
                            run.property.facts[k]=desc[k]
                            run.claims.append(Claim(property_id=run.property.id,text=f"The listing reports {k.replace('_',' ')}: {desc[k]}.",kind="reported",source_ids=[source.id]))
                    if desc.get("baths_full") is not None:
                        run.property.facts["baths"]=desc["baths_full"]+0.5*(desc.get("baths_half") or 0)
                    if record.get("list_price") and run.request.assumptions.purchase_price is None:
                        run.request.assumptions.purchase_price=record["list_price"]
                        run.request.assumptions.source_notes["purchase_price"]=f"Listing asking price; source {source.id}; retrieved {source.retrieved_at}"
                    images=([desc["primary_photo"]] if desc.get("primary_photo") else [])+(desc.get("alt_photos") or [])
                    if run.request.authorize_images:
                        for url in images[:12]:
                            try:
                                data,_,final=adapters.fetch_public(str(url))
                                self.add_image(run,data,source,"user_authorized",final)
                            except Exception as exc: errors.append("Photo retrieval failed: "+type(exc).__name__)
                else:
                    errors.append("HomeHarvest did not return exactly one confirmed unit match; use manual sources")
            except Exception as exc: errors.append("HomeHarvest unavailable: "+type(exc).__name__)
        for url in run.request.image_urls:
            if not run.request.authorize_images:
                errors.append("Authorize the supplied images before downloading")
                break
            try:
                data,_,final=adapters.fetch_public(url)
                source=Source(title="User-supplied property photo",url=final,kind="user")
                run.sources.append(source)
                self.add_image(run,data,source,"user_authorized",final)
            except Exception as exc: errors.append("Image could not be read: "+type(exc).__name__)
        if errors: raise adapters.ProviderError("; ".join(errors))
        return "Identity and source data recorded"

    def research(self,run):
        if run.request.mode=="synthetic": return "Synthetic research fixture; all real HOA records remain unreviewed"
        errors=[]
        urls=list(run.request.source_urls)
        if self.settings.search_key:
            for query in search_queries(run):
                try:
                    urls += [r["url"] for r in adapters.search_web(self.settings,query) if r.get("url")]
                except adapters.ProviderError as exc: errors.append(str(exc))
        for url in list(dict.fromkeys(urls))[:20]:
            try: self.source_url(run,url)
            except Exception as exc: errors.append("A research source was unavailable: "+type(exc).__name__)
        if self.settings.llm_key and self.settings.llm_model:
            for source in run.sources:
                if source.excerpt and not any(source.id in c.source_ids for c in run.claims):
                    try: extract_claims(run,source,self.llm)
                    except Exception as exc: errors.append("Source extraction needs review: "+type(exc).__name__)
        if not self.settings.search_key: errors.append("Live search is not configured; supplied documents and URLs are available")
        if not self.settings.llm_key or not self.settings.llm_model: errors.append("Language-model extraction is not configured; review source excerpts directly")
        if errors: raise adapters.ProviderError("; ".join(errors[:4]))
        return "Research sources gathered; extracted claims require review"

    def comparables(self,run):
        if run.request.mode!="synthetic" and run.request.use_homeharvest:
            for category,query in [("sale","sold"),("rent","for_rent")]:
                for record in adapters.homeharvest(run.property.address,query,0.7):
                    desc=record.get("description") or {}
                    address=(record.get("address") or {}).get("formatted_address")
                    price=(record.get("last_sold_price") or desc.get("sold_price")) if category=="sale" else record.get("list_price")
                    if not address or not price or identity_match(run.property.address,run.property.unit,record): continue
                    url=str(record.get("property_url") or "")
                    if any(c.address==address and c.category==category for c in run.comparables): continue
                    source=Source(title="Comparable candidate",url=url,kind="listing",feed="realtor.com",excerpt=json.dumps(record,default=str)[:40000])
                    run.sources.append(source)
                    run.comparables.append(Comparable(address=address,category=category,price=price,
                        price_type="executed" if category=="sale" else "current_ask",event_date=record.get("last_sold_date") if category=="sale" else record.get("list_date"),
                        status=record.get("status") or "unknown",source_id=source.id,feed="realtor.com",beds=desc.get("beds"),sqft=desc.get("sqft")))
        conflicts=compare(run)
        (self.store.folder(run.id)/"comp-conflicts.json").write_text(json.dumps(conflicts,indent=2))
        return f"{len(run.comparables)} candidates; {len(conflicts)} price histories need reconciliation. No automatic premiums applied."

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
                run.claims.append(Claim(property_id=run.property.id,text=observation.description,kind="visual",source_ids=[media.source_id],media_ids=[media.id],limitation="Cosmos observation; confirm against the photograph"))
                self.store.save(run)
            except Exception as exc: failures.append(str(exc) if isinstance(exc,adapters.ProviderError) else type(exc).__name__)
        if failures: raise adapters.ProviderError("; ".join(failures[:3]))
        return f"{len(run.observations)} photo observations recorded for review"

    def finances(self,run):
        run.finance=calculate(run.request.assumptions)
        return "Calculated with explicit assumptions" if not run.finance["missing"] else "Missing inputs: "+", ".join(run.finance["missing"])

    def story(self,run):
        run.story=template_story(run)
        if run.request.mode=="synthetic": return "Template draft using synthetic assumptions"
        if self.settings.llm_key and self.settings.llm_model:
            run.story=generate_story(run,self.llm)
            return "Model-generated draft; review citations and narration before use"
        raise adapters.ProviderError("Template draft created. Configure W&B inference for generated hooks and narration")

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
            for key in ["finance","story","export"]: run.stages.pop(key,None)
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
            for key in (["vision"] if image else ["research"])+["story","export"]: run.stages.pop(key,None)
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
