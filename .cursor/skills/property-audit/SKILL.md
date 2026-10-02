---
name: property-audit
description: Review Property Studio evidence, scenario consistency, image support and export readiness before a realtor uses a generated script.
---

From `tools/property-studio`, run `python -m property_studio audit RUN_ID`. Inspect blocking findings, source excerpts, photos and the workbook assumptions. The audit catches structural problems and unsupported numbers; it does not prove semantic truth.

Check exact unit, source dates, asking versus achieved prices, unresolved contradictions, assessment status, and matching images. Check all public wording, including hooks and captions. A plausible number without a supporting calculation is not acceptable. A rejected claim must not survive in the story.

Keep live, cached and synthetic results distinguishable. Do not claim a service is integrated merely because its adapter exists. Report implementation gaps from `HANDOVER.md`; never replace them with invented successful checks.
