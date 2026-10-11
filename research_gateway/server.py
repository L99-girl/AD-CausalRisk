"""Authenticated loopback HTTP facade for the unchanged, hash-bound V8 runtime.

Initial application acceptance is restricted to declared synthetic source graphs.
This service neither reads patient tables nor fits/publishes estimators.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
import re
import secrets
import threading

from research_runtime_v8 import RuntimeModels,RuntimeErrorCode,ROOT,CONTRACT,MODEL_FAMILY,sha

HTTP_CONTRACT='adni-v8-http-v1'
PREFIX='/api/research-runtime/v1'
MAX_BODY=256*1024

class HttpFailure(Exception):
    def __init__(self,status,code):self.status=status;self.code=code

class ResearchState:
    def __init__(self,models,token,capacity=64):
        if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{24,128}',token):
            raise ValueError('Provide a dedicated 24-128 character local access token')
        self.models=models;self.token=token;self.capacity=capacity;self.cache={};self.lock=threading.RLock()
        self.manifest_sha=sha(models.folder/'Runtime_Manifest.json')

    def verify_artifacts(self):
        m=self.models.manifest
        try:
            if sha(self.models.folder/'Runtime_Manifest.json')!=self.manifest_sha:raise HttpFailure(503,'MODEL_RUNTIME_CHANGED')
            for row in m['models'].values():
                if sha(self.models.folder/row['file'])!=row['sha256']:raise HttpFailure(503,'MODEL_RUNTIME_CHANGED')
            for name,digest in m['runtime_source_sha256'].items():
                if sha(ROOT/name)!=digest:raise HttpFailure(503,'MODEL_RUNTIME_CHANGED')
        except OSError:raise HttpFailure(503,'MODEL_RUNTIME_UNAVAILABLE') from None

    def status(self):
        self.verify_artifacts()
        return {'httpContractVersion':HTTP_CONTRACT,'contractVersion':CONTRACT,'modelVersion':MODEL_FAMILY,
                'ready':True,'scope':'LOCAL_RESEARCH_ONLY','inputMode':'SYNTHETIC_TEST',
                'variants':list(self.models.models),'clinicalUseEstablished':False,'eligibilityVerified':False,
                'persistentRequestCache':False,'runtimeManifestSha256':self.manifest_sha}

    def predict(self,payload):
        required={'httpContractVersion','requestId','inputMode','runtimeRequest'}
        if not isinstance(payload,dict) or set(payload)!=required:raise HttpFailure(400,'ENVELOPE_FIELDS')
        if payload['httpContractVersion']!=HTTP_CONTRACT:raise HttpFailure(409,'HTTP_CONTRACT_MISMATCH')
        if payload['inputMode']!='SYNTHETIC_TEST':raise HttpFailure(403,'INPUT_MODE_NOT_ENABLED')
        request_id=payload['requestId']
        if not isinstance(request_id,str) or not re.fullmatch(r'research-run-[A-Za-z0-9][A-Za-z0-9-]{0,47}',request_id):
            raise HttpFailure(400,'REQUEST_ID')
        request=payload['runtimeRequest']
        if not isinstance(request,dict) or not isinstance(request.get('caseCode'),str) or not request['caseCode'].startswith('LOCAL-SYNTHETIC-'):
            raise HttpFailure(403,'SYNTHETIC_CASE_ALIAS_REQUIRED')
        graph=request.get('graph')
        if not isinstance(graph,dict) or not isinstance(graph.get('nodes'),list):raise HttpFailure(400,'GRAPH_SCHEMA')
        for node in graph['nodes']:
            if not isinstance(node,dict) or not isinstance(node.get('source_visit'),str) or not node['source_visit'].startswith('DEMO-'):
                raise HttpFailure(403,'SYNTHETIC_SOURCE_REQUIRED')
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        with self.lock:
            # Changed on-disk model/code cannot be concealed by cached replies.
            self.verify_artifacts()
            if request_id in self.cache:
                old,response=self.cache[request_id]
                if old!=digest:raise HttpFailure(409,'REQUEST_ID_CONFLICT')
                return copy.deepcopy(response)
            if len(self.cache)>=self.capacity:raise HttpFailure(503,'REQUEST_CAPACITY_REACHED')
            try:result=self.models.predict(request)
            except RuntimeErrorCode as error:
                status=409 if error.code=='REQUEST_VERSION' else 400
                raise HttpFailure(status,error.code) from None
            except (KeyError,TypeError,ValueError,OverflowError):raise HttpFailure(400,'SOURCE_SCHEMA_INVALID') from None
            response={'httpContractVersion':HTTP_CONTRACT,'requestId':request_id,'status':'COMPLETED',
                      'inputMode':'SYNTHETIC_TEST','inputDeclarationIndependentlyVerified':False,
                      'eligibilityVerified':False,'result':result}
            self.cache[request_id]=(digest,response)
            return copy.deepcopy(response)

class ResearchServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,state):
        if address[0]!='127.0.0.1':raise ValueError('Only IPv4 loopback is supported')
        self.state=state;super().__init__(address,ResearchHandler)

class ResearchHandler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def setup(self):super().setup();self.connection.settimeout(10)
    def send_json(self,status,payload):
        body=json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
    def authorize(self):
        if self.headers.get('Origin') is not None:raise HttpFailure(403,'BROWSER_DIRECT_CALL_DISABLED')
        supplied=self.headers.get('Authorization','')
        if not secrets.compare_digest(supplied,'Bearer '+self.server.state.token):raise HttpFailure(401,'LOCAL_ACCESS_REQUIRED')
    def error(self,e):self.send_json(e.status,{'httpContractVersion':HTTP_CONTRACT,'status':'REJECTED','code':e.code})
    def do_GET(self):
        try:
            self.authorize()
            if self.path!=PREFIX+'/status':raise HttpFailure(404,'ROUTE_NOT_FOUND')
            self.send_json(200,self.server.state.status())
        except HttpFailure as e:self.error(e)
    def do_POST(self):
        try:
            self.authorize()
            if self.path!=PREFIX+'/predictions':raise HttpFailure(404,'ROUTE_NOT_FOUND')
            if self.headers.get_content_type()!='application/json':raise HttpFailure(415,'CONTENT_TYPE')
            if self.headers.get('Transfer-Encoding'):raise HttpFailure(400,'CONTENT_LENGTH_REQUIRED')
            size=self.headers.get('Content-Length','')
            if not size.isdecimal() or int(size)<1:raise HttpFailure(400,'CONTENT_LENGTH_REQUIRED')
            if int(size)>MAX_BODY:raise HttpFailure(413,'PAYLOAD_TOO_LARGE')
            def unique(pairs):
                result={}
                for key,value in pairs:
                    if key in result:raise ValueError('duplicate JSON key')
                    result[key]=value
                return result
            def nonfinite(value):raise ValueError('nonfinite JSON')
            payload=json.loads(self.rfile.read(int(size)).decode('utf-8'),object_pairs_hook=unique,parse_constant=nonfinite)
            self.send_json(200,self.server.state.predict(payload))
        except HttpFailure as e:self.error(e)
        except (UnicodeError,ValueError,RecursionError):self.error(HttpFailure(400,'JSON_INVALID'))
        except (TimeoutError,OSError):self.error(HttpFailure(408,'REQUEST_TIMEOUT'))
    def do_OPTIONS(self):self.error(HttpFailure(405,'BROWSER_DIRECT_CALL_DISABLED'))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8092);args=parser.parse_args()
    token=os.environ.get('ADNI_V8_RUNTIME_TOKEN','')
    if not token:raise SystemExit('Set ADNI_V8_RUNTIME_TOKEN for this dedicated local service')
    state=ResearchState(RuntimeModels(),token)
    with ResearchServer(('127.0.0.1',args.port),state) as server:
        print(json.dumps({'status':'ready','url':f'http://127.0.0.1:{server.server_port}',
                          'httpContractVersion':HTTP_CONTRACT,'inputMode':'SYNTHETIC_TEST'}),flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt:pass

if __name__=='__main__':main()
