---
name: property-research
description: Research a Property Studio run using supplied documents, public sources and the configured search provider, including HOA and historical questions.
---

From `tools/property-studio`, run `python -m property_studio research RUN_ID`. Inspect the run first with `show RUN_ID`; confirm its exact property and association. Upload supporting PDFs or text through the app. Search requires `BRAVE_SEARCH_API_KEY`; extraction requires the configured W&B model.

Extracted claims remain pending review. Check exact source excerpts before confirming them. Distinguish proposed assessments from approved, outstanding and paid obligations; missing HOA documents are unanswered questions, not a clean bill of health. Preserve allegations versus findings and event dates versus retrieval times.

The current adapter performs directed search, not comprehensive official-record coverage. State gaps and identify the next document that could change the conclusion. Never infer a seller's finances or motivation from staging or an old recorded mortgage.
