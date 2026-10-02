---
name: property-comparables
description: Review Property Studio sale and rental comparable candidates, including conflicting portal prices and outdated rental records.
---

Inspect `show RUN_ID` and the saved dossier in `tools/property-studio`. Comparable candidates live in the run; the authenticated API accepts additional records at `POST /api/runs/RUN_ID/comparables` using the Comparable schema in `property_studio/models.py`.

Keep current asks, historical asks, executed transactions, algorithmic estimates and scenarios separate. A removed listing does not establish an achieved price. Preserve concessions, lease term, original feed and event date. Syndicated copies are not independent confirmations.

Explain actual bedrooms versus dens, bath-count discrepancies, floor, view, laundry, outdoor space and condition. No unsupported percentage premiums or double counting floor and view. Candidate rent does not automatically become underwriting rent; the user chooses an explicit, sourced scenario input.
