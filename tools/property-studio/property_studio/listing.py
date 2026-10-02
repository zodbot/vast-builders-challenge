"""Resolve public listing pages before querying the Realtor.com adapter."""
import json
import re
from urllib.parse import unquote, urlsplit
from bs4 import BeautifulSoup

ALIASES = {'street':'st','avenue':'ave','boulevard':'blvd','road':'rd','drive':'dr','lane':'ln',
           'court':'ct','place':'pl','terrace':'ter','california':'ca','apartment':'unit','apt':'unit',
           'suite':'unit','north':'n','south':'s','east':'e','west':'w'}
UNIT = re.compile(r'\b(?:unit|apt|apartment|suite)\s*#?\s*([a-z0-9-]+)|#\s*([a-z0-9-]+)',re.I)


def normalized(text):
    return [ALIASES.get(x,x) for x in re.findall(r'[a-z0-9]+',str(text).lower())]


def unit_of(text):
    m=UNIT.search(text or '')
    return (m.group(1) or m.group(2)).upper() if m else None


def clean_unit(unit):
    return re.sub(r'^(?:unit|apt|apartment|suite)\s*#?\s*|^#','',str(unit or '').strip(),flags=re.I).upper()


def without_unit(address):
    return re.sub(r'\s+,',',',UNIT.sub('',address)).strip(' ,')


def identity_match(address,unit,record):
    if re.match(r'https?://',address,re.I): return False
    candidate=record.get('address') or {}
    expected=set(normalized(without_unit(address)))
    actual=set(normalized(without_unit(candidate.get('formatted_address') or candidate.get('full_line') or '')))
    if not expected or not expected<=actual: return False
    expected_unit=clean_unit(unit or unit_of(address))
    actual_unit=clean_unit(candidate.get('unit') or unit_of(candidate.get('full_line') or candidate.get('formatted_address') or ''))
    return not expected_unit or expected_unit==actual_unit


def address_from_url(url):
    """Known portal slugs are hints for exact lookup, never property evidence."""
    u=urlsplit(url);host=(u.hostname or '').lower();path=unquote(u.path)
    if not any(host==h or host.endswith('.'+h) for h in ('zillow.com','realtor.com','redfin.com','trulia.com')): return ''
    for part in path.split('/'):
        part=part.split('_zpid')[0]
        match=re.search(r'^(\d[^/]*?)[_-]([A-Z]{2})[_-](\d{5})(?:[_-]|$)',part,re.I)
        if match:
            return re.sub('[-_]',' ',match.group(1)) + ', ' + match.group(2).upper()+' '+match.group(3)
    # Redfin places the state/city/ZIP in separate path segments.
    m=re.search(r'/([A-Z]{2})/([^/]+)/(\d[^/]+)-(\d{5})/home/',path,re.I)
    if m: return m[3].replace('-',' ')+', '+m[2].replace('-',' ')+', '+m[1].upper()+' '+m[4]
    return ''


def objects(value,depth=0):
    if depth>22: return
    if isinstance(value,dict):
        yield value
        for v in value.values(): yield from objects(v,depth+1)
    elif isinstance(value,list):
        for v in value: yield from objects(v,depth+1)
    elif isinstance(value,str) and value.startswith('{'):
        try: yield from objects(json.loads(value),depth+1)
        except (ValueError,RecursionError): pass


def number(value):
    if isinstance(value,dict): value=value.get('value')
    if isinstance(value,str):
        m=re.search(r'\d[\d,]*(?:\.\d+)?',value)
        value=m[0].replace(',','') if m else None
    try: return float(value) if value is not None else None
    except (ValueError,TypeError): return None


def parse_listing(data,url):
    soup=BeautifulSoup(data,'html.parser')
    record={}; photos=[]
    scripts=[]
    for node in soup.select('script[type="application/ld+json"], script#__NEXT_DATA__'):
        try: scripts.append(json.loads(node.string or node.get_text()))
        except ValueError: continue
    candidates=[o for item in scripts for o in objects(item)]
    zpid=re.search(r'/(\d+)_zpid',url)
    zillow=next((o for o in candidates if 'zpid' in o and 'price' in o and 'address' in o
                 and (not zpid or str(o['zpid'])==zpid[1])),None)
    if zillow:
        a=zillow.get('address') or {};facts=zillow.get('resoFacts') or {}
        record={'address':{'full_line':a.get('streetAddress'),'city':a.get('city'),'state':a.get('state'),'zip':a.get('zipcode')},
                'list_price':zillow.get('price'),'hoa_fee':zillow.get('monthlyHoaFee'),
                'latitude':zillow.get('latitude'),'longitude':zillow.get('longitude'),
                'rent_estimate':zillow.get('rentZestimate'),'property_tax_rate':zillow.get('propertyTaxRate'),
                'description':{'beds':zillow.get('bedrooms'),'baths_full':zillow.get('bathrooms'),'sqft':zillow.get('livingArea'),
                               'year_built':facts.get('yearBuilt'),'style':zillow.get('homeType'),'text':zillow.get('description') or ''}}
        for p in zillow.get('responsivePhotos') or zillow.get('originalPhotos') or []:
            variants=(p.get('mixedSources') or {}).get('jpeg') or []
            best=min(variants,key=lambda x:abs(x.get('width',0)-1152)) if variants else p
            if best.get('url'): photos.append(best['url'])
    else:
        # JSON-LD is shared by many brokerages and listing portals.
        eligible=[o for o in candidates if isinstance(o.get('address'),dict) and o['address'].get('streetAddress') and not any(t in str(o.get('@type','')).lower() for t in ('organization','localbusiness','realestateagent'))]
        target=next((o for o in eligible if any(t in str(o.get('@type','')).lower() for t in ('apartment','house','residence','accommodation'))),eligible[0] if eligible else None)
        if target:
            a=target['address'];offer=next((o for o in candidates if o.get('price') and ('itemOffered' in o or o.get('@type')=='Offer')), {})
            record={'address':{'full_line':a.get('streetAddress'),'city':a.get('addressLocality'),'state':a.get('addressRegion'),'zip':a.get('postalCode')},
                    'list_price':number(offer.get('price')),'latitude':(target.get('geo') or {}).get('latitude'),
                    'longitude':(target.get('geo') or {}).get('longitude'),
                    'description':{'beds':number(target.get('numberOfBedrooms')),'baths_full':number(target.get('numberOfBathroomsTotal')),
                                   'sqft':number(target.get('floorSize')),'text':target.get('description') or '', 'style':target.get('@type')}}
            images=target.get('image') or []
            if not isinstance(images,list): images=[images]
            photos += [x.get('url') if isinstance(x,dict) else x for x in images]
    address=record.setdefault('address',{})
    if address.get('full_line'):
        address['unit']=unit_of(address['full_line'])
        address['street']=without_unit(address['full_line'])
        address['formatted_address']=', '.join(str(address[k]) for k in ['full_line','city','state','zip'] if address.get(k))
    else:
        title=soup.title.get_text(' ',strip=True) if soup.title else ''
        candidate=title.split('|')[0].strip()
        if re.match(r'^\d+\s+\w',candidate) and re.search(r',\s*[A-Z]{2}\s+\d{5}',candidate):
            address['formatted_address']=candidate;address['unit']=unit_of(candidate)
    record['property_url']=url
    desc=record.setdefault('description',{})
    if not photos:
        for node in soup.select('meta[property="og:image"],meta[name="twitter:image"]'):
            if node.get('content'): photos.append(node['content'])
    desc['alt_photos']=list(dict.fromkeys(p for p in photos if isinstance(p,str) and p.startswith(('http://','https://'))))
    if desc['alt_photos']: desc['primary_photo']=desc['alt_photos'][0]
    # Never read the page's generic mortgage calculator as actual taxes or costs.
    text=soup.get_text(' ',strip=True)
    if record.get('hoa_fee') is None:
        m=re.search(r'\$([\d,]+)\s*/mo\s*HOA',text,re.I)
        if m: record['hoa_fee']=number(m[1])
    return record


def select_photos(urls,limit=8):
    urls=list(dict.fromkeys(urls))
    if len(urls)<=limit: return urls
    # Cover the full gallery instead of spending all image calls on the first kitchen.
    indices=[0,1]+[round(2+i*(len(urls)-3)/(limit-3)) for i in range(limit-2)]
    return [urls[i] for i in indices]
