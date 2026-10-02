"""Reject wrong-market, future-dated and dissimilar records before showing comps."""
import json
from datetime import date
from math import radians,sin,cos,asin,sqrt
from .listing import clean_unit,without_unit,normalized,identity_match


def distance_miles(lat1,lon1,lat2,lon2):
    a,b,c,d=map(radians,map(float,(lat1,lon1,lat2,lon2)))
    return 3958.8*2*asin(min(1,sqrt(sin((c-a)/2)**2+cos(a)*cos(c)*sin((d-b)/2)**2)))


def screen(record,subject,category,today=None):
    today=today or date.today();f=subject.facts;address=record.get('address') or {};desc=record.get('description') or {}
    if not address.get('formatted_address'): return None,'missing address'
    if identity_match(subject.address,subject.unit,record): return None,'subject property'
    for key in ('city','state'):
        if not f.get(key) or normalized(f[key])!=normalized(address.get(key,'')): return None,'different or unresolved market'
    coords=(f.get('latitude'),f.get('longitude'),record.get('latitude'),record.get('longitude'))
    if any(x is None for x in coords): return None,'missing coordinates'
    distance=distance_miles(*coords)
    if distance>1.0: return None,'outside one mile'
    beds,sqft=desc.get('beds'),desc.get('sqft')
    if beds is None or sqft is None or not sqft: return None,'missing unit size'
    if f.get('beds') is not None and abs(beds-f['beds'])>0: return None,'different bedroom count'
    if f.get('sqft') and not .7<=sqft/f['sqft']<=1.4: return None,'dissimilar floor area'
    style=str(desc.get('style') or desc.get('type') or '').lower()
    if 'condo' in subject.kind.lower() and not any(s in style for s in ('condo','apartment','town')): return None,'different property type'
    status=(record.get('status') or '').upper()
    if category=='sale':
        price=record.get('last_sold_price') or desc.get('sold_price');rawdate=record.get('last_sold_date')
        if status!='SOLD': return None,'not a closed sale'
    else:
        price=record.get('list_price');rawdate=record.get('last_update_date') or record.get('list_date')
        if status!='FOR_RENT': return None,'not an active rental'
    if not price or price<=0: return None,'missing unit price'
    details=json.dumps(record.get('details') or [])+' '+str(desc.get('text') or '')
    if any(term in details.lower() for term in ('below market rate','below-market','deed restricted','deed-restricted','fractional ownership')):
        return None,'restricted or fractional ownership'
    subject_price=f.get('asking_price')
    if category=='sale' and subject_price and f.get('sqft') and not .5<=(price/sqft)/(subject_price/f['sqft'])<=2:
        return None,'outlier price per square foot'

    try: event=date.fromisoformat(str(rawdate)[:10])
    except ValueError: return None,'missing or invalid event date'
    age=(today-event).days
    if age<0: return None,'future event date'
    if age>(365 if category=='sale' else 120): return None,'stale price record'
    return {'address':address['formatted_address'],'category':category,'price':price,'price_type':'executed' if category=='sale' else 'current_ask',
            'event_date':event.isoformat(),'status':status,'feed':'realtor.com','beds':beds,
            'baths':desc.get('baths_full',0)+(desc.get('baths_half') or 0)*.5 if desc.get('baths_full') is not None else None,
            'sqft':sqft,'included':True,'distance_miles':round(distance,2),
            'rationale':f'{distance:.2f} miles away; same bedroom count; similar floor area. '+('Reported closed sale.' if category=='sale' else 'Active asking rent; date is feed update, not lease execution.')+' Building, floor, condition and view can differ.'},None
