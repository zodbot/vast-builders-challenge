"""Isolate third-party listing retrieval so the parent can bound its wall time."""
import contextlib
import json
import sys
from homeharvest import scrape_property

if __name__=='__main__':
    args=json.load(sys.stdin)
    with contextlib.redirect_stdout(sys.stderr):
        rows=scrape_property(**args,parallel=False)
    print(json.dumps([p.model_dump(mode='json') for p in rows]))
