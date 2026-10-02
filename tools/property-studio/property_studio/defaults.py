"""Editable, attributed starting assumptions; never silently fill an asking price."""
from datetime import date
from decimal import Decimal as D
from statistics import median
from .models import Source

RATE_DATE='2026-10-01'
RATE_URL='https://freddiemac.gcs-web.com/news-releases/news-release-details/mortgage-rates-average-728'
RATE=D('0.0728')


def apply_defaults(run):
    a=run.request.assumptions;facts=run.property.facts
    def put(key,value,note):
        if getattr(a,key) is None and value is not None:
            setattr(a,key,D(str(value)))
            a.source_notes[key]=note
    rate_source=next((s for s in run.sources if s.url==RATE_URL),None)
    if a.annual_rate is None:
        if not rate_source:
            rate_source=Source(title='Freddie Mac 30-year mortgage benchmark',url=RATE_URL,kind='public_record',event_date=RATE_DATE,
                               excerpt='30-year fixed mortgage average: 7.28% as of October 1, 2026. Conventional conforming benchmark, not a property-specific loan quote.')
            run.sources.append(rate_source)
        stale=' Older benchmark; refresh before relying on it.' if (date.today()-date.fromisoformat(RATE_DATE)).days>30 else ''
        put('annual_rate',RATE,f'Freddie Mac 30-year benchmark, {RATE_DATE}; source {rate_source.id}. Editable scenario, not a jumbo or lender quote.'+stale)
    if a.purchase_price is None: return
    price=a.purchase_price
    condo=any(x in run.property.kind.lower() for x in ('condo','apartment','town'))
    put('tax_annual',price*D(str(facts.get('property_tax_rate') or 1.25))/100,
        'Buyer tax budget: asking price × '+str(facts.get('property_tax_rate') or 1.25)+'%. '+('Rate reported by listing; reassessment and local charges may differ.' if facts.get('property_tax_rate') else 'Editable planning assumption; replace with local tax estimate.'))
    put('insurance_annual',1200 if condo else 2400,'Editable annual insurance budget; not an insurer quote.')
    put('hoa_monthly',500 if condo else 0,'Editable HOA placeholder; actual dues were unavailable.' if condo else 'Assumed no HOA; replace if applicable.')
    put('repairs_monthly',(price*D('0.0025')/12).quantize(D('1')),'Maintenance budget: 0.25% of purchase price per year; editable assumption.')
    put('capex_monthly',(price*D('0.0025')/12).quantize(D('1')),'Capital reserve budget: 0.25% of purchase price per year; editable assumption, separate from HOA reserves.')
    put('utilities_monthly',0,'Assumed tenant/occupant-paid utilities; editable owner expense budget.')
    rentals=[float(c.price) for c in run.comparables if c.category=='rent' and c.included]
    if len(rentals)>=3:
        put('rent_monthly',round(median(rentals)),f'Median of {len(rentals)} filtered nearby asking rents, retrieved {date.today()}; scenario only, not achieved rent.')
    elif facts.get('rent_estimate'):
        put('rent_monthly',facts['rent_estimate'],'Listing portal automated rent estimate; scenario only, not a lease or verified market rent.')
    else:
        put('rent_monthly',(price*D('0.004')).quantize(D('1')),'Placeholder rent scenario: 0.4% of purchase price/month. No supported rent estimate available; editable, not market evidence.')
