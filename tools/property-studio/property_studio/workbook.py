import json
import os
from pathlib import Path
import subprocess
from .adapters import ProviderError


def export_workbook(run,folder,settings,verify=False):
    spec={"address":run.property.address,"mode":run.request.mode,"version":run.version,
          "finance":run.finance,"sources":[s.model_dump(mode="json") for s in run.sources],
          "comps":[c.model_dump(mode="json") for c in run.comparables],
          "questions":run.questions,"claims":[c.model_dump(mode="json") for c in run.claims],
          "assumptions":run.request.assumptions.model_dump(mode="json")}
    path=folder/"workbook-spec.json"
    path.write_text(json.dumps(spec,indent=2))
    cmd=[settings.node_bin,str(Path(__file__).parent/"exports"/"workbook.mjs"),str(path),str(folder/"analysis.xlsx")]
    if verify: cmd.append("--verify")
    env={**os.environ,"PROPERTY_ARTIFACT_MODULE":settings.artifact_module}
    try:
        result=subprocess.run(cmd,env=env,timeout=180,capture_output=True,text=True)
    except FileNotFoundError:
        from .portable_workbook import export_portable
        export_portable(spec,folder/"analysis.xlsx")
        return
    except (OSError,subprocess.TimeoutExpired):
        raise ProviderError("Workbook renderer could not finish; JSON calculations are saved.") from None
    if result.returncode:
        if 'ERR_MODULE_NOT_FOUND' in result.stderr or 'Cannot find package' in result.stderr:
            from .portable_workbook import export_portable
            export_portable(spec,folder/"analysis.xlsx")
            return
        # Detailed renderer output is kept locally, never credentials or remote payloads.
        (folder/"workbook-error.txt").write_text(result.stderr[-6000:])
        raise ProviderError("Workbook renderer failed; inspect workbook-error.txt locally")
