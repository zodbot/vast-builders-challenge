# Property Studio

A local working application for evidence-led property research, Cosmos photo analysis, financial scenarios and video scripts. The workshop integration still needs live VM verification. Start with the synthetic demo; it never claims to have performed live research.

## Run

From this directory, using Python 3.12 or newer:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python main.py
```

Open `http://127.0.0.1:8080`. Select **Explore a synthetic demo**. This creates invented property data, three labeled illustrations, a conflicting-rental-price example, a draft script, and a financial workbook.

The Python environment already installed during local development is at the repository root. From this directory you can instead run `../../.venv/bin/python main.py`.

The application reads exported environment variables; it does not automatically source `.env` files. See `.env.example`. Never commit actual credentials.

## Commands

```sh
python -m property_studio doctor
python -m property_studio doctor --live
python -m property_studio analyze --demo
python -m property_studio analyze --input request.json
python -m property_studio show RUN_ID
python -m property_studio research RUN_ID
python -m property_studio images RUN_ID
python -m property_studio finance RUN_ID
python -m property_studio script RUN_ID
python -m property_studio audit RUN_ID
python -m property_studio export RUN_ID
python -m pytest -q
```

Stage commands run the chosen stage and its downstream dependencies. `resume` skips completed stages until the first incomplete one, then refreshes downstream results. Use the web app for financial revisions; it creates a scenario version and invalidates stale artifacts.

Example live request (replace the address and sources):

```json
{
  "address": "EXACT STREET ADDRESS, CITY, STATE",
  "unit": "EXACT UNIT",
  "confirm_identity": true,
  "authorize_images": true,
  "use_homeharvest": true,
  "source_urls": [],
  "image_urls": [],
  "assumptions": {
    "purchase_price": null,
    "annual_rate": null,
    "rent_monthly": null
  }
}
```

Only confirm identity and authorize images when those statements are true. URL-only intake deliberately asks for an exact address; it does not silently select a unit. Unsupported sites can use manual documents and photographs. HomeHarvest runs through its own Realtor.com adapter; arbitrary listing URLs are not passed to it.

## Architecture

- `models.py`: typed property, evidence, media, scenario and story records.
- `adapters.py`: Cosmos, W&B, public fetching, Brave search and HomeHarvest.
- `service.py`: single-worker stages and resumable workflow.
- `research.py`: document questions, extraction and comparable reconciliation.
- `finance.py`: shared Decimal expression graph and Excel formula generation.
- `story.py`: draft generation, citation and number checks.
- `storage.py`: atomic local manifests, history and optional VAST S3 backup.
- `workbook.py`, `exports/`: artifact-tool workbook generation and verification.
- `portable_workbook.py`: fallback when artifact-tool is unavailable on a VM; writes the same formulas with initial Python-calculated caches.
- `api.py`, `ui/`: authenticated API and a small responsive interface.

The workbook recalculates ordinary financial inputs in Excel. Loan term, holding duration and assessment installment duration currently require regeneration in the app. No tax benefits, PMI cancellation or lender-specific underwriting is inferred.

## Workshop status

Implemented adapters are not evidence of live service access. Cosmos image payloads, W&B endpoint/model, public-source coverage, VAST credentials and Kubernetes deployment must be verified on the VM. `doctor --live` checks Cosmos model discovery, not image inference.

The current research implementation uses supplied sources, directed web search and reviewable extraction. It does not yet implement dedicated assessor/court/permit database connectors, automatic parcel resolution, automated HOA document review completion, or reliable nationwide history coverage. Comp candidates require review and do not automatically determine a supported market rent.

VSS media ingestion, Embed/VastDB writes, W&B Weave tracing and video rendering are not implemented. Local stage timing records are available. Follow `HANDOVER.md` for the exact next steps.

Use a durable PVC for the deployed application. The optional S3 adapter copies run artifacts but does not currently restore a lost local index automatically. The app is designed for one team and one worker, not public multi-tenant use.

## Skills

Canonical property skills live in the repository's `.cursor/skills/property-*` directories. Each skill calls the same CLI functions as the UI. In Codex, explicitly ask it to read the relevant `SKILL.md`; automatic discovery of Cursor skills is not assumed. Optional agent-specific registration can be added on the VM.

## Deployment

The generator only writes manifests; it does not apply them:

```sh
python deploy/prepare.py --namespace YOUR_TEAM --pvc YOUR_EXISTING_APPLICATION_PVC > deploy/generated.json
```

It reads the actual `INGRESS_URL`, creates a small code ConfigMap and reuses `/app`. It expects a separately provisioned `property-studio-env` Secret. Review the generated manifest and use the handover checklist before applying it. Never redeploy the shared VSS stack or write application artifacts to watched ingest buckets.
