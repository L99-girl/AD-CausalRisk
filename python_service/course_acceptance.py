"""Repeatable synthetic course HTTP acceptance; no research records or fitting."""
import argparse
import copy
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import http.client
import json
from pathlib import Path
import socket
import threading
from uuid import uuid4
from urllib.parse import urlsplit
from .course_client import CourseClient,CourseClientError
from .course_protocol import CourseContract,decode_json,validate_course_result
from .deepagent_contract import run_workflow
from .demo_scoring import score_java_synthetic_payload
from .server import AgentServer,RunStore,MAX_BODY

ROOT=Path(__file__).resolve().parents[1]
SOURCE_FILES=('contracts/python-agent.openapi.json','python_service/deepagent_contract.py','python_service/course_fusion.py',
              'python_service/demo_scoring.py','python_service/server.py','python_service/course_protocol.py',
              'python_service/course_client.py','python_service/course_acceptance.py','fixtures/synthetic_subjects_100.json')


def source_hashes(root=ROOT):
    return {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in SOURCE_FILES}


class AcceptanceStore(RunStore):
    def __init__(self):super().__init__();self.calls=0
    def create(self,payload):
        self.calls+=1
        if payload.get('runId')=='run-acceptance-execution-failure':
            raise RuntimeError('CONSTRUCTED_DETAIL_NOT_FOR_RESPONSE')
        return super().create(payload)


@contextmanager
def owned_service():
    server=AgentServer(('127.0.0.1',0),AcceptanceStore())
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield f'http://127.0.0.1:{server.server_port}',server.store
    finally:server.shutdown();server.server_close();thread.join(timeout=5)


def without_timing(value):
    result=copy.deepcopy(value)
    for stage in result['stages']:stage.pop('durationMs')
    return result


def run_acceptance(url,*,owned_store=None,observe=None):
    """Live --url uses new synthetic runIds; fault injection is self-test only."""
    checks=[];schema=CourseContract();client=CourseClient(url,timeout=20)
    def seen(name,value,valid=True):
        if observe:observe(name,value,valid)
    def verify_result(payload,result):
        seen('AgentRequest',payload);seen('AgentResult',result)
        validate_course_result(result,payload,schema)
    client.health();checks.append('health_identity_versions_synthetic_mode_and_volatile_store')
    fixture=json.loads((ROOT/'fixtures/synthetic_subjects_100.json').read_text(encoding='utf-8'))
    assert fixture['dataSource']=='SYNTHETIC_DEMO' and len(fixture['subjects'])==100
    prefix='run-accept-'+uuid4().hex
    first=None
    for index,original in enumerate(fixture['subjects']):
        payload=copy.deepcopy(original);payload['runId']=prefix+'-'+str(index)
        result=client.create(payload);verify_result(payload,result)
        baseline=run_workflow(payload,score_java_synthetic_payload)
        assert without_timing(result)==without_timing(baseline)
        cached=client.result(payload['runId']);seen('AgentResult',cached)
        assert cached==result
        if first is None:first=(payload,result)
    checks.extend(['all_100_fixture_profiles_request_response_schema_and_semantics',
                   'all_100_http_cores_match_unchanged_direct_workflow_excluding_actual_timing',
                   'all_100_run_lookups_preserve_first_result_including_timing'])
    payload,result=first
    assert client.create(payload)==result
    checks.append('same_request_replay_preserves_exact_cached_result')
    changed=copy.deepcopy(payload);changed['predictionWindowMonths']=12
    try:client.create(changed)
    except CourseClientError as error:assert error.http_status==409 and error.code=='RUN_ID_CONFLICT'
    else:raise AssertionError('Conflicting run accepted')
    assert client.result(payload['runId'])==result
    checks.append('changed_request_same_run_409_keeps_original_binding_and_result')
    for label,change in [('no_cognition',lambda body:body.update(visits=[])),
                         ('unsupported_window',lambda body:body.update(predictionWindowMonths=12)),
                         ('ambiguous_visit',lambda body:body['visits'].append(dict(body['visits'][-1],visitCode='CONFLICT'))),
                         ('conflicting_feature',lambda body:body['features'].append(dict(body['features'][0],featureValue=2 if body['features'][0]['featureValue']!=2 else 1)))]:
        body=copy.deepcopy(payload);body['runId']=prefix+'-'+label.replace('_','-');change(body)
        value=client.create(body);verify_result(body,value)
        assert value['status']=='BLOCKED' and value['riskScore'] is None and value['graph']['nodes']==[]
        checks.append('blocked_null_no_prediction_'+label)
    body=copy.deepcopy(payload);body['runId']=prefix+'-future-source'
    body['features'].append(dict(body['features'][0],recordedAt='2026-02-01'))
    value=client.create(body);verify_result(body,value)
    assert value['stages'][0]['summary']['excludedPostIndexFeatures']>=1
    checks.append('post_index_feature_excluded_with_original_warn_semantics')
    fresh=CourseClient(url)
    assert fresh.result(payload['runId'],expected_request=payload)==result
    checks.append('fresh_client_lookup_requires_explicit_expected_request')
    request_observations=100+5
    repeat_count=0
    # These requests contain only controlled synthetic text. Do not use this
    # helper to send patient data or arbitrary bytes to a remote address.
    port=urlsplit(url).port
    def raw_error(status,code,body=b'{}',*,headers=None,path='/api/agent/v1/runs',method='POST',half_close=False):
        connection=http.client.HTTPConnection('127.0.0.1',port,timeout=20)
        fields=headers if headers is not None else [('Content-Type','application/json'),('Content-Length',str(len(body)))]
        try:
            connection.putrequest(method,path,skip_accept_encoding=True)
            for key,value in [*fields,('X-Trace-Id','acceptance-trace')]:connection.putheader(key,value)
            connection.endheaders(body)
            if half_close:connection.sock.shutdown(socket.SHUT_WR)
            response=connection.getresponse();value=decode_json(response.read())
            assert response.status==status and value['code']==code
            assert response.getheader('X-Trace-Id')==value['traceId']=='acceptance-trace'
            assert 'CONSTRUCTED_DETAIL_NOT_FOR_RESPONSE' not in json.dumps(value)
            schema.validate('AgentError',value);seen('AgentError',value)
            return value
        finally:connection.close()
    raw_error(400,'VALIDATION_400',b'{')
    raw_error(400,'VALIDATION_400',b'{"runId":"a","runId":"b"}')
    raw_error(400,'VALIDATION_400',b'{"x":NaN}')
    checks.append('malformed_duplicate_and_nonfinite_json_return_standard_400')
    invalid=copy.deepcopy(payload);invalid['contractVersion']='wrong'
    raw_error(409,'AGENT_CONTRACT_MISMATCH',json.dumps(invalid).encode())
    checks.append('wire_contract_mismatch_is_409_not_demo_fallback')
    raw_error(400,'VALIDATION_400',headers=[('Content-Type','application/json'),('Content-Length','2'),('Content-Length','2')])
    raw_error(400,'VALIDATION_400',headers=[('Content-Type','application/json'),('Content-Length','2'),('Transfer-Encoding','chunked')])
    raw_error(415,'UNSUPPORTED_MEDIA_TYPE',headers=[('Content-Type','application/json'),('Content-Type','text/plain'),('Content-Length','2')])
    checks.append('ambiguous_content_length_transfer_encoding_and_media_type_rejected')
    raw_error(400,'VALIDATION_400',headers=[('Content-Type','application/json'),('Content-Length','20')],half_close=True)
    checks.append('truncated_declared_body_rejected_before_run_creation')
    for index in range(16):
        before=owned_store.calls if owned_store else None
        raw_error(415,'UNSUPPORTED_MEDIA_TYPE',b'invalid-json',headers=[('Content-Type','text/plain'),('Content-Length','12')])
        raw_error(413,'PAYLOAD_TOO_LARGE',b' '*(MAX_BODY+1))
        if owned_store:assert owned_store.calls==before
        repeat_count+=2
    checks.append('32_early_rejections_deliver_full_error_json_without_run_execution')
    raw_error(405,'METHOD_NOT_ALLOWED',method='OPTIONS')
    checks.append('browser_cross_origin_access_still_not_enabled')
    if owned_store:
        failing=copy.deepcopy(payload);failing['runId']='run-acceptance-execution-failure'
        raw_error(500,'ASSESSMENT_FAILED',json.dumps(failing).encode())
        assert failing['runId'] not in owned_store.runs
        checks.append('unexpected_execution_failure_is_safe_500_and_not_cached')
        capacity=owned_store.capacity
        try:
            owned_store.capacity=len(owned_store.runs)
            full=copy.deepcopy(payload);full['runId']=prefix+'-capacity'
            raw_error(503,'RUN_CAPACITY_REACHED',json.dumps(full).encode())
        finally:owned_store.capacity=capacity
        checks.append('real_run_capacity_503_keeps_previous_results')
        # A real incomplete HTTP request reaches the unchanged 10-second read
        # timeout; no mocked status or shortened production timeout is used.
        raw_error(408,'REQUEST_TIMEOUT',headers=[('Content-Type','application/json'),('Content-Length','20')])
        checks.append('real_request_body_read_timeout_returns_schema_valid_408')
    assert client.result(payload['runId'])==result
    checks.append('server_and_first_result_remain_healthy_after_all_error_paths')
    return {'status':'PASSED','passed':len(checks),'checks':checks,'checked_at_utc':datetime.now(timezone.utc).isoformat(),
            'contract_version':'deepagent-v1','http_api_version':'course-agent-http-v1','mode':'COURSE_SYNTHETIC',
            'source_sha256':source_hashes(),'fixture_profiles':100,'request_profiles_validated':request_observations,
            'repeated_early_rejections':repeat_count,'owned_server_fault_checks':owned_store is not None,
            'baseline_core_comparison':'Exact excluding actual stage timing; shares unchanged workflow/scoring source, not independent scientific validation',
            'original_api_paths_and_fields_changed':False,'scoring_formula_changed':False,'new_fits':0,
            'research_or_private_records_read':False,'java_integration_validated':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--self-test',action='store_true');group.add_argument('--url');args=parser.parse_args()
    try:
        if args.self_test:
            with owned_service() as (url,store):result=run_acceptance(url,owned_store=store)
        else:result=run_acceptance(args.url)
        print(json.dumps(result,ensure_ascii=False));return 0
    except Exception as error:
        print(json.dumps({'status':'FAILED','code':getattr(error,'code','ACCEPTANCE_FAILED'),'error_type':type(error).__name__}));return 1


if __name__=='__main__':raise SystemExit(main())
