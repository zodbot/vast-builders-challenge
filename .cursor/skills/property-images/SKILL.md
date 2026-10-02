---
name: property-images
description: Use NVIDIA Cosmos through Property Studio to describe authorized property photographs and assess visible features against its rubric.
---

From `tools/property-studio`, run `python -m property_studio images RUN_ID`. Photos must already belong to the run. Upload photographs through the app or provide authorized image URLs at intake. Read `property_studio/adapters.py` for the implemented image payload and `service.py` for the rubric.

Preserve actual `COSMOS3_REASON_URL`, model ID and authentication from the team environment. The starter documents disagree about authentication and hosts. Do not overwrite them with sample addresses. A models list or text smoke test is not photo inference; verify one real photograph first on the VM.

Keep description and analysis separate and retain media IDs. Review model observations against the actual images. Do not infer structural integrity, window direction, legal compliance or actual daylight from a photograph. Synthetic observations must remain labeled synthetic.
