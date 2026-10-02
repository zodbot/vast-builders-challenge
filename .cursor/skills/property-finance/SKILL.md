---
name: property-finance
description: Calculate Property Studio mortgage, NOI, rental cash flow and rent-versus-buy scenarios and export an editable financial workbook.
---

Use the app's Numbers tab or `POST /api/runs/RUN_ID/scenarios` with the Assumptions schema. This creates a version and invalidates stale outputs. Run `python -m property_studio finance RUN_ID` to recalculate the existing scenario through downstream exports.

Use `finance.py` as the shared calculation graph. Do not substitute LLM arithmetic. Rates are decimal fractions and must be dated assumptions or sourced quotes. The user has requested automatic defaults: `defaults.py` supplies dated mortgage benchmarks, listing dues, rent scenarios and labeled expense budgets. Preserve their source notes and user overrides. Never invent the asking price; request it only if acquisition fails.

NOI excludes financing and capital expenditure. Assessments are explicit cash obligations. Rent versus buy compares terminal wealth and symmetric invested savings. No tax benefit, PMI cancellation or lender-specific eligibility is inferred. Change structural durations in the app, then regenerate the workbook.

Artifact-tool is the preferred workbook renderer. The portable VM fallback is used only when that runtime is unavailable and uses the same formulas with Python-calculated initial caches. Distinguish this from native Excel recalculation testing.
