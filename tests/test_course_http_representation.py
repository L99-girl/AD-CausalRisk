"""UTF-8 JSON declarations and actual bytes must agree at both HTTP ends."""
from contextlib import contextmanager
from email.message import Message
import http.client
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from python_service.course_client import CourseClient, CourseClientError
from python_service.course_protocol import decode_json, CourseProtocolError
from python_service.deepagent_contract import run_workflow
from python_service.demo_scoring import score_java_synthetic_payload
from python_service.server import AgentServer, RunStore

ROOT = Path(__file__).resolve().parents[1]
TRACE = 'representation-test'


def request():
    return json.loads((ROOT / 'contracts/examples/deepagent-v1.request.example.json').read_text(encoding='utf-8'))


class CountingStore(RunStore):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def create(self, payload):
        self.calls += 1
        return super().create(payload)


@contextmanager
def service():
    store = CountingStore()
    server = AgentServer(('127.0.0.1', 0), store)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server, store
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def post(port, body, fields):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
    try:
        connection.putrequest('POST', '/api/agent/v1/runs')
        for key, value in [*fields, ('Content-Length', str(len(body))), ('X-Trace-Id', TRACE)]:
            connection.putheader(key, value)
        connection.endheaders(body)
        response = connection.getresponse()
        return response.status, json.loads(response.read().decode('utf-8'))
    finally:
        connection.close()


class ResponseConnection:
    def __init__(self, value, fields, encoding='utf-8'):
        self.raw = json.dumps(value, ensure_ascii=False).encode(encoding)
        self.headers = Message()
        for key, text in [*fields, ('Content-Length', str(len(self.raw))), ('X-Trace-Id', TRACE)]:
            self.headers[key] = text
        self.closed = False
        self.requests = []

    def request(self, *args, **kwargs):
        self.requests.append((args, kwargs))

    def getresponse(self):
        return SimpleNamespace(status=200, headers=self.headers, getheader=self.headers.get,
                               read=lambda _: self.raw)

    def close(self):
        self.closed = True


class RequestRepresentationTests(unittest.TestCase):
    def rejected(self, fields, encoding='utf-8', status=415):
        body = json.dumps(request(), ensure_ascii=False).encode(encoding)
        with service() as (server, store), patch('python_service.server.run_workflow') as workflow:
            actual, value = post(server.server_port, body, fields)
            self.assertEqual(actual, status)
            self.assertEqual(value['code'], 'UNSUPPORTED_MEDIA_TYPE' if status == 415 else 'VALIDATION_400')
            self.assertEqual(value['traceId'], TRACE)
            self.assertEqual(store.calls, 0)
            self.assertEqual(store.runs, {})
            workflow.assert_not_called()

    def test_non_utf8_declared_charset_rejected_before_store(self):
        self.rejected([('Content-Type', 'application/json; charset=iso-8859-1')])

    def test_duplicate_charset_even_equal_rejected_before_store(self):
        for charset in ('UTF-8', 'iso-8859-1'):
            with self.subTest(charset=charset):
                self.rejected([('Content-Type', 'application/json; charset=utf-8; charset=' + charset)])

    def test_extended_charset_is_not_plain_utf8_declaration(self):
        self.rejected([('Content-Type', "application/json; charset*=utf-8''utf-8")])

    def test_continued_or_malformed_charset_is_rejected(self):
        for suffix in ('; charset*0=utf-; charset*1=8', '; charset', '; charset=', '; charset="utf-8', ';'):
            with self.subTest(suffix=suffix):
                self.rejected([('Content-Type', 'application/json' + suffix)])

    def test_unsupported_content_encoding_rejected_before_store(self):
        for encoding in ('gzip', 'br', '', 'identity, gzip'):
            with self.subTest(encoding=encoding):
                self.rejected([('Content-Type', 'application/json'), ('Content-Encoding', encoding)])

    def test_duplicate_content_encoding_rejected_even_identity_first(self):
        for encoding in ('identity', 'gzip'):
            with self.subTest(encoding=encoding):
                self.rejected([('Content-Type', 'application/json'), ('Content-Encoding', 'identity'),
                               ('Content-Encoding', encoding)])

    def test_actual_non_utf8_body_is_bad_json_without_execution(self):
        for encoding in ('utf-16', 'utf-32', 'utf-16-le', 'utf-32-be'):
            with self.subTest(encoding=encoding):
                self.rejected([('Content-Type', 'application/json; charset=utf-8')], encoding, 400)

    def test_valid_media_case_quotes_and_identity_preserve_cached_result(self):
        body = request()
        body['visits'][0]['visitCode'] = '基线访视'
        raw = json.dumps(body, ensure_ascii=False).encode('utf-8')
        with service() as (server, store):
            first = None
            for media, encoding in [('application/json', None), ('Application/JSON; Charset="UTF-8"', 'Identity'),
                                    ('application/json; charset=utf-8; profile="course"', 'identity')]:
                fields = [('Content-Type', media)] + ([] if encoding is None else [('Content-Encoding', encoding)])
                status, value = post(server.server_port, raw, fields)
                self.assertEqual(status, 200)
                if first is None:
                    first = value
                self.assertEqual(value, first)
            self.assertEqual(len(store.runs), 1)
            self.assertEqual(first['riskScore'], .8304)

    def test_rejected_declaration_leaves_runid_free_for_explicit_valid_post(self):
        body = json.dumps(request()).encode('utf-8')
        with service() as (server, store):
            self.assertEqual(post(server.server_port, body, [('Content-Type', 'application/json'),
                                  ('Content-Encoding', 'gzip')])[0], 415)
            self.assertEqual(store.calls, 0)
            self.assertEqual(post(server.server_port, body, [('Content-Type', 'application/json')])[0], 200)
            self.assertEqual(store.calls, 1)


class ResponseRepresentationTests(unittest.TestCase):
    def setUp(self):
        self.body = request()
        self.value = run_workflow(self.body, score_java_synthetic_payload)
        self.client = CourseClient()
        self.client._ready = True

    def invoke(self, fields, encoding='utf-8', *, get=False):
        fake = ResponseConnection(self.value, fields, encoding)
        with patch('python_service.course_client.http.client.HTTPConnection', return_value=fake):
            value = (self.client.result(self.body['runId'], expected_request=self.body, trace_id=TRACE)
                     if get else self.client.create(self.body, trace_id=TRACE))
        return value, fake

    def rejected(self, fields, code, encoding='utf-8', *, get=False):
        fake = ResponseConnection(self.value, fields, encoding)
        with patch('python_service.course_client.http.client.HTTPConnection', return_value=fake):
            with self.assertRaises(CourseClientError) as caught:
                if get:
                    self.client.result(self.body['runId'], expected_request=self.body, trace_id=TRACE)
                else:
                    self.client.create(self.body, trace_id=TRACE)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.request_outcome_unknown, not get)
        self.assertEqual(len(fake.requests), 1)
        self.assertTrue(fake.closed)
        if not get:
            self.assertEqual(self.client._requests[self.body['runId']], self.body)

    def test_duplicate_charset_response_is_not_success(self):
        for charset in ('UTF-8', 'iso-8859-1'):
            with self.subTest(charset=charset):
                self.rejected([('Content-Type', 'application/json; charset=utf-8; charset=' + charset)], 'RESPONSE_MEDIA_TYPE')

    def test_non_utf8_charset_response_is_rejected(self):
        self.rejected([('Content-Type', 'application/json; charset=utf-16')], 'RESPONSE_MEDIA_TYPE')

    def test_extended_charset_response_is_rejected(self):
        self.rejected([('Content-Type', "application/json; charset*=utf-8''utf-8")], 'RESPONSE_MEDIA_TYPE')

    def test_continued_or_malformed_charset_response_is_rejected(self):
        for suffix in ('; charset*0=utf-; charset*1=8', '; charset', '; charset=', '; charset="utf-8', ';'):
            with self.subTest(suffix=suffix):
                self.rejected([('Content-Type', 'application/json' + suffix)], 'RESPONSE_MEDIA_TYPE')

    def test_quoted_unrelated_parameter_does_not_fake_charset_declaration(self):
        value, _ = self.invoke([('Content-Type', 'application/json; profile="course; charset*=opaque"; charset="utf-8"')])
        self.assertEqual(value, self.value)

    def test_utf8_bom_and_malformed_utf8_are_rejected(self):
        for raw in (b'\xef\xbb\xbf{}', b'{"x":"\xff"}'):
            with self.subTest(raw=raw):
                with self.assertRaises(CourseProtocolError):
                    decode_json(raw)

    def test_duplicate_content_encoding_response_is_not_success(self):
        for encoding in ('identity', 'gzip'):
            with self.subTest(encoding=encoding):
                self.rejected([('Content-Type', 'application/json'), ('Content-Encoding', 'identity'),
                               ('Content-Encoding', encoding)], 'RESPONSE_ENCODING')

    def test_valid_case_insensitive_identity_response_is_accepted(self):
        value, fake = self.invoke([('Content-Type', 'Application/JSON; Charset="UTF-8"'),
                                   ('Content-Encoding', 'Identity')])
        self.assertEqual(value, self.value)
        self.assertTrue(fake.closed)

    def test_actual_utf16_utf32_response_is_not_guessed_from_utf8_declaration(self):
        for encoding in ('utf-16', 'utf-32', 'utf-16-le', 'utf-32-be'):
            with self.subTest(encoding=encoding):
                self.rejected([('Content-Type', 'application/json; charset=utf-8')],
                              'INVALID_RESPONSE_JSON', encoding)

    def test_bad_get_representation_does_not_mark_new_uncertain_submission(self):
        self.rejected([('Content-Type', 'application/json')], 'INVALID_RESPONSE_JSON', 'utf-16', get=True)

    def test_health_wrong_actual_encoding_is_rejected_before_post_and_binding(self):
        from python_service.deepagent_contract import CONTRACT_VERSION, WORKFLOW_VERSION, MODEL_VERSION, STAGES
        health = dict(status='ok', serviceMode='COURSE_SYNTHETIC', httpApiVersion='course-agent-http-v1',
                      contractVersion=CONTRACT_VERSION, workflowVersion=WORKFLOW_VERSION, modelVersion=MODEL_VERSION,
                      dataSource='SYNTHETIC_DEMO', synchronousExecution=True, persistentRunStore=False,
                      researchEvidenceLoaded=False, individualResearchModelDeployed=False, stages=list(STAGES))
        self.client._ready = False
        fake = ResponseConnection(health, [('Content-Type', 'application/json')], 'utf-16')
        with patch('python_service.course_client.uuid4', return_value=SimpleNamespace(hex=TRACE)), patch(
                'python_service.course_client.http.client.HTTPConnection', return_value=fake):
            with self.assertRaises(CourseClientError) as caught:
                self.client.create(self.body)
        self.assertEqual(caught.exception.code, 'INVALID_RESPONSE_JSON')
        self.assertFalse(caught.exception.request_outcome_unknown)
        self.assertEqual(self.client._requests, {})
        self.assertEqual(fake.requests[0][0][0], 'GET')
        self.assertEqual(len(fake.requests), 1)

    def test_decoder_rejects_non_utf8_bytes_without_echo(self):
        for encoding in ('utf-16', 'utf-32'):
            with self.subTest(encoding=encoding):
                with self.assertRaises(CourseProtocolError) as caught:
                    decode_json('{"secret":"CONSTRUCTED_PRIVATE_TEXT"}'.encode(encoding))
                self.assertEqual(str(caught.exception), 'INVALID_RESPONSE_JSON')


if __name__ == '__main__':
    unittest.main()
