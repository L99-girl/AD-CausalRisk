import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from python_service.course_client import CourseClient, CourseClientError
from python_service.course_interop import vector_requests, owned_lab
from python_service.course_recovery import reconcile_course_run
from python_service.deepagent_contract import run_workflow
from python_service.demo_scoring import score_java_synthetic_payload

ROOT = Path(__file__).resolve().parents[1]


class CourseRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.request = vector_requests()[0][1]
        self.result = run_workflow(self.request, score_java_synthetic_payload)
        self.client = Mock(spec=CourseClient)
        self.client.result.return_value = copy.deepcopy(self.result)

    def test_found_is_validated_but_does_not_certify_business_or_execution(self):
        report = reconcile_course_run(self.client, self.request)
        self.assertEqual(report['lookupStatus'], 'FOUND'); self.assertEqual(report['result'], self.result)
        self.assertIsNone(report['executionOccurred']); self.assertTrue(report['businessHistoryRequired'])
        self.assertFalse(report['resubmissionAuthorized']); self.assertFalse(report['sourceAuthenticityVerified'])
        self.client.create.assert_not_called()
        self.client.result.assert_called_once_with(self.request['runId'], expected_request=self.request)

    def test_result_and_input_are_copied(self):
        before = copy.deepcopy(self.request)
        report = reconcile_course_run(self.client, self.request)
        report['result']['stages'][0]['durationMs'] = -999
        self.assertEqual(self.request, before)
        self.assertGreaterEqual(self.client.result.return_value['stages'][0]['durationMs'], 0)

    def test_lookup_cannot_mutate_expected_request_for_validation(self):
        def change(run_id, *, expected_request):
            expected_request['runId'] = 'run-unrelated'
            return dict(self.result, runId='run-unrelated')
        self.client.result.side_effect = change
        report = reconcile_course_run(self.client, self.request)
        self.assertEqual(report['lookupStatus'], 'LOOKUP_FAILED'); self.assertIsNone(report['result'])
        self.assertEqual(self.request['runId'], 'run-interop-completed')

    def test_only_exact_missing_run_error_means_cache_miss(self):
        self.client.result.side_effect = CourseClientError('RUN_NOT_FOUND', 404)
        report = reconcile_course_run(self.client, self.request)
        self.assertEqual(report['lookupStatus'], 'CACHE_MISS'); self.assertIsNone(report['executionOccurred'])
        self.client.create.assert_not_called()
        for code, status in [('ROUTE_NOT_FOUND',404), ('RUN_NOT_FOUND',500), ('LOCAL_TRANSPORT_FAILED',None)]:
            self.client.result.side_effect = CourseClientError(code, status)
            self.assertEqual(reconcile_course_run(self.client,self.request)['lookupStatus'], 'LOOKUP_FAILED')

    def test_500_or_503_does_not_become_a_missing_run_or_success(self):
        for code,status in [('ASSESSMENT_FAILED',500),('RUN_CAPACITY_REACHED',503)]:
            self.client.result.side_effect = CourseClientError(code,status)
            report = reconcile_course_run(self.client,self.request)
            self.assertEqual(report['lookupStatus'],'LOOKUP_FAILED'); self.assertIsNone(report['result'])
            self.assertEqual(report['error'],{'code':code,'httpStatus':status})

    def test_invalid_request_is_rejected_before_any_network_method(self):
        for request in ({}, dict(self.request,subjectCode='REAL-PRIVATE'), dict(self.request,runId='../secret')):
            with self.assertRaises(CourseClientError): reconcile_course_run(self.client,request)
        self.assertEqual(self.client.mock_calls,[])

    def test_untrusted_found_result_is_not_exposed(self):
        for result in ({}, dict(self.result,runId='run-unrelated'), dict(self.result,riskScore=None)):
            self.client.result.return_value=result
            report=reconcile_course_run(self.client,self.request)
            self.assertEqual(report['lookupStatus'],'LOOKUP_FAILED');self.assertIsNone(report['result'])

    def test_blocked_found_keeps_null_and_no_prediction(self):
        request=vector_requests()[1][1]
        self.client.result.return_value=run_workflow(request,score_java_synthetic_payload)
        report=reconcile_course_run(self.client,request)
        self.assertEqual(report['lookupStatus'],'FOUND');self.assertIsNone(report['result']['riskScore'])
        self.assertEqual(report['result']['riskLevel'],'UNAVAILABLE')

    def test_error_does_not_echo_exception_text_or_full_request(self):
        self.client.result.side_effect=CourseClientError('LOCAL_TRANSPORT_FAILED')
        text=json.dumps(reconcile_course_run(self.client,self.request))
        self.assertNotIn('visits',text);self.assertNotIn('features',text)

    def test_cli_existing_output_refuses_before_connecting(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'previous.json';output.write_text('KEEP',encoding='utf-8')
            command=[sys.executable,'-B','-m','python_service.course_recovery','--url','http://127.0.0.1:1',
                     '--request','contracts/examples/deepagent-v1.request.example.json','--output',str(output)]
            run=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,1);self.assertIn('OUTPUT_EXISTS',run.stdout)
            self.assertEqual(output.read_text(encoding='utf-8'),'KEEP')

    def test_cli_cache_miss_has_distinct_exit_and_no_submission(self):
        with tempfile.TemporaryDirectory() as folder, owned_lab() as (url, server):
            output=Path(folder)/'lookup.json'
            run=subprocess.run([sys.executable,'-B','-m','python_service.course_recovery','--url',url,
                                '--request','contracts/examples/deepagent-v1.request.example.json','--output',str(output)],
                               cwd=ROOT,capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,2);self.assertEqual(server.post_calls,0)
            self.assertEqual(json.loads(output.read_text(encoding='utf-8'))['lookupStatus'],'CACHE_MISS')

    def test_cli_found_preserves_result_and_does_not_submit(self):
        with tempfile.TemporaryDirectory() as folder, owned_lab() as (url, server):
            source=Path(folder)/'request.json';source.write_text(json.dumps(self.request),encoding='utf-8')
            output=Path(folder)/'lookup.json';result=CourseClient(url).create(self.request)
            run=subprocess.run([sys.executable,'-B','-m','python_service.course_recovery','--url',url,
                                '--request',str(source),'--output',str(output)],cwd=ROOT,capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,0);self.assertEqual(server.post_calls,1)
            self.assertEqual(json.loads(output.read_text(encoding='utf-8'))['result'],result)

    def test_cli_invalid_file_or_real_alias_never_exposes_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'input.json';source.write_text('{"private":"DO_NOT_ECHO"}',encoding='utf-8')
            output=Path(folder)/'never.json'
            run=subprocess.run([sys.executable,'-B','-m','python_service.course_recovery','--request',str(source),
                                '--output',str(output)],cwd=ROOT,capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,1);self.assertNotIn('DO_NOT_ECHO',run.stdout+run.stderr)
            self.assertFalse(output.exists())
