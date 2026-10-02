from decimal import Decimal as D
import pytest
from pydantic import ValidationError
from property_studio.models import Assumptions
from property_studio.finance import calculate, expression


def example(**changes):
    data=dict(purchase_price=100000,down_payment_pct="0.2",annual_rate=0,term_years=10,
              rent_monthly=1200,vacancy_pct="0.05",tax_annual=1200,insurance_annual=600,
              hoa_monthly=100,repairs_monthly=50,utilities_monthly=0,capex_monthly=0,management_pct=0)
    data.update(changes)
    return Assumptions(**data)


def test_zero_rate_noi_and_amortization():
    result=calculate(example())
    m=result['metrics']
    assert m['payment']==666.67
    assert m['noi']==10080
    assert m['cap_rate']==pytest.approx(.1008)
    cells={c['key']:c for c in result['cells']}
    assert cells['balance_120']['value']==0
    assert sum(cells[f'principal_{i}']['value'] for i in range(1,121))==pytest.approx(80000)


def test_fixed_payment_against_independent_formula():
    a=example(purchase_price=800000,annual_rate='.065',term_years=30)
    p=640000; r=.065/12; n=360
    expected=round(p*r*(1+r)**n/((1+r)**n-1),2)
    assert calculate(a)['metrics']['payment']==expected


def test_missing_rent_does_not_become_zero():
    m=calculate(example(rent_monthly=None))['metrics']
    assert m['noi'] is None
    assert m['renter_wealth'] is None
    assert m['payment']==666.67


def test_assessments_do_not_reduce_noi():
    base=calculate(example())['metrics']
    special=calculate(example(assessment_upfront=5000,assessment_monthly=300,assessment_months=6))['metrics']
    assert special['noi']==base['noi']
    assert special['cash_flow']==pytest.approx(base['cash_flow']-1800)
    assert special['initial_cash']==base['initial_cash']+5000


def test_all_cash_buy_vs_rent_symmetric_savings():
    a=example(down_payment_pct=1,closing_cost_pct=0,selling_cost_pct=0,holding_years=1,
              tax_annual=0,insurance_annual=0,hoa_monthly=0,repairs_monthly=0,rent_monthly=1000)
    m=calculate(a)['metrics']
    assert m['payment']==0
    assert m['dscr'] is None
    assert m['buyer_wealth']==112000
    assert m['renter_wealth']==100000
    assert m['wealth_gap']==12000


def test_capital_budget_separate_from_noi():
    a=calculate(example())['metrics']; b=calculate(example(capex_monthly=100))['metrics']
    assert a['noi']==b['noi']
    assert b['cash_flow']==a['cash_flow']-1200


def test_invalid_finance_inputs():
    for value in ['NaN','Infinity',-1]:
        with pytest.raises(ValidationError): example(annual_rate=value)
    with pytest.raises(ValidationError): example(down_payment_pct=2)


def test_expression_language_cannot_execute_code():
    with pytest.raises(ValueError): expression("__import__('os').system('echo wrong')",{})


def test_unavailable_denominator_exports_as_na():
    result=calculate(example(down_payment_pct=1))
    cell=next(c for c in result['cells'] if c['key']=='dscr')
    assert cell['value'] is None
    assert '"n.a."' in cell['formula']
