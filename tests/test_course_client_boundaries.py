"""Caller mutation must not change an authorized course HTTP operation."""
import copy
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch

from python_service.course_client import CourseClient, CourseClientError
from python_service.deepagent_contract import run_workflow
from python_service.demo_scoring import score_java_synthetic_payload
from python_service.course_acceptance import owned_service

ROOT = Path(__file__).resolve().parents[1]
TRACE = 'client-boundary-test'


def request():
    return json.loads((ROOT / 'contracts/examples/deepagent-v1.request.example.json').read_text(encoding='utf-8'))


class Connection:
    def __init__(self, result, *, during_request=None, during_response=None):
        self.raw = json.dumps(result, ensure_ascii=False).encode('utf-8')
        self.headers = Message()
        for key, value in [('Content-Type', 'application/json'), ('Content-Length', str(len(self.raw))), ('X-Trace-Id', TRACE)]:
            self.headers[key] = value
        self.during_request, self.during_response = during_request, during_response
        self.sent = []
        self.closed = False

    def request(self, method, path, body=None, headers=None):
        self.sent.append((method, path, body, headers))
        if self.during_request:
            self.during_request()

    def getresponse(self):
        if self.during_response:
            self.during_response()
        return SimpleNamespace(status=200, headers=self.headers, getheader=self.headers.get, read=lambda _: self.raw)

    def close(self):
        self.closed = True


class ClientBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.body = request()
        self.original = copy.deepcopy(self.body)
        self.result = run_workflow(self.original, score_java_synthetic_payload)
        self.client = CourseClient()

    def test_create_health_caller_mutation_does_not_change_sent_or_bound_request(self):
        def health():
            self.body['runId'] = 'run-caller-changed'
            self.body['features'][1]['featureValue'] = .9
        connection = Connection(self.result)
        with patch.object(self.client, 'health', side_effect=health), patch(
                'python_service.course_client.http.client.HTTPConnection', return_value=connection):
            self.assertEqual(self.client.create(self.body, trace_id=TRACE), self.result)
        self.assertEqual(json.loads(connection.sent[0][2]), self.original)
        self.assertEqual(self.client._requests, {self.original['runId']: self.original})

    def test_create_response_caller_mutation_cannot_rebind_success_identity(self):
        changed = dict(copy.deepcopy(self.body), runId='run-caller-changed')
        changed_result = run_workflow(changed, score_java_synthetic_payload)
        connection = Connection(changed_result, during_response=lambda: self.body.update(changed))
        self.client._ready = True
        with patch('python_service.course_client.http.client.HTTPConnection', return_value=connection):
            with self.assertRaises(CourseClientError) as caught:
                self.client.create(self.body, trace_id=TRACE)
        self.assertEqual(caught.exception.code, 'RESULT_IDENTITY')
        self.assertTrue(caught.exception.request_outcome_unknown)
        self.assertEqual(self.client._requests[self.original['runId']], self.original)

    def test_get_health_caller_mutation_does_not_change_expected_request(self):
        connection = Connection(self.result)
        def health():
            self.body['features'][1]['featureValue'] = .9
        with patch.object(self.client, 'health', side_effect=health), patch(
                'python_service.course_client.http.client.HTTPConnection', return_value=connection):
            value = self.client.result(self.original['runId'], expected_request=self.body, trace_id=TRACE)
        self.assertEqual(value, self.result)
        self.assertEqual(connection.sent[0][0], 'GET')

    def test_invalid_trace_does_not_probe_health_or_bind_unsent_request(self):
        with patch.object(self.client, 'health') as health:
            with self.assertRaises(CourseClientError) as caught:
                self.client.create(self.body, trace_id='invalid trace')
        self.assertEqual(caught.exception.code, 'INVALID_TRACE_ID')
        health.assert_not_called()
        self.assertEqual(self.client._requests, {})

    def test_invalid_get_trace_does_not_probe_health(self):
        with patch.object(self.client, 'health') as health:
            with self.assertRaises(CourseClientError) as caught:
                self.client.result(self.body['runId'], expected_request=self.body, trace_id='invalid trace')
        self.assertEqual(caught.exception.code, 'INVALID_TRACE_ID')
        health.assert_not_called()

    def test_existing_bound_post_keeps_original_when_caller_changes_during_send(self):
        self.client._ready = True
        self.client._requests[self.body['runId']] = copy.deepcopy(self.body)
        connection = Connection(self.result, during_request=lambda: self.body.update(subjectCode='DEMO-CHANGED'))
        with patch('python_service.course_client.http.client.HTTPConnection', return_value=connection):
            self.assertEqual(self.client.create(self.body, trace_id=TRACE), self.result)
        self.assertEqual(self.client._requests[self.original['runId']], self.original)

    def test_invalid_request_has_no_network_or_binding(self):
        self.body['visits'][0]['mmse'] = 10**400
        with patch.object(self.client, 'health') as health, patch(
                'python_service.course_client.http.client.HTTPConnection') as connection:
            with self.assertRaises(CourseClientError) as caught:
                self.client.create(self.body, trace_id=TRACE)
        self.assertEqual(caught.exception.code, 'INVALID_REQUEST')
        self.assertFalse(caught.exception.request_outcome_unknown)
        self.assertEqual(self.client._requests, {})
        health.assert_not_called()
        connection.assert_not_called()

    def test_unencodable_caller_text_is_local_invalid_request(self):
        self.body['dataVersion'] = 'demo-\ud800'
        with patch.object(self.client, 'health') as health:
            with self.assertRaises(CourseClientError) as caught:
                self.client.create(self.body)
        self.assertEqual(caught.exception.code, 'INVALID_REQUEST')
        self.assertEqual(self.client._requests, {})
        health.assert_not_called()

    def test_invalid_trace_does_not_replace_existing_binding(self):
        self.client._requests[self.original['runId']] = copy.deepcopy(self.original)
        with patch.object(self.client, 'health') as health:
            with self.assertRaises(CourseClientError):
                self.client.create(self.body, trace_id='bad\r\ntrace')
        self.assertEqual(self.client._requests[self.original['runId']], self.original)
        health.assert_not_called()

    def test_wire_size_failure_occurs_before_health_or_binding(self):
        with patch('python_service.course_client.MAX_REQUEST', 1), patch.object(self.client, 'health') as health:
            with self.assertRaises(CourseClientError) as caught:
                self.client.create(self.body)
        self.assertEqual(caught.exception.code, 'REQUEST_TOO_LARGE')
        self.assertFalse(caught.exception.request_outcome_unknown)
        self.assertEqual(self.client._requests, {})
        health.assert_not_called()

    def test_encoding_failure_occurs_before_health_or_binding(self):
        with patch('python_service.course_client.json.dumps', side_effect=ValueError('PRIVATE_ENCODER_DETAIL')), patch.object(self.client, 'health') as health:
            with self.assertRaises(CourseClientError) as caught:
                self.client.create(self.body)
        self.assertEqual(caught.exception.code, 'INVALID_JSON')
        self.assertNotIn('PRIVATE', str(caught.exception))
        self.assertEqual(self.client._requests, {})
        health.assert_not_called()

    def test_failed_health_does_not_bind_or_submit(self):
        with patch.object(self.client, 'health', side_effect=CourseClientError('SERVICE_CONTRACT_MISMATCH')), patch(
                'python_service.course_client.http.client.HTTPConnection') as connection:
            with self.assertRaises(CourseClientError) as caught:
                self.client.create(self.body)
        self.assertFalse(caught.exception.request_outcome_unknown)
        self.assertEqual(self.client._requests, {})
        connection.assert_not_called()

    def test_uncertain_post_retains_entry_snapshot_for_read_only_lookup(self):
        def response():
            self.body.update(subjectCode='DEMO-CHANGED')
            self.body['features'].clear()
            raise TimeoutError()
        connection = Connection(self.result, during_response=response)
        self.client._ready = True
        with patch('python_service.course_client.http.client.HTTPConnection', return_value=connection):
            with self.assertRaises(CourseClientError) as caught:
                self.client.create(self.body, trace_id=TRACE)
        self.assertTrue(caught.exception.request_outcome_unknown)
        self.assertEqual(len(connection.sent), 1)
        self.assertEqual(self.client._requests, {self.original['runId']: self.original})
        lookup = Connection(self.result)
        with patch('python_service.course_client.http.client.HTTPConnection', return_value=lookup):
            self.assertEqual(self.client.result(self.original['runId'], trace_id=TRACE), self.result)
        self.assertEqual(lookup.sent[0][0], 'GET')

    def test_get_response_mutation_does_not_rebind_explicit_expected_request(self):
        connection = Connection(self.result, during_response=lambda: self.body['features'].clear())
        self.client._ready = True
        with patch('python_service.course_client.http.client.HTTPConnection', return_value=connection):
            self.assertEqual(self.client.result(self.original['runId'], expected_request=self.body, trace_id=TRACE), self.result)
        self.assertEqual(self.client._requests, {})

    def test_same_score_changed_mri_context_cannot_replace_request_evidence(self):
        changed = copy.deepcopy(self.body)
        # Right MRI is context, so its raw value is not exposed by this DTO.
        # Its recorded date is exposed and must remain request-bound.
        changed['features'][2]['recordedAt'] = '2025-02-01'
        changed_result = run_workflow(changed, score_java_synthetic_payload)
        self.assertEqual(changed_result['riskScore'], self.result['riskScore'])
        connection = Connection(changed_result, during_response=lambda: self.body.update(changed))
        self.client._ready = True
        with patch('python_service.course_client.http.client.HTTPConnection', return_value=connection):
            with self.assertRaises(CourseClientError) as caught:
                self.client.create(self.body, trace_id=TRACE)
        self.assertTrue(caught.exception.request_outcome_unknown)
        self.assertEqual(self.client._requests[self.original['runId']], self.original)

    def test_blocked_snapshot_is_not_changed_to_supported_window_during_health(self):
        self.body['predictionWindowMonths'] = 12
        original = copy.deepcopy(self.body)
        result = run_workflow(original, score_java_synthetic_payload)
        connection = Connection(result)
        with patch.object(self.client, 'health', side_effect=lambda: self.body.update(predictionWindowMonths=24)), patch(
                'python_service.course_client.http.client.HTTPConnection', return_value=connection):
            value = self.client.create(self.body, trace_id=TRACE)
        self.assertEqual(value['status'], 'BLOCKED')
        self.assertIsNone(value['riskScore'])
        self.assertEqual(json.loads(connection.sent[0][2]), original)

    def test_conflicting_expected_request_is_rejected_before_health_or_get(self):
        self.client._requests[self.body['runId']] = copy.deepcopy(self.body)
        self.body['features'].clear()
        with patch.object(self.client, 'health') as health, patch(
                'python_service.course_client.http.client.HTTPConnection') as connection:
            with self.assertRaises(CourseClientError) as caught:
                self.client.result(self.body['runId'], expected_request=self.body)
        self.assertEqual(caught.exception.code, 'REQUEST_BINDING_MISMATCH')
        health.assert_not_called()
        connection.assert_not_called()

    def test_real_http_health_mutation_preserves_create_get_and_replay(self):
        with owned_service() as (url, store):
            client = CourseClient(url)
            health = client.health
            def mutate():
                value = health()
                self.body.update(runId='run-caller-other', subjectCode='DEMO-CHANGED')
                self.body['features'].clear()
                return value
            with patch.object(client, 'health', side_effect=mutate):
                value = client.create(self.body)
            self.assertEqual(value['runId'], self.original['runId'])
            self.assertEqual(client.result(self.original['runId']), value)
            self.assertEqual(client.create(self.original), value)
            self.assertEqual(list(store.runs), [self.original['runId']])

    def test_real_http_caller_mutation_while_workflow_is_inflight(self):
        entered, release = threading.Event(), threading.Event()
        def workflow(body, scorer):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test did not release workflow')
            return run_workflow(body, scorer)
        with owned_service() as (url, store), patch('python_service.server.run_workflow', side_effect=workflow) as work:
            client = CourseClient(url)
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(client.create, self.body)
                try:
                    self.assertTrue(entered.wait(5))
                    self.body['runId'] = 'run-inflight-changed'
                    self.body['visits'].clear()
                finally:
                    release.set()
                value = future.result(timeout=5)
            self.assertEqual(work.call_count, 1)
            self.assertEqual(client.result(self.original['runId']), value)
            self.assertEqual(list(store.runs), [self.original['runId']])

    def test_real_http_maximum_utf8_history_uses_exact_entry_snapshot(self):
        self.body['visits'] = [dict(visitCode='访'*45+f'{i:05}', visitDate=(date(2024,1,1)+timedelta(days=i*4)).isoformat(),
            mmse=25+(i%3)*.125, moca=24, cdrSb=.5) for i in range(100)]
        self.body['features'] = [dict(self.body['features'][i%3], recordedAt=(date(2024,1,1)+timedelta(days=(i%100)*4)).isoformat()) for i in range(500)]
        original = copy.deepcopy(self.body)
        with owned_service() as (url, store):
            client = CourseClient(url)
            health = client.health
            def mutate():
                value = health()
                self.body['visits'].clear()
                self.body['features'].clear()
                return value
            with patch.object(client, 'health', side_effect=mutate):
                value = client.create(self.body)
            self.assertEqual(value['status'], 'COMPLETED')
            self.assertEqual(client._requests[original['runId']], original)
            self.assertEqual(client.result(original['runId']), value)


if __name__ == '__main__':
    unittest.main()
