"""One expression graph drives Decimal calculations and editable Excel formulas.

Only the deliberately small arithmetic language below is accepted; never eval().
"""
import ast
from decimal import Decimal, ROUND_HALF_UP, localcontext
from .models import Assumptions


D = Decimal


def expression(text, values, refs=None):
    def visit(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return str(node.value) if refs is not None else D(str(node.value))
        if isinstance(node, ast.Name):
            return refs[node.id] if refs is not None else values[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            v = visit(node.operand)
            return f"(-{v})" if refs is not None else -v
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left), visit(node.right)
            op = type(node.op)
            symbols = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.Pow: "^"}
            if op not in symbols:
                raise ValueError("Unsupported operation")
            if refs is not None:
                return f"({left}{symbols[op]}{right})"
            if op is ast.Add: return left + right
            if op is ast.Sub: return left - right
            if op is ast.Mult: return left * right
            if op is ast.Div: return left / right
            return left ** right
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            left, right = visit(node.left), visit(node.comparators[0])
            if not isinstance(node.ops[0], ast.Eq): raise ValueError("Only equality is supported")
            return f"({left}={right})" if refs is not None else left == right
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name == "UNAVAILABLE" and not node.args:
                return '"n.a."' if refs is not None else None
            if name == "IF":
                if refs is None:
                    return visit(node.args[1] if visit(node.args[0]) else node.args[2])
                return "IF(" + ",".join(visit(a) for a in node.args) + ")"
            args = [visit(a) for a in node.args]
            if name not in {"MIN", "MAX", "ROUND"}: raise ValueError("Unsupported function")
            if refs is not None: return name + "(" + ",".join(args) + ")"
            if name == "MIN": return min(args)
            if name == "MAX": return max(args)
            return args[0].quantize(D(1).scaleb(-int(args[1])), rounding=ROUND_HALF_UP)
        raise ValueError("Unsupported expression")
    return visit(ast.parse(text, mode="eval").body)


class Graph:
    def __init__(self):
        self.values = {}
        self.refs = {}
        self.cells = []

    def input(self, key, value, row, note):
        self.refs[key] = f"'Inputs'!D{row}"
        self.values[key] = None if value is None else D(str(value))
        self.cells.append({"key": key, "sheet": "Inputs", "cell": f"D{row}", "label_cell": f"C{row}",
                           "label": key.replace("_", " ").capitalize(), "value": None if value is None else float(value),
                           "note": note, "input": True, "format": "percent" if "pct" in key or key == "annual_rate" else "number"})

    def add(self, key, expr, sheet, cell, label="", note="", fmt="money"):
        names = {n.id for n in ast.walk(ast.parse(expr, mode="eval")) if isinstance(n, ast.Name)} - {"IF", "MIN", "MAX", "ROUND", "UNAVAILABLE"}
        missing = any(self.values[n] is None for n in names)
        with localcontext() as ctx:
            ctx.prec = 36
            try:
                value = None if missing else expression(expr, self.values)
            except (ZeroDivisionError, ArithmeticError):
                value = None
        formula = expression(expr, self.values, self.refs)
        if names:
            dependencies = ",".join(self.refs[n] for n in sorted(names))
            formula = f'IF(COUNT({dependencies})={len(names)},{formula},"n.a.")'
        self.refs[key] = f"'{sheet}'!{cell}"
        self.values[key] = value
        self.cells.append({"key": key, "sheet": sheet, "cell": cell, "label": label,
                           "label_cell": f"C{''.join(filter(str.isdigit, cell))}" if label else "",
                           "formula": "=" + formula, "value": None if value is None else float(value),
                           "note": note, "format": fmt})


def calculate(a: Assumptions):
    g = Graph()
    for row, (key, value) in enumerate(a.model_dump().items(), 6):
        if key == "source_notes": continue
        note = a.source_notes.get(key, "User scenario / editable default; not market evidence")
        g.input(key, value, row, note)
    summary = [
        ("loan", "purchase_price*(1-down_payment_pct)", "Loan principal", ""),
        ("payment", "ROUND(IF(annual_rate==0,loan/(term_years*12),loan*(annual_rate/12)/(1-(1+annual_rate/12)**(-term_years*12))),2)", "Monthly principal and interest", "Fixed rate; PMI is separate"),
        ("effective_income", "rent_monthly*12*(1-vacancy_pct)+other_income_monthly*12", "Annual effective rental income", "Vacancy applies to scheduled rent"),
        ("opex", "tax_annual+insurance_annual+hoa_monthly*12+repairs_monthly*12+utilities_monthly*12+effective_income*management_pct", "Annual operating expenses", "Before debt service and capital expenditure"),
        ("noi", "effective_income-opex", "Annual NOI", "Excludes financing, capital spending, depreciation and income tax"),
        ("cap_rate", "noi/purchase_price", "Cap rate", "NOI / purchase price"),
        ("debt_service", "(payment+pmi_monthly)*12", "Annual financing payments", "Principal, interest and explicitly entered PMI"),
        ("cash_flow", "noi-debt_service-capex_monthly*12-assessment_monthly*MIN(assessment_months,12)", "Year one rental cash flow", "After capital budget and scheduled assessment installments"),
        ("initial_cash", "purchase_price*down_payment_pct+purchase_price*closing_cost_pct+loan*points_pct+assessment_upfront", "Initial cash invested", "Upfront assessment treated as cash obligation"),
        ("cash_on_cash", "IF(initial_cash==0,UNAVAILABLE(),cash_flow/initial_cash)", "Cash on cash return", "Unavailable if no initial cash invested"),
        ("dscr", "IF(debt_service==0,UNAVAILABLE(),noi/debt_service)", "Debt service coverage", "Unavailable for an all-cash purchase; NOI / financing payments"),
        ("owner_monthly", "payment+pmi_monthly+tax_annual/12+insurance_annual/12+hoa_monthly+repairs_monthly+utilities_monthly+capex_monthly+IF(assessment_months==0,0,assessment_monthly)", "Initial owner monthly cash cost", "Before income tax effects; utilities assumed comparable"),
        ("renter_monthly", "rent_monthly+renter_insurance_monthly", "Initial renter monthly cash cost", "Rent plus entered renter insurance"),
        ("monthly_gap", "owner_monthly-renter_monthly", "Initial owner minus renter cost", "Positive means buying requires more monthly cash"),
    ]
    for row, (key, expr, label, note) in enumerate(summary, 6):
        g.add(key, expr, "Rental Operations", f"D{row}", label, note, "percent" if key in {"cap_rate", "cash_on_cash"} else "ratio" if key=="dscr" else "money")
    # Loan schedule uses currency rounding each month and caps the last payment.
    for month in range(1, max(a.term_years, a.holding_years)*12+1):
        r = month + 5
        previous = "loan" if month == 1 else f"balance_{month-1}"
        g.add(f"interest_{month}", f"ROUND({previous}*annual_rate/12,2)", "Amortization", f"E{r}")
        payexpr = f"MIN(payment,{previous}+interest_{month})" if month <= a.term_years*12 else "0"
        if month == a.term_years*12: payexpr = f"{previous}+interest_{month}"
        g.add(f"paid_{month}", payexpr, "Amortization", f"D{r}")
        g.add(f"principal_{month}", f"MAX(paid_{month}-interest_{month},0)", "Amortization", f"F{r}")
        g.add(f"balance_{month}", f"MAX({previous}-principal_{month},0)", "Amortization", f"G{r}")
    # Match budgets symmetrically: both parties invest their monthly savings.
    for month in range(1, a.holding_years*12+1):
        r = month+5
        year = (month-1)//12
        assessment = "assessment_monthly" if month <= a.assessment_months else "0"
        pmi = "pmi_monthly" if month <= a.term_years*12 else "0"
        g.add(f"owner_{month}", f"paid_{month}+{pmi}+(tax_annual/12+insurance_annual/12+hoa_monthly+repairs_monthly+utilities_monthly+capex_monthly)*(1+expense_growth_pct)**{year}+{assessment}", "Rent vs Buy", f"D{r}")
        g.add(f"rent_{month}", f"rent_monthly*(1+rent_growth_pct)**{year}+renter_insurance_monthly", "Rent vs Buy", f"E{r}")
        renterprev = "initial_cash" if month == 1 else f"renter_invest_{month-1}"
        buyerprev = "0" if month == 1 else f"buyer_invest_{month-1}"
        g.add(f"renter_invest_{month}", f"{renterprev}*(1+investment_return_pct)**(1/12)+MAX(owner_{month}-rent_{month},0)", "Rent vs Buy", f"F{r}")
        g.add(f"buyer_invest_{month}", f"{buyerprev}*(1+investment_return_pct)**(1/12)+MAX(rent_{month}-owner_{month},0)", "Rent vs Buy", f"G{r}")
    horizon = a.holding_years*12
    g.add("buyer_wealth", f"purchase_price*(1+appreciation_pct)**holding_years*(1-selling_cost_pct)-balance_{horizon}+buyer_invest_{horizon}", "Rental Operations", "D21", "Buyer terminal wealth", "Net sale equity plus invested monthly savings; no income tax effects")
    g.add("renter_wealth", f"renter_invest_{horizon}", "Rental Operations", "D22", "Renter terminal wealth", "Initial cash invested plus invested monthly savings")
    g.add("wealth_gap", "buyer_wealth-renter_wealth", "Rental Operations", "D23", "Buyer minus renter wealth", "Positive favors buying under these assumptions")
    for cell in list(g.cells):
        if cell['sheet']=='Rental Operations':
            g.add('display_'+cell['key'],cell['key'],'Summary',cell['cell'],cell['label'],cell['note'],cell['format'])
    # Hypothetical comparison cases; these adjustments are not market estimates.
    row=6
    for price_factor in ['0.9','1','1.1']:
        for rent_factor in ['0.85','1','1.15']:
            prefix=f'sensitivity_{row}'
            g.add(prefix+'_price',f'purchase_price*{price_factor}','Sensitivity',f'D{row}',f'Price × {price_factor}; rent × {rent_factor}')
            g.add(prefix+'_rent',f'rent_monthly*{rent_factor}','Sensitivity',f'E{row}')
            g.add(prefix+'_payment',f'ROUND(payment*{price_factor},2)','Sensitivity',f'F{row}')
            # Grow buyer tax budget with purchase price in this explicitly labeled scenario.
            g.add(prefix+'_noi',f'({prefix}_rent*12*(1-vacancy_pct)+other_income_monthly*12)*(1-management_pct)-(tax_annual*{price_factor}+insurance_annual+hoa_monthly*12+repairs_monthly*12+utilities_monthly*12)','Sensitivity',f'G{row}')
            g.add(prefix+'_cap',f'{prefix}_noi/{prefix}_price','Sensitivity',f'H{row}',fmt='percent')
            g.add(prefix+'_cash',f'{prefix}_noi-({prefix}_payment+pmi_monthly)*12-capex_monthly*12-assessment_monthly*MIN(assessment_months,12)','Sensitivity',f'I{row}')
            row+=1
    metrics = {k: None if g.values[k] is None else float(g.values[k]) for k, *_ in summary}
    metrics.update({k: None if g.values[k] is None else float(g.values[k]) for k in ["buyer_wealth", "renter_wealth", "wealth_gap"]})
    if not g.values["initial_cash"]: metrics["cash_on_cash"] = None
    if not g.values["debt_service"]: metrics["dscr"] = None
    missing = [k for k, v in a.model_dump().items() if v is None]
    return {"version": "1", "metrics": metrics, "missing": missing,
            "cells": g.cells, "notes": ["All inputs are editable scenarios unless individually sourced.",
            "PMI is a fixed entered budget; no automatic cancellation is assumed.",
            "Utilities must reflect costs paid only by the owner; shared costs should be excluded from both sides.",
            "No income-tax benefit or capital-gains tax is modeled.",
            "Loan term, holding period and assessment duration are structural inputs; regenerate in the app after changing them."]}
