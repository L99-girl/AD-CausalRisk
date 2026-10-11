"""Start the dedicated Python-owner research service from its authorized workspace.

No scientific source or estimator is copied into the course repo. Missing runtime
is an explicit startup error; the launcher never substitutes the demo scorer.
"""
import argparse
import importlib.util
from pathlib import Path
import sys

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--research-workspace',required=True,type=Path)
    parser.add_argument('--port',type=int,default=8092)
    args=parser.parse_args()
    scripts=(args.research_workspace/'scripts').resolve()
    required=['research_runtime_server.py','research_runtime_v8.py']
    if not scripts.is_dir() or any(not (scripts/name).is_file() for name in required):
        raise SystemExit('Authorized research workspace/runtime is unavailable; course service is separate')
    sys.path.insert(0,str(scripts))
    facade=Path(__file__).resolve().parent/'research_gateway/server.py'
    spec=importlib.util.spec_from_file_location('adcausalrisk_shared_research_facade',facade)
    if spec is None or spec.loader is None:raise SystemExit('Research HTTP source is unavailable')
    service=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    if service.HTTP_CONTRACT!='adni-v8-http-v1':raise SystemExit('Research HTTP contract differs')
    sys.argv=[sys.argv[0],'--port',str(args.port)]
    service.main()

if __name__=='__main__':main()
