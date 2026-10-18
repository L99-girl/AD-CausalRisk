import copy
from email.message import Message
import http.client
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from python_service.course_client import CourseClient,CourseClientError,MAX_RESPONSE
from python_service.server import AgentServer
from python_service.deepagent_contract import run_workflow
from python_service.demo_scoring import score_java_synthetic_payload

ROOT=Path(__file__).resolve().parents[1]
TRACE='constructed-trace'


def fixture():return json.loads((ROOT/'contracts/examples/deepagent-v1.request.example.json').read_text(encoding='utf-8'))


class FakeConnection:
    def __init__(self,value,status=200,*,headers=None,raw=None,error=None):
        self.raw=json.dumps(value).encode() if raw is None else raw;self.status=status;self.error=error
        self.headers=Message()
        for key,value in (headers or [('Content-Type','application/json'),('Content-Length',str(len(self.raw))),('X-Trace-Id',TRACE)]):self.headers[key]=value
        self.requests=[];self.closed=False;self.reads=0
    def request(self,*args,**kwargs):self.requests.append((args,kwargs))
    def getresponse(self):
        if self.error:raise self.error
        return SimpleNamespace(status=self.status,headers=self.headers,getheader=self.headers.get,read=self.read)
    def read(self,size):self.reads+=1;return self.raw[:size]
    def close(self):self.closed=True


class CourseClientTests(unittest.TestCase):
    def setUp(self):
        self.payload=fixture();self.value=run_workflow(self.payload,score_java_synthetic_payload)
        self.client=CourseClient('http://127.0.0.1:8091');self.client._ready=True
    def invoke(self,fake,*,read=False):
        with patch('python_service.course_client.http.client.HTTPConnection',return_value=fake):
            return self.client.result(self.payload['runId'],expected_request=self.payload,trace_id=TRACE) if read else self.client.create(self.payload,trace_id=TRACE)
    def rejected(self,fake,code,*,read=False):
        with self.assertRaises(CourseClientError) as error:self.invoke(fake,read=read)
        self.assertEqual(error.exception.code,code);self.assertTrue(fake.closed)
        return error.exception

    def test_constructor_refuses_external_credentialed_query_and_invalid_urls(self):
        for url in ('https://127.0.0.1:8091','http://localhost:8091','http://example.com:8091',
                    'http://user@127.0.0.1:8091','http://127.0.0.1:8091?token=x','http://127.0.0.1:0','http://127.0.0.1:99999'):
            with self.assertRaises(CourseClientError):CourseClient(url)

    def test_timeout_and_trace_parameters_are_validated(self):
        for timeout in (0,True,float('nan'),121):
            with self.assertRaises(CourseClientError):CourseClient(timeout=timeout)
        for trace in ('','contains spaces','bad\r\nheader',False):
            with self.assertRaises(CourseClientError):self.client.create(self.payload,trace_id=trace)

    def test_success_get_uses_bound_request_without_copying_caller_mutation(self):
        self.assertEqual(self.invoke(FakeConnection(self.value)),self.value)
        self.payload['subjectCode']='DEMO-CHANGED'
        fake=FakeConnection(self.value)
        with patch('python_service.course_client.http.client.HTTPConnection',return_value=fake):
            self.assertEqual(self.client.result(self.value['runId'],trace_id=TRACE),self.value)

    def test_unknown_run_requires_explicit_binding_and_refuses_path_injection(self):
        with self.assertRaises(CourseClientError) as error:self.client.result('run-unrequested')
        self.assertEqual(error.exception.code,'REQUEST_BINDING_REQUIRED')
        for value in ('../raw','run-x?token=secret','run-x/y'):
            with self.assertRaises(CourseClientError):self.client.result(value)

    def test_wrong_bound_request_is_rejected_before_lookup(self):
        self.client._requests[self.payload['runId']]=copy.deepcopy(self.payload)
        self.payload['subjectCode']='DEMO-OTHER'
        with self.assertRaises(CourseClientError) as error:self.client.result(self.payload['runId'],expected_request=self.payload)
        self.assertEqual(error.exception.code,'REQUEST_BINDING_MISMATCH')

    def test_wrong_service_is_detected_before_sending_input(self):
        self.client._ready=False
        fake=FakeConnection({'serviceMode':'WRONG'})
        with patch('python_service.course_client.uuid4',return_value=SimpleNamespace(hex=TRACE)):
            self.rejected(fake,'SERVICE_CONTRACT_MISMATCH')
        self.assertEqual(fake.requests[0][0],('GET','/api/health'))
        self.assertEqual(len(fake.requests),1)

    def test_post_timeout_is_uncertain_without_automatic_retry(self):
        fake=FakeConnection({},error=TimeoutError())
        error=self.rejected(fake,'LOCAL_TRANSPORT_FAILED')
        self.assertTrue(error.request_outcome_unknown);self.assertEqual(len(fake.requests),1)
        self.assertIn(self.payload['runId'],self.client._requests)

    def test_get_timeout_is_not_a_new_uncertain_submission(self):
        error=self.rejected(FakeConnection({},error=TimeoutError()),'LOCAL_TRANSPORT_FAILED',read=True)
        self.assertFalse(error.request_outcome_unknown)

    def test_redirect_is_never_followed(self):
        fake=FakeConnection({},302)
        self.rejected(fake,'REDIRECT_REFUSED');self.assertEqual(len(fake.requests),1)

    def test_standard_error_exposes_code_status_but_no_remote_message(self):
        value={'code':'ASSESSMENT_FAILED','message':'CONSTRUCTED_SECRET_NOT_FOR_CLIENT','traceId':TRACE,'timestamp':'2026-10-18T00:00:00+00:00'}
        error=self.rejected(FakeConnection(value,500),'ASSESSMENT_FAILED')
        self.assertEqual(error.http_status,500);self.assertFalse(error.request_outcome_unknown)
        self.assertNotIn('CONSTRUCTED_SECRET',str(error))

    def test_error_trace_and_timestamp_must_match_contract(self):
        value={'code':'VALIDATION_400','message':'x','traceId':'other','timestamp':'2026-10-18T00:00:00+00:00'}
        self.rejected(FakeConnection(value,400),'ERROR_CONTRACT')
        value['traceId']=TRACE;value['timestamp']='yesterday'
        self.rejected(FakeConnection(value,400),'WIRE_SCHEMA_MISMATCH')

    def test_non_json_and_duplicate_response_values_are_not_accepted(self):
        for raw in (b'[]',b'{"x":NaN}',b'{"x":1e999}',b'{"x":1,"x":2}'):
            self.rejected(FakeConnection(None,raw=raw),'INVALID_RESPONSE_JSON')

    def test_response_media_framing_trace_and_size_are_validated(self):
        for headers,code in [([('Content-Type','text/html')],'RESPONSE_MEDIA_TYPE'),
                             ([('Content-Type','application/json')],'RESPONSE_FRAMING'),
                             ([('Content-Type','application/json'),('Content-Length',str(MAX_RESPONSE+1))],'RESPONSE_TOO_LARGE')]:
            self.rejected(FakeConnection(self.value,headers=headers),code)
        fake=FakeConnection(self.value);fake.headers.replace_header('X-Trace-Id','other')
        self.rejected(fake,'RESPONSE_TRACE')
        fake=FakeConnection(self.value);fake.headers['Content-Encoding']='gzip'
        self.rejected(fake,'RESPONSE_ENCODING')

    def test_schema_valid_wrong_identity_is_not_returned_as_success(self):
        self.value['runId']='run-other'
        error=self.rejected(FakeConnection(self.value),'RESULT_IDENTITY')
        self.assertTrue(error.request_outcome_unknown)

    def test_missing_or_false_result_fields_do_not_create_mock_success(self):
        for changes in ({'riskScore':None},{'dataSource':'REAL'},{'workflowVersion':'wrong'}):
            value=copy.deepcopy(self.value);value.update(changes)
            with self.assertRaises(CourseClientError):self.invoke(FakeConnection(value))

    def test_server_accepting_conflicting_request_is_rejected_locally(self):
        self.client._requests[self.payload['runId']]=copy.deepcopy(self.payload)
        self.payload['subjectCode']='DEMO-OTHER'
        self.rejected(FakeConnection(self.value),'CONFLICTING_RUN_ACCEPTED')

    def test_not_found_after_restart_does_not_resubmit(self):
        value={'code':'RUN_NOT_FOUND','message':'cache cleared','traceId':TRACE,'timestamp':'2026-10-18T00:00:00Z'}
        fake=FakeConnection(value,404)
        error=self.rejected(fake,'RUN_NOT_FOUND',read=True)
        self.assertEqual(error.http_status,404);self.assertEqual(len(fake.requests),1)
        self.assertEqual(fake.requests[0][0][0],'GET')

    def test_actual_original_http_create_replay_lookup_conflict_and_blocked(self):
        server=AgentServer(('127.0.0.1',0));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            client=CourseClient(f'http://127.0.0.1:{server.server_port}')
            result=client.create(self.payload);self.assertEqual(client.create(self.payload),result)
            self.assertEqual(client.result(self.payload['runId']),result)
            changed=copy.deepcopy(self.payload);changed['predictionWindowMonths']=12
            with self.assertRaises(CourseClientError) as error:client.create(changed)
            self.assertEqual(error.exception.http_status,409)
            changed['runId']='run-blocked-client';blocked=client.create(changed)
            self.assertEqual(blocked['status'],'BLOCKED');self.assertIsNone(blocked['riskScore'])
        finally:server.shutdown();server.server_close();thread.join(timeout=5)


if __name__=='__main__':unittest.main()
