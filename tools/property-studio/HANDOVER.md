# Property Studio VM handover

The local application is built and ready to push to the repository, pull on the workshop VM, and continue with Codex. No remote push or Kubernetes deployment was performed in the local session. No VM credentials were read or copied.

## Prompt to give Codex on the VM

> Read tools/property-studio/HANDOVER.md and README.md, then inspect the implementation and relevant .cursor/skills/property-* skills. Continue the property-analysis hackathon project from this code. First run the tests and synthetic demo, then verify the actual team environment and one real Cosmos photo inference. Use the supplied W&B inference service for research and script generation. Preserve configured endpoints and credentials, keep all integrations honest about live versus synthetic results, and follow the starter's deployment skill to deploy only our app at the team ingress /app. Resolve the documented VSS ingestion and judging-fit question before uploading any new property video or changing shared infrastructure. Complete a real property run and report remaining gaps. Do not publish videos or send messages.

## What is implemented

- FastAPI application with responsive UI, local CLI and a single background worker.
- Exact-property confirmation, manual source/photo intake, HomeHarvest adapter and candidate comp discovery.
- Public URL fetching with private-address rejection, redirect checks and address-pinned connections.
- Optional Brave web search, supplied PDF/text extraction, HOA document questions and W&B evidence extraction.
- Cosmos image requests, separate descriptions and rubric observations, source IDs and reviewable claims.
- Comparable price-type distinctions, stale/removed listing handling, conflict records and explicit differences.
- Shared Decimal calculation graph that also generates Excel formulas.
- Mortgage amortization, NOI, cash flow, assessments, rent versus buy, and price/rent sensitivities.
- An 11-sheet workbook, JSON dossier and script/storyboard Markdown.
- W&B-generated script adapter, a labeled template fallback and structural claim/number checks.
- Editable scenarios, stale-artifact invalidation, versioned manifests and interrupted-run recovery on persistent local storage.
- Optional VAST S3 backup, authenticated application access and a Kubernetes manifest generator.
- Seven reusable property skills in .cursor/skills/property-*.

The UI is a working local application. The synthetic demo uses invented property facts and labeled illustrations, never fabricated live findings.

## What was tested locally

- Unit and integration tests covering finance, zero-rate loans, all-cash purchases, missing rent, assessment accounting, claim/source validation, price conflicts, exact-unit matching, URL restrictions, scenario invalidation, authentication and restart state.
- Mocked Cosmos requests including the actual image payload shape, bearer header and model discovery; mocked W&B model/project configuration. These are contract tests, not proof the workshop endpoints accept the requests.
- The synthetic workflow through photos, assumptions, script and workbook export.
- Workbook calculation parity, input-change recalculation through artifact-tool, and sheet previews. Native Microsoft Excel recalculation was not tested.
- Portable workbook fallback when the Node/artifact runtime is unavailable; formulas and initial caches checked by reopening the file.
- Browser inspection of the investigation and script UI, including the synthetic label, source links and artifact links.
- Manifest generation using a test hostname. No manifests were applied.

Run the test suite again after pulling; the repository is the source of truth for the latest count and results.

## Start on the VM

Run from the repository root after pulling the branch containing these changes:

```sh
cd tools/property-studio
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pytest -q
.venv/bin/python -m property_studio doctor
.venv/bin/python -m property_studio analyze --demo
```

Python 3.12 or newer is required. If the VM default Python is older, use its available Python 3.12 executable rather than modifying the operating system Python. The local developer .venv is ignored and must not be copied from macOS to Linux.

For an initial VM-local preview:

```sh
.venv/bin/python main.py
```

This binds to 127.0.0.1:8080. The workshop deliverable remains the Kubernetes application at the team's existing host under /app.

## Configure services without copying secrets into Git

The app reads exported environment variables. It does not automatically read .env. Use the actual team configuration under /config, or already-exported workshop environment. Do not search the repository's team-configs directory or print credential values. Configuration filenames can be team-prefixed; inspect the available team files rather than inventing a path.

| Integration | Variables | Required verification |
|---|---|---|
| Cosmos | COSMOS3_REASON_URL, COSMOS3_REASON_MODEL if known, GPU_BEARER_TOKEN if required | One authorized photo, not just models or text inference |
| W&B inference | WANDB_API_KEY, WANDB_TEAM, WANDB_PROJECT, PROPERTY_LLM_MODEL | Confirm actual model and compatible base URL |
| W&B base URL | PROPERTY_LLM_BASE_URL | Defaults to the documented workshop-era URL; verify actual account endpoint |
| Search | BRAVE_SEARCH_API_KEY | A successful bounded property query; otherwise use supplied URLs/docs |
| VAST application storage | PROPERTY_S3_BUCKET, PROPERTY_S3_PREFIX, S3_ENDPOINT, ACCESS_KEY, SECRET_KEY | Approved bucket separate from watched ingest buckets |
| App access | PROPERTY_APP_TOKEN | Set before exposing beyond localhost |
| Persistent evidence | PROPERTY_DATA_DIR or a mounted PVC | Writable durable volume and restart test |
| Workbook runtime | Optional PROPERTY_NODE_BIN and PROPERTY_ARTIFACT_MODULE | Primary renderer if available; portable fallback otherwise |

The spreadsheet renderer prefers the bundled artifact-tool runtime where available. It is not copied into this repository. The pure-Python fallback makes the VM application usable without that runtime: it writes the same formulas and initial caches from the shared graph and requests recalculation on opening in Excel. Distinguish initial cache checks from native spreadsheet-engine verification.

## First live verification sequence

1. Run doctor and inspect configured versus missing capabilities. Run doctor --live to check Cosmos model discovery. Do not report photo inference complete yet.
2. Start a run with the chosen exact address and unit. Do not reuse the synthetic property's identity. If a listing URL is the only input, the current app asks for the exact address rather than automatically trusting a scraped unit match.
3. Upload one authorized JPEG or PNG, or supply its authorized URL. Run the images stage. The current adapter sends OpenAI-style image_url content with a JPEG data URL to /v1/chat/completions. Confirm the real service accepts it and returns schema-valid image observations. Adapt to the documented server contract if necessary; do not silently substitute text-only inference.
4. Compare the returned description with the actual photo. It must not invent rooms, directions, hidden damage or structural conclusions. Confirm supported claims in the app.
5. Verify W&B inference with the actual model ID. Then test one document extraction and a generated script. Without credentials the app returns a template draft and a partial stage, not a fake model response.
6. Test HomeHarvest for the selected unit and a few comps. Retrieval is isolated in a subprocess with a 60-second budget per call. If the upstream source blocks the VM or cannot resolve the unit, use manual sources and record the limitation.
7. Provide sourced or explicit scenario inputs for rate, taxes, insurance, HOA, rent, maintenance and capital budget. A zero must mean a deliberate zero. Historical seller taxes are not automatically buyer taxes.
8. Review the workbook and draft script. Change one assumption and confirm the numbers and scenario version update while photos remain attached.
9. Confirm the chosen VAST application bucket is safe, test backup and inspect the saved objects. Backup does not currently provide automatic restoration into a new local data directory.

## Starter inconsistencies to resolve

The architecture reference says GPU authentication is unnecessary; the GPU skills use a bearer token and a hardcoded host. The app preserves configured endpoints and uses the token when supplied. Test the actual team service instead of copying sample hosts.

The architecture reference says the challenge uses pre-ingested video and re-ingestion of existing segments. An upload skill also exists. The property app does not yet upload new property video, invoke the segmenter, write VastDB rows or modify DataEngine functions.

Confirm with organizers whether Cosmos photo analysis plus W&B, VAST storage and the deployed app meets judging expectations. If the indexed VSS video loop is mandatory, add a relevant authorized property-video path after its support is confirmed. Never present unrelated archive footage as property or neighborhood evidence.

## Deployment

Read .cursor/skills/deployment/deploy-app-no-registry/SKILL.md. Preserve the shared VSS system. The app uses a small deterministic code archive in a ConfigMap, python:3.12-slim, the team namespace and the actual ingress host at /app. The archive generator verifies its size and includes nested Python modules correctly.

Create a property-studio-env Secret from the relevant team environment without writing secret values into tracked files. Include PROPERTY_APP_TOKEN. Use an existing approved application PVC for /data. Then generate and review the manifest:

```sh
.venv/bin/python deploy/prepare.py --namespace YOUR_TEAM --pvc YOUR_APPLICATION_PVC > deploy/generated.json
```

Replace the identifiers with values verified from the team environment. The generator requires the actual INGRESS_URL. It does not create a Secret or PVC. Use --ephemeral only for a deliberate temporary demo; evidence disappears on pod replacement and S3 restore is not automatic.

After review, apply the generated manifest in the authorized team namespace. Verify the pod can install pinned dependencies, reach the APIs, write the data volume, and serve health, static assets, authenticated API routes and downloads through /app. The initial runtime installs dependencies, so startup has a generous probe window.

Recreate the ConfigMap and restart the application deployment after code changes. A running pod will not automatically reload changed Python files.

## Known implementation limits and next work

These are genuine remaining work, not completed features from the architecture plan:

- Live workshop services and deployment have not been verified from this laptop session.
- Official assessor, recorder, court and permit database adapters, automatic parcel identity and nationwide coverage are not built. Current research is directed search plus supplied sources and reviewable extraction.
- HOA questions are a review checklist; there is no complete association financial parser or automatic clean/unsafe verdict. Review document status and unit allocations manually before changing scenario inputs.
- Comparable candidates are not a valuation model. Qualitative differences and provenance are shown, but selection, achieved-rent verification and adjustments require review. No unsupported premium is inserted.
- The base visual rubric is static. Property-specific rubric generation and semantic retrieval over images are next steps.
- W&B inference is wired; Weave tracing, usage/cost accounting and automatic model discovery for W&B are not implemented. Local stage timing is recorded.
- VSS retrieval integration, new-video ingestion, Embed/VastDB writes, video rendering, voice synthesis and publishing are not implemented.
- The script audit checks reference integrity and numeric consistency in scenes, not all semantic assertions. Review hooks, captions and narration before public use. All scripts remain drafts.
- Loan term, holding period and assessment duration are structural workbook inputs: change them in the app and re-export. Other ordinary financial inputs recalculate in the workbook. No income-tax effects, automatic PMI termination or lender-specific rules are modeled.
- Sensitivities are hypothetical purchase-price/rent cases; the tax budget scales with price in those cases. They are not market forecasts. More rate, holding-period and HOA sensitivities can be added to the shared graph.
- S3 currently backs up artifacts. Durable local storage or a PVC is required for reliable resume; automatic S3 restoration is not implemented.
- This is one team's single-worker app, not a hardened public multi-tenant service. Document parsing is bounded by input size and page count; stronger process isolation, comprehensive fetch budgets and tenant controls are future production work.

## Files to push

Include tools/property-studio, .cursor/skills/property-*, docs/plans/property-analysis-architecture.md and the .gitignore change. The original starter content is preserved.

Do not add .property-data, .venv, node_modules, generated deployment manifests, documents, photographs, real configuration or credentials. Those runtime locations are ignored. No commit or push was made by the local assistant.

For Codex skill use, explicitly reference the canonical .cursor/skills/property-* files. Automatic discovery of Cursor skills by Codex is not assumed; agent-specific registration can be added inside the VM if desired.
