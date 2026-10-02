"""Generate reviewed, team-scoped manifests without mutating the cluster.

Usage: python deploy/prepare.py --namespace team-N --pvc existing-claim > manifest.json
Create the property-studio-env Secret separately from the team's environment.
"""
import argparse
import base64
import gzip
import io
import json
import os
import re
import tarfile
from pathlib import Path
from urllib.parse import urlsplit


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--namespace',required=True)
    p.add_argument('--pvc',help='Existing application PVC for durable evidence')
    p.add_argument('--ephemeral',action='store_true',help='Explicitly accept evidence loss on pod replacement')
    args=p.parse_args()
    if not re.fullmatch(r'[a-z0-9](?:[-a-z0-9]*[a-z0-9])?',args.namespace): p.error('Invalid namespace')
    if not args.pvc and not args.ephemeral: p.error('Provide --pvc or explicitly accept --ephemeral')
    host=urlsplit(os.environ.get('INGRESS_URL','')).hostname
    if not host: p.error('Set the actual team INGRESS_URL')
    app=Path(__file__).resolve().parents[1]
    raw=io.BytesIO()
    with tarfile.open(fileobj=raw,mode='w') as tar:
        paths=[app/'main.py',app/'requirements.lock']+sorted((app/'property_studio').rglob('*'))
        for file in paths:
            if not file.is_file() or '__pycache__' in file.parts: continue
            data=file.read_bytes(); info=tarfile.TarInfo(str(file.relative_to(app)))
            info.size=len(data);info.mode=0o644;info.mtime=0
            tar.addfile(info,io.BytesIO(data))
    archive=gzip.compress(raw.getvalue(),mtime=0)
    if len(archive)*4//3>900_000: p.error('Code archive exceeds ConfigMap budget')
    name='property-studio'
    meta={'name':name,'namespace':args.namespace,'labels':{'app':name}}
    startup="""import pathlib, subprocess, tarfile
pathlib.Path('/app').mkdir(exist_ok=True)
with tarfile.open('/code/app.tar.gz') as archive:
    archive.extractall('/app', filter='data')
subprocess.run(['python','-m','pip','install','--no-cache-dir','-r','/app/requirements.lock'],check=True)
import os
os.chdir('/app')
os.execvp('python',['python','main.py'])
"""
    items=[{'apiVersion':'v1','kind':'ConfigMap','metadata':meta,'binaryData':{'app.tar.gz':base64.b64encode(archive).decode()}},
           {'apiVersion':'apps/v1','kind':'Deployment','metadata':meta,'spec':{
             'replicas':1,'strategy':{'type':'Recreate'},'selector':{'matchLabels':{'app':name}},
             'template':{'metadata':{'labels':{'app':name}},'spec':{'containers':[{
                 'name':name,'image':'python:3.12-slim','command':['python','-c',startup],
                 'ports':[{'containerPort':8080}],'envFrom':[{'secretRef':{'name':'property-studio-env'}}],
                 'env':[{'name':'HOST','value':'0.0.0.0'},{'name':'PROPERTY_ROOT_PATH','value':'/app'},
                        {'name':'PROPERTY_DATA_DIR','value':'/data'}],
                 'volumeMounts':[{'name':'code','mountPath':'/code','readOnly':True},{'name':'data','mountPath':'/data'}],
                 'readinessProbe':{'httpGet':{'path':'/health','port':8080},'initialDelaySeconds':10,'periodSeconds':10},
                 'startupProbe':{'httpGet':{'path':'/health','port':8080},'failureThreshold':60,'periodSeconds':10},
                 'resources':{'requests':{'cpu':'250m','memory':'512Mi'},'limits':{'cpu':'2','memory':'2Gi'}}}],
                 'volumes':[{'name':'code','configMap':{'name':name}}, {'name':'data',**({'persistentVolumeClaim':{'claimName':args.pvc}} if args.pvc else {'emptyDir':{}})}]}}}},
           {'apiVersion':'v1','kind':'Service','metadata':meta,'spec':{'selector':{'app':name},'ports':[{'port':80,'targetPort':8080}]}},
           {'apiVersion':'networking.k8s.io/v1','kind':'Ingress','metadata':{**meta,'annotations':{'nginx.ingress.kubernetes.io/rewrite-target':'/$2','nginx.ingress.kubernetes.io/use-regex':'true','nginx.ingress.kubernetes.io/proxy-body-size':'12m'}},
            'spec':{'ingressClassName':'nginx','rules':[{'host':host,'http':{'paths':[{'path':'/app(/|$)(.*)','pathType':'ImplementationSpecific',
                   'backend':{'service':{'name':name,'port':{'number':80}}}}]}}]}}]
    print(json.dumps({'apiVersion':'v1','kind':'List','items':items},indent=2))


if __name__=='__main__': main()
