import argparse
import json
from pathlib import Path
from .config import Settings
from .models import RunInput
from .service import Service


def main():
    p=argparse.ArgumentParser(description="Property Studio")
    sub=p.add_subparsers(dest="command",required=True)
    doctor=sub.add_parser("doctor"); doctor.add_argument("--live",action="store_true")
    a=sub.add_parser("analyze"); a.add_argument("--input",type=Path); a.add_argument("--demo",action="store_true")
    show=sub.add_parser("show"); show.add_argument("run_id")
    for name in ["resume","research","images","finance","script","export","video","audit"]:
        q=sub.add_parser(name); q.add_argument("run_id")
    args=p.parse_args(); s=Settings.load(); service=Service(s)
    try:
        if args.command=="doctor":
            result=s.capabilities()
            if args.live:
                from .adapters import request_json,ProviderError
                if s.cosmos_url:
                    try:
                        headers={"Authorization":f"Bearer {s.gpu_token}"} if s.gpu_token else {}
                        result["cosmos_models"]=request_json("GET",s.cosmos_url+"/v1/models",headers=headers)
                        result["photo_inference"]="Not tested by doctor; run images with an authorized photograph"
                    except ProviderError as e: result["cosmos_error"]=str(e)
            print(json.dumps(result,indent=2)); return
        if args.command=="analyze":
            if args.demo: request=RunInput(mode="synthetic")
            elif args.input: request=RunInput.model_validate_json(args.input.read_text())
            else: p.error("Pass --demo or --input request.json")
            run=service.create(request); service.execute(run.id)
        else:
            run=service.store.get(args.run_id)
            if args.command not in {"show","audit"}:
                stage={"resume":"intake","images":"vision","script":"story"}.get(args.command,args.command)
                service.execute(run.id,stage)
            if args.command=="audit":
                from .story import audit
                print(json.dumps(audit(run),indent=2)); return
        run=service.store.get(run.id)
        print(json.dumps({"id":run.id,"state":run.state,"address":run.property.address,"stages":run.stages,"artifacts":run.artifacts,"data_dir":str(service.store.folder(run.id))},indent=2))
    finally: service.worker.shutdown(wait=True)


if __name__=="__main__": main()
