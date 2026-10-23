"""A valid AgentError must match its operation and HTTP rejection status."""
import copy
from contextlib import contextmanager
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from python_service.course_client import CourseClient, CourseClientError
from python_service.course_recovery import reconcile_course_run
from python_service.server import AgentServer, AgentHandler
from test_course_client import FakeConnection, TRACE

ROOT = Path(__file__).resolve().parents[1]
POST_ERRORS = ((400, 'VALIDATION_400'), (408, 'REQUEST_TIMEOUT'),
               (409, 'AGENT_CONTRACT_MISMATCH'), (409, 'RUN_ID_CONFLICT'),
               (413, 'PAYLOAD_TOO_LARGE'), (415, 'UNSUPPORTED_MEDIA_TYPE'),
               (500, 'ASSESSMENT_FAILED'), (503, 'RUN_CAPACITY_REACHED'))


def request():
    return json.loads((ROOT / 'contracts/examples/deepagent-v1.request.example.json').read_text(encoding='utf-8'))


def error(code, trace=TRACE):
    return dict(code=code, message='PRIVATE_ERROR_BODY_NOT_FOR_OUTPUT', traceId=trace,
                timestamp='2026-10-23T00:00:00Z')


@contextmanager
def peer():
    class Handler(AgentHandler):
        def do_GET(self):
            self.server.gets.append(self.path)
            super().do_GET()
        def do_POST(self):
            self.server.posts += 1
            super().do_POST()
        def send_json(self, body, status=200):
            fault = self.server.fault
            kind = 'health' if self.path == '/api/health' else 'post' if self.command == 'POST' else 'get'
            if fault and kind == fault[0]:
                self.server.fault = None
                _, status, code = fault
                return super().send_json(error(code, self.trace_id), status)
            super().send_json(body, status)
    server = AgentServer(('127.0.0.1', 0))
    server.RequestHandlerClass = Handler
    server.fault = None; server.posts = 0; server.gets = []
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    try: yield server, 'http://127.0.0.1:' + str(server.server_port)
    finally: server.shutdown(); server.server_close(); worker.join(timeout=5)


class ErrorBindingTests(unittest.TestCase):
    def setUp(self):
        self.body = request()
        self.client = CourseClient(); self.client._ready = True

    def failure(self, status, code, operation='post'):
        fake = FakeConnection(error(code), status)
        with patch('python_service.course_client.http.client.HTTPConnection', return_value=fake), patch(
                'python_service.course_client.uuid4') as uuid:
            uuid.return_value.hex = TRACE
            with self.assertRaises(CourseClientError) as caught:
                if operation == 'post': self.client.create(self.body, trace_id=TRACE)
                elif operation == 'get': self.client.result(self.body['runId'], expected_request=self.body, trace_id=TRACE)
                else: self.client.health()
        self.assertTrue(fake.closed); self.assertEqual(len(fake.requests), 1)
        return caught.exception

    def test_original_post_error_pairs_are_preserved(self):
        for status, code in POST_ERRORS:
            with self.subTest(status=status, code=code):
                actual = self.failure(status, code)
                self.assertEqual((actual.http_status, actual.code), (status, code))
                self.assertFalse(actual.request_outcome_unknown)
                self.assertNotIn('PRIVATE_ERROR', str(actual))

    def test_status_code_cross_product_is_rejected_without_losing_post_uncertainty(self):
        for status in sorted({status for status, _ in POST_ERRORS}):
            for _, code in POST_ERRORS:
                if (status, code) in POST_ERRORS: continue
                with self.subTest(status=status, code=code):
                    actual = self.failure(status, code)
                    self.assertEqual(actual.code, 'ERROR_CONTRACT')
                    self.assertEqual(actual.http_status, status)
                    self.assertTrue(actual.request_outcome_unknown)
                    self.assertEqual(self.client._requests[self.body['runId']], self.body)

    def test_unknown_uppercase_error_code_is_not_a_confirmed_rejection(self):
        actual = self.failure(500, 'UNREVIEWED_REMOTE_EXTENSION')
        self.assertEqual(actual.code, 'ERROR_CONTRACT')
        self.assertTrue(actual.request_outcome_unknown)

    def test_original_result_get_errors_remain_accepted(self):
        for status, code in ((400, 'VALIDATION_400'), (404, 'RUN_NOT_FOUND'), (404, 'ROUTE_NOT_FOUND')):
            with self.subTest(status=status, code=code):
                actual = self.failure(status, code, 'get')
                self.assertEqual(actual.code, code)
                self.assertFalse(actual.request_outcome_unknown)

    def test_wrong_get_error_pair_cannot_be_a_cache_miss(self):
        for status, code in ((400, 'RUN_NOT_FOUND'), (404, 'VALIDATION_400'), (404, 'RUN_CAPACITY_REACHED')):
            with self.subTest(status=status, code=code):
                actual = self.failure(status, code, 'get')
                self.assertEqual(actual.code, 'ERROR_CONTRACT')
                self.assertFalse(actual.request_outcome_unknown)

    def test_health_cannot_claim_that_a_run_was_not_found(self):
        actual = self.failure(404, 'RUN_NOT_FOUND', 'health')
        self.assertEqual(actual.code, 'ERROR_CONTRACT')
        self.assertFalse(self.client._ready)
        self.assertFalse(actual.request_outcome_unknown)

    def test_health_original_validation_and_route_errors_are_preserved(self):
        for status, code in ((400, 'VALIDATION_400'), (404, 'ROUTE_NOT_FOUND')):
            with self.subTest(status=status, code=code):
                self.assertEqual(self.failure(status, code, 'health').code, code)

    def test_actual_bad_health_is_lookup_failed_without_run_lookup_or_post(self):
        with peer() as (server, url):
            server.fault = 'health', 404, 'RUN_NOT_FOUND'
            client = CourseClient(url)
            report = reconcile_course_run(client, self.body)
            self.assertEqual(report['lookupStatus'], 'LOOKUP_FAILED')
            self.assertEqual(report['error'], {'code': 'ERROR_CONTRACT', 'httpStatus': 404})
            self.assertEqual(server.gets, ['/api/health']); self.assertEqual(server.posts, 0)
            self.assertEqual(client._requests, {})
            self.assertIsNone(report['executionOccurred'])
            self.assertFalse(report['resubmissionAuthorized'])

    def test_actual_post_mismatched_error_retains_cache_and_recovers_by_get(self):
        with peer() as (server, url):
            client = CourseClient(url); server.fault = 'post', 500, 'RUN_ID_CONFLICT'
            with self.assertRaises(CourseClientError) as caught: client.create(self.body)
            self.assertEqual(caught.exception.code, 'ERROR_CONTRACT')
            self.assertTrue(caught.exception.request_outcome_unknown)
            self.assertIn(self.body['runId'], server.store.runs)
            report = reconcile_course_run(client, self.body)
            self.assertEqual(report['lookupStatus'], 'FOUND')
            self.assertEqual(report['result'], server.store.get(self.body['runId']))
            self.assertEqual(server.posts, 1)

    def test_actual_get_wrong_pair_is_lookup_failed_and_does_not_resubmit(self):
        with peer() as (server, url):
            client = CourseClient(url); expected = client.create(self.body)
            server.fault = 'get', 404, 'VALIDATION_400'
            report = reconcile_course_run(client, self.body)
            self.assertEqual(report['lookupStatus'], 'LOOKUP_FAILED')
            self.assertEqual(report['error']['code'], 'ERROR_CONTRACT')
            self.assertEqual(server.posts, 1)
            self.assertEqual(client.result(self.body['runId']), expected)

    def test_actual_genuine_result_cache_miss_stays_cache_miss(self):
        with peer() as (server, url):
            report = reconcile_course_run(CourseClient(url), self.body)
            self.assertEqual(report['lookupStatus'], 'CACHE_MISS')
            self.assertEqual(server.gets, ['/api/health', '/api/agent/v1/runs/' + self.body['runId']])
            self.assertEqual(server.posts, 0)

    def test_actual_blocked_response_is_200_and_unchanged(self):
        body = dict(copy.deepcopy(self.body), predictionWindowMonths=12)
        with peer() as (server, url):
            client = CourseClient(url); value = client.create(body)
            self.assertEqual(value['status'], 'BLOCKED'); self.assertIsNone(value['riskScore'])
            self.assertEqual(reconcile_course_run(client, body)['result'], value)
            self.assertEqual(server.posts, 1)


if __name__ == '__main__': unittest.main()
