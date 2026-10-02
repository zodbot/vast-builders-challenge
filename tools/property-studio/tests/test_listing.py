import json
from datetime import date
from decimal import Decimal
import pytest
from property_studio.listing import parse_listing,address_from_url,identity_match
from property_studio.models import RunInput,Run,Property,Source,Comparable
from property_studio.defaults import apply_defaults
from property_studio.comps import screen
from property_studio.adapters import homeharvest,ProviderError

URL='https://www.zillow.com/homedetails/501-Beale-St-UNIT-15H-San-Francisco-CA-94105/123_zpid/'


def test_url_in_address_is_normalized_without_recursion():
    r=RunInput(address=URL)
    assert r.url==URL and not r.address and r.authorize_images
    assert '501 Beale' in address_from_url(URL)
    assert address_from_url('https://unknown.example/501-Beale-St-CA-94105')==''


def test_zillow_structured_listing_and_photos():
    prop={'zpid':123,'address':{'streetAddress':'501 Beale St Unit 15H','city':'San Francisco','state':'CA','zipcode':'94105'},
          'price':1595000,'monthlyHoaFee':1532,'bedrooms':2,'bathrooms':2,'livingArea':1161,'rentZestimate':7128,
          'responsivePhotos':[{'url':'https://example.com/photo.jpg'}],'resoFacts':{'yearBuilt':2006}}
    data='<script id="__NEXT_DATA__">'+json.dumps({'props':{'cache':json.dumps({'property':prop})}})+'</script>'
    record=parse_listing(data.encode(),URL)
    assert record['address']['unit']=='15H'
    assert record['list_price']==1595000 and record['hoa_fee']==1532
    assert record['description']['alt_photos']==['https://example.com/photo.jpg']
    assert identity_match('501 Beale Street San Francisco','15h',record)
    assert not identity_match('501 Beale St San Francisco','9B',record)
    assert not identity_match(URL,None,record)


def test_generic_brokerage_jsonld():
    data={'@type':'RealEstateListing','offers':{'@type':'Offer','price':'850000','itemOffered':{'@type':'Apartment','numberOfBedrooms':2,
          'address':{'streetAddress':'10 Main St Apt 2','addressLocality':'Oakland','addressRegion':'CA','postalCode':'94612'},'floorSize':{'value':900}}}}
    r=parse_listing(('<script type="application/ld+json">'+json.dumps(data)+'</script>').encode(),'https://broker.example/listing/10')
    assert r['address']['unit']=='2' and r['list_price']==850000 and r['description']['sqft']==900


def subject():
    return Property(address='501 Beale St Unit 15H San Francisco CA 94105',unit='15H',kind='condos',identity_status='resolved',
                    facts={'city':'San Francisco','state':'CA','latitude':37.786,'longitude':-122.389,'beds':2,'sqft':1161,'asking_price':1595000})


def candidate():
    return {'address':{'formatted_address':'501 Beale St Unit 7H, San Francisco, CA 94105','full_line':'501 Beale St Unit 7H','unit':'7H','city':'San Francisco','state':'CA'},
            'latitude':37.786,'longitude':-122.389,'last_sold_date':'2026-07-08','last_sold_price':1475000,'status':'SOLD',
            'description':{'beds':2,'baths_full':2,'sqft':1161,'style':'CONDOS'}}


def test_comps_reject_wrong_market_future_dates_and_dissimilar_units():
    r=candidate();c,reason=screen(r,subject(),'sale',date(2026,10,2));assert c['included'] and reason is None
    r['address']['city']='Saint Croix';assert screen(r,subject(),'sale',date(2026,10,2))[0] is None
    r=candidate();r['last_sold_date']='2089-12-12';assert screen(r,subject(),'sale',date(2026,10,2))[1]=='future event date'
    r=candidate();r['description']['beds']=1;assert screen(r,subject(),'sale',date(2026,10,2))[1]=='different bedroom count'
    r=candidate();r['last_sold_price']=300000;assert screen(r,subject(),'sale',date(2026,10,2))[1]=='outlier price per square foot'


def test_homeharvest_never_receives_portal_url(monkeypatch):
    monkeypatch.setattr('subprocess.run',lambda *a,**k:pytest.fail('URL reached HomeHarvest'))
    with pytest.raises(ProviderError,match='resolved street address'): homeharvest(URL)


def test_defaults_fill_costs_but_keep_user_overrides_and_never_invent_price():
    req=RunInput(address='501 Beale St',assumptions={'purchase_price':1595000,'annual_rate':'.06','hoa_monthly':1532})
    run=Run(request=req,property=subject());run.property.facts['rent_estimate']=7128
    apply_defaults(run)
    assert run.request.assumptions.annual_rate==Decimal('.06')
    assert run.request.assumptions.hoa_monthly==1532
    assert run.request.assumptions.rent_monthly==7128
    assert run.request.assumptions.insurance_annual>0
    assert 'automated' in run.request.assumptions.source_notes['rent_monthly']
    empty=Run(request=RunInput(address='1 Main St'),property=subject());apply_defaults(empty)
    assert empty.request.assumptions.purchase_price is None


def test_editorial_draft_is_specific_and_auditable():
    from property_studio.service import Service
    from property_studio.config import Settings
    from property_studio.finance import calculate
    from property_studio.story import editorial_story,audit
    from property_studio.models import Claim
    r=Run(request=RunInput(address='501 Beale St Unit 15H',assumptions={'purchase_price':1595000,'hoa_monthly':1532}),property=subject())
    source=Source(title='Listing');r.sources.append(source)
    r.claims.append(Claim(property_id=r.property.id,text='The listing is for '+r.property.address+'.',kind='reported',status='supported',source_ids=[source.id]))
    for k in ['beds','sqft']:
        r.claims.append(Claim(property_id=r.property.id,text=f'The listing reports {r.property.facts[k]} {k}.',kind='reported',status='supported',source_ids=[source.id]))
    apply_defaults(r);r.finance=calculate(r.request.assumptions);r.story=editorial_story(r)
    assert 'plot twist' in r.story.scenes[0].narration
    assert not [f for f in audit(r) if f['severity']=='block']
    assert any(s.calculation_ids==['owner_monthly','hoa_monthly'] for s in r.story.scenes)
