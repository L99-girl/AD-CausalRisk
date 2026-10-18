"""Constructed loopback responses; no private records, estimators or research imports."""
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from python_service.workbench_client import (WorkbenchClient, ClientError, validate_result,
    decode_json, PREFIX, COOKIE, CONTRACT, MODEL, MODE, FAMILIES)

ALIAS = 'ADNI-R-CONSTRUCTED-CLIENT'
JOB = 'wb4-' + 'a' * 32
CODE = 'constructed-private-access-code'
TOKEN = 'constructed-cookie-token-00000000'


def result():
    return {'contract': CONTRACT, 'computation_contract': 'adni-v8-real-retrospective-v1', 'mode': MODE, 'alias': ALIAS,
            'historical_realtime_prediction_available': False, 'clinical_use_established': False, 'export_allowed': False,
            'qualification': {'out_of_sample': None}, 'availability': {'mmse': None},
            'core': {'contractVersion': 'adni-v8-research-v1', 'modelVersion': MODEL, 'caseCode': 'LOCAL-REAL-' + ALIAS,
                     'variant': 'trajectory_graph', 'status': 'RESEARCH_COMPUTATION_COMPLETE', 'scope': 'LOCAL_RESEARCH_ONLY',
                     'predictionWindowMonths': 24, 'clinicalUseEstablished': False, 'adCumulativeIncidence': .2,
                     'otherDementiaCumulativeIncidence': .1, 'explanation': {
                         'reference': 'source_withdrawal_with_derived_features_and_masks_recomputed', 'causalEffectIdentified': False,
                         'baseline': .1, 'reconstructionResidual': 0.,
                         'contributions': [{'sourceFamily': name, 'contribution': .02} for name in sorted(FAMILIES)]}}}


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self):
        super().__init__(('127.0.0.1', 0), Handler)
        self.requests = []
        self.override = None
        self.auth = False
        self.expired = False
        self.job = None
        self.result = result()
        self.job_status = 'COMPLETED'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, data, status=200, headers=()):
        raw = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.execute()

    def do_POST(self):
        self.execute(True)

    def execute(self, write=False):
        server = self.server
        body = json.loads(self.rfile.read(int(self.headers['Content-Length']))) if write else None
        server.requests.append((self.path, body, self.headers.get('Cookie')))
        if server.override:
            return self.respond(*server.override)
        if self.path == PREFIX + 'status':
            return self.respond({'application_id': 'ad-causalrisk-system', 'contract': CONTRACT, 'mode': MODE,
                                 'model_version': MODEL, 'maximum_batch_size': 10, 'clinical_use_established': False,
                                 'historical_realtime_prediction_available': False, 'arbitrary_patient_upload_allowed': False,
                                 'export_allowed': False})
        if self.path == PREFIX + 'health':
            return self.respond({'application_id': 'ad-causalrisk-system', 'status': 'ready',
                                 'checks': {'constructed_binding_check': True}, 'models_deserialized': 0,
                                 'clinical_tables_parsed': 0, 'new_fits': 0})
        if write:
            assert self.headers['Origin'] == f'http://127.0.0.1:{server.server_port}'
        if self.path == PREFIX + 'session':
            if body != {'access_code': CODE}:
                return self.respond({'code': 'LOGIN_FAILED', 'message': 'do-not-print-response'}, 401)
            server.auth = True
            return self.respond({'authenticated': True, 'expires_in_seconds': 1800}, headers=[
                ('Set-Cookie', f'{COOKIE}={TOKEN}; HttpOnly; SameSite=Strict; Path={PREFIX}; Max-Age=1800')])
        if server.expired or not server.auth or self.headers.get('Cookie') != COOKIE + '=' + TOKEN:
            return self.respond({'code': 'SESSION_REQUIRED'}, 401)
        if self.path == PREFIX + 'logout':
            server.auth = False
            return self.respond({'authenticated': False})
        if self.path.startswith(PREFIX + 'real/cases?'):
            return self.respond({'page': 1, 'page_size': 20, 'total': 1, 'registry_total': 2,
                                 'projected_total': 1, 'ready_total': 1,
                                 'items': [{'alias': ALIAS, 'state': 'READY'}]})
        if self.path == PREFIX + 'jobs':
            if server.job and body != server.job[0]:
                return self.respond({'code': 'IDEMPOTENCY_CONFLICT'}, 409)
            replay = server.job is not None
            job = {'id': JOB, 'mode': MODE, 'request_key': body['request_key'], 'status': 'PENDING',
                   'total': 1, 'processed': 0, 'result_persistence': False,
                   'cases': [{'alias': ALIAS, 'status': 'PENDING'}]}
            server.job = (body, job)
            return self.respond({'job': job, 'idempotent_replay': replay}, 200 if replay else 202)
        if self.path.endswith('/results/' + ALIAS):
            return self.respond(server.result)
        if self.path in {PREFIX + 'jobs/' + JOB, PREFIX + 'jobs/' + JOB + '/cancel'}:
            job = copy.deepcopy(server.job[1])
            state = 'CANCELLED' if self.path.endswith('/cancel') else server.job_status
            job.update(status=state, processed=0 if state in {'RUNNING', 'CANCELLED'} else 1)
            job['cases'][0]['status'] = state
            return self.respond({'job': job})
        return self.respond({'code': 'NOT_FOUND'}, 404)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.server = Server()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.client = WorkbenchClient(self.url, timeout=2)

    def tearDown(self):
        self.client._forget()
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def submit(self):
        self.client.login(CODE)
        return self.client.submit([ALIAS], request_key='constructed-request')

    def test_status_then_login_catalogue_and_confirmed_logout(self):
        self.assertFalse(self.client.authenticated)
        self.client.login(CODE)
        self.assertEqual(self.client.cases()['items'][0]['alias'], ALIAS)
        self.client.logout()
        self.assertFalse(self.client.authenticated)
        self.assertFalse(self.server.auth)

    def test_submit_replay_wait_and_validated_result(self):
        first = self.submit()
        self.assertFalse(first['idempotent_replay'])
        self.assertTrue(self.client.submit([ALIAS], request_key='constructed-request')['idempotent_replay'])
        self.assertEqual(self.client.wait(JOB)['status'], 'COMPLETED')
        self.assertEqual(self.client.result(JOB, ALIAS), result())

    def test_conflicting_request_does_not_silently_create_new_job(self):
        self.submit()
        with self.assertRaises(ClientError) as error:
            self.client.submit([ALIAS], request_key='different-request')
        self.assertEqual((error.exception.code, error.exception.http_status), ('IDEMPOTENCY_CONFLICT', 409))

    def test_cancel_is_explicit(self):
        self.submit()
        self.assertEqual(self.client.cancel(JOB)['status'], 'CANCELLED')

    def test_wait_timeout_does_not_cancel_or_resubmit(self):
        self.submit(); self.server.job_status = 'RUNNING'
        with self.assertRaisesRegex(ClientError, 'WAIT_TIMEOUT'):
            self.client.wait(JOB, timeout=.03, poll_interval=.01)
        self.assertFalse(any(path.endswith('/cancel') for path, _, _ in self.server.requests))
        self.assertEqual(sum(path == PREFIX + 'jobs' for path, _, _ in self.server.requests), 1)

    def test_failed_and_cancelled_terminal_jobs_are_returned_honestly(self):
        self.submit()
        for state in ('FAILED', 'CANCELLED'):
            with self.subTest(state=state):
                self.server.job_status = state
                self.assertEqual(self.client.wait(JOB)['status'], state)

    def test_expired_session_clears_cookie_and_known_jobs(self):
        self.submit(); self.server.expired = True
        with self.assertRaises(ClientError) as error:
            self.client.job(JOB)
        self.assertEqual(error.exception.http_status, 401)
        self.assertFalse(self.client.authenticated)
        self.assertEqual(self.client._jobs, {})

    def test_network_error_on_post_is_marked_uncertain(self):
        self.client.login(CODE)
        from unittest.mock import patch
        with patch('http.client.HTTPConnection.request', side_effect=ConnectionResetError):
            with self.assertRaises(ClientError) as error:
                self.client.submit([ALIAS], request_key='constructed-request')
        self.assertTrue(error.exception.request_outcome_unknown)
        self.assertEqual(str(error.exception), 'LOCAL_TRANSPORT_FAILED')

    def test_context_logout_and_original_error_preserved(self):
        with self.assertRaisesRegex(ValueError, 'constructed-error'):
            with self.client:
                self.client.login(CODE)
                raise ValueError('constructed-error')
        self.assertFalse(self.server.auth)
        self.assertFalse(self.client.authenticated)

    def test_logout_failure_still_clears_local_credentials(self):
        self.client.login(CODE); self.server.override = ({'code': 'LOCAL_UNAVAILABLE'}, 503)
        with self.assertRaises(ClientError):
            self.client.logout()
        self.assertFalse(self.client.authenticated)

    def test_no_private_request_before_login(self):
        with self.assertRaisesRegex(ClientError, 'SESSION_REQUIRED'):
            self.client.cases()
        self.assertEqual(self.server.requests, [])

    def test_invalid_batch_and_path_injection_rejected_without_requests(self):
        for aliases in ([], [ALIAS] * 2, [ALIAS] * 11, ['../Cases.json'], ['RAW-ID']):
            with self.subTest(aliases=aliases), self.assertRaises(ClientError):
                self.client.submit(aliases, request_key='constructed-request')
        for identifier in ('../../session', [], None):
            with self.assertRaises(ClientError):self.client.job(identifier)
        self.assertEqual(self.server.requests, [])

    def test_invalid_pagination_timeout_and_state_rejected(self):
        for arguments in ({'page': True}, {'page': 0}, {'page_size': 101}, {'state': 'CLINICAL'}):
            with self.assertRaises(ClientError):self.client.cases(**arguments)
        with self.assertRaises(ClientError):self.client.wait(JOB, timeout=float('nan'))
        self.assertEqual(self.server.requests, [])

    def test_result_not_requested_cannot_be_read(self):
        self.submit()
        count = len(self.server.requests)
        with self.assertRaisesRegex(ClientError, 'RESULT_NOT_REQUESTED'):
            self.client.result(JOB, 'ADNI-R-OTHER')
        self.assertEqual(len(self.server.requests), count)

    def test_redirect_never_forwards_cookie(self):
        self.client.login(CODE)
        self.server.override = ({}, 302, [('Location', 'https://example.invalid/')])
        count = len(self.server.requests)
        with self.assertRaisesRegex(ClientError, 'REDIRECT_REFUSED'):self.client.status()
        self.assertEqual(len(self.server.requests), count + 1)

    def test_error_never_contains_response_message_or_credentials(self):
        self.server.override = ({'code': 'invalid ' + ALIAS, 'message': CODE + TOKEN}, 503)
        with self.assertRaises(ClientError) as error:self.client.status()
        self.assertEqual(str(error.exception), 'REMOTE_REJECTED')
        for secret in (CODE, TOKEN, ALIAS):
            self.assertNotIn(secret, str(error.exception))
            self.assertNotIn(secret, repr(self.client))

    def test_wrong_service_rejected_before_access_code_is_sent(self):
        self.server.override = ({'serviceMode': 'COURSE_SYNTHETIC'}, 200)
        with self.assertRaises(ClientError):self.client.login(CODE)
        self.assertTrue(all(body is None for _, body, _ in self.server.requests))

    def test_unready_health_cannot_be_reported_as_ready(self):
        self.server.override = ({'application_id': 'ad-causalrisk-system', 'status': 'ready',
                                 'checks': {'source_binding': False}}, 200)
        with self.assertRaises(ClientError):self.client.health()

    def test_malformed_and_oversized_response_rejected(self):
        from unittest.mock import patch
        for raw in (b'{"a":1,"a":2}', b'{"score":NaN}'):
            self.server.override = (raw, 200)
            with self.assertRaisesRegex(ClientError, 'INVALID_RESPONSE_JSON'):self.client.status()
        self.server.override = ({'a': 'x' * 100}, 200)
        with patch('python_service.workbench_client.MAX_RESPONSE', 20):
            with self.assertRaisesRegex(ClientError, 'RESPONSE_TOO_LARGE'):self.client.status()

    def test_terminal_job_identity_and_state_invariants(self):
        self.submit()
        bad = copy.deepcopy(self.server.job[1]); bad.update(status='COMPLETED', processed=1)
        # A terminal success cannot contain a pending case.
        self.server.override = ({'job': bad}, 200)
        with self.assertRaises(ClientError):self.client.job(JOB)
        bad.update(id='wb4-' + 'b' * 32)
        with self.assertRaises(ClientError):self.client.job(JOB)

    def test_cli_prints_only_capabilities(self):
        root = Path(__file__).resolve().parents[1]
        command = subprocess.run([sys.executable, '-B', '-m', 'python_service.workbench_client', '--url', self.url],
                                 cwd=root, capture_output=True, text=True, timeout=10)
        self.assertEqual(command.returncode, 0)
        self.assertEqual(json.loads(command.stdout)['mode'], MODE)
        for secret in (ALIAS, CODE, TOKEN):self.assertNotIn(secret, command.stdout + command.stderr)


class ValidationTests(unittest.TestCase):
    def test_non_loopback_urls_and_credentials_refused(self):
        for url in ('https://127.0.0.1:8084', 'http://localhost:8084', 'http://example.com:8084',
                    'http://127.0.0.1:8084/?token=x', 'http://user:pass@127.0.0.1:8084', 'http://127.0.0.1:65536'):
            with self.subTest(url=url), self.assertRaises(ClientError):WorkbenchClient(url)

    def test_duplicate_nonfinite_and_nonobject_json_refused(self):
        for value in (b'{"a":1,"a":2}', b'{"x":NaN}', b'{"x":1e999}', b'[]', b'\xff'):
            with self.subTest(value=value), self.assertRaises(ClientError):decode_json(value)

    def test_probability_identity_and_attribution_corruption_refused(self):
        mutations = [lambda data: data.update(alias='ADNI-R-OTHER'),
                     lambda data: data['core'].update(modelVersion='unverified-model'),
                     lambda data: data['core'].update(adCumulativeIncidence=1.01),
                     lambda data: data['core'].update(otherDementiaCumulativeIncidence=.9),
                     lambda data: data['core']['explanation'].update(baseline=.3),
                     lambda data: data['core']['explanation']['contributions'][0].update(contribution=True),
                     lambda data: data['core']['explanation']['contributions'][0].update(sourceFamily='unknown'),
                     lambda data: data['core']['explanation'].update(reconstructionResidual=.01)]
        for mutate in mutations:
            data = result(); mutate(data)
            with self.assertRaises(ClientError):validate_result(data, ALIAS)

    def test_clinical_causal_availability_or_out_of_sample_claim_refused(self):
        mutations = [lambda data: data.update(export_allowed=True),
                     lambda data: data.update(clinical_use_established=True),
                     lambda data: data.update(historical_realtime_prediction_available=True),
                     lambda data: data['qualification'].update(out_of_sample=True),
                     lambda data: data['availability'].update(mmse='2020-01-01'),
                     lambda data: data['core']['explanation'].update(causalEffectIdentified=True)]
        for mutate in mutations:
            data = result(); mutate(data)
            with self.assertRaises(ClientError):validate_result(data, ALIAS)

    def test_missing_or_malformed_credential_file_does_not_reveal_path(self):
        client = WorkbenchClient()
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / 'private-file-name'
            with self.assertRaises(ClientError) as error:client.login_file(private)
            self.assertNotIn(str(private), str(error.exception))
            private.write_bytes(b'\xff')
            with self.assertRaises(ClientError):client.login_file(private)


if __name__ == '__main__':
    unittest.main()
