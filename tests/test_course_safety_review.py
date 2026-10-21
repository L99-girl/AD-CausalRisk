"""Content binding, safe failure records and actual consumer rejection."""
import copy
from contextlib import contextmanager
import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from python_service.course_batch import prepare_course_batch, execute_course_batch
from python_service.course_client import CourseClient, CourseClientError
from python_service.course_recovery import reconcile_course_run
from python_service.course_report import build_course_report, render_course_html, CourseReportError
from python_service.course_safety import review_course_output, MAX_REQUEST_BYTES, MAX_RESULT_BYTES
from python_service.deepagent_contract import run_workflow
from python_service.demo_scoring import score_java_synthetic_payload
from python_service.server import AgentServer, RunStore

ROOT = Path(__file__).resolve().parents[1]


def request():
    return json.loads((ROOT / 'contracts/examples/deepagent-v1.request.example.json').read_text(encoding='utf-8'))


def result(body):
    return run_workflow(body, score_java_synthetic_payload)


def altered_message(value):
    value['explanations'][0]['message'] = 'PRIVATE_DETAIL已证明治疗获益'


class PeerStore(RunStore):
    def __init__(self, change):
        super().__init__()
        self.change, self.posts, self.gets = change, 0, 0

    def create(self, body):
        self.posts += 1
        value = super().create(body)
        if self.change: self.change(value)
        return value

    def get(self, run_id):
        self.gets += 1
        value = super().get(run_id)
        if self.change: self.change(value)
        return value


@contextmanager
def peer(change=None):
    store = PeerStore(change)
    server = AgentServer(('127.0.0.1', 0), store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}', store
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class SafetyReviewTests(unittest.TestCase):
    def setUp(self):
        self.body = request()
        self.value = result(self.body)

    def assert_boundaries(self, review):
        self.assertTrue(review['reviewRequired'])
        for key in ('manualReviewCompleted', 'clinicalUseAllowed', 'clinicalValidityEstablished',
                    'causalEffectIdentified', 'sourceAuthenticityVerified', 'upstreamExecutionVerified',
                    'modelExecutedByReview', 'persisted'):
            self.assertIs(review[key], False)

    def test_acceptance_never_grants_clinical_or_business_approval(self):
        review = review_course_output(self.body, self.value)
        self.assertEqual(review['status'], 'ACCEPTED')
        self.assertEqual(review['findings'], [])
        self.assertTrue(review['predictionAvailable'])
        self.assert_boundaries(review)

    def test_blocked_review_passes_without_prediction(self):
        for field, value in (('predictionWindowMonths', 12), ('visits', [])):
            body = request()
            body[field] = value
            review = review_course_output(body, result(body))
            self.assertEqual(review['status'], 'ACCEPTED')
            self.assertFalse(review['predictionAvailable'])
            self.assert_boundaries(review)

    def test_binding_matches_independent_canonical_json_hashes(self):
        review = review_course_output(self.body, self.value)
        for name, value in (('request', self.body), ('result', self.value)):
            raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
            self.assertEqual(review[name + 'Sha256'], hashlib.sha256(raw).hexdigest())
        raw = (ROOT / 'contracts/python-agent.openapi.json').read_bytes()
        self.assertEqual(review['contractSha256'], hashlib.sha256(raw).hexdigest())
        hashes = {name: hashlib.sha256((ROOT / 'python_service' / name).read_bytes()).hexdigest()
                  for name in ('course_safety.py', 'course_protocol.py', 'course_graph.py', 'course_fusion.py', 'deepagent_contract.py')}
        expected = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode('ascii')).hexdigest()
        self.assertEqual(review['policySha256'], expected)

    def test_dictionary_order_does_not_change_binding(self):
        first = review_course_output(self.body, self.value)
        second = review_course_output(dict(reversed(list(self.body.items()))), dict(reversed(list(self.value.items()))))
        self.assertEqual(first, second)

    def test_even_allowed_duration_changes_alter_result_binding(self):
        first = review_course_output(self.body, self.value)
        self.value['stages'][0]['durationMs'] += 1
        second = review_course_output(self.body, self.value)
        self.assertEqual(second['status'], 'ACCEPTED')
        self.assertNotEqual(first['resultSha256'], second['resultSha256'])

    def test_request_changes_are_bound_and_stale_result_is_rejected(self):
        first = review_course_output(self.body, self.value)
        self.body['visits'][-1]['mmse'] = 30
        second = review_course_output(self.body, self.value)
        self.assertNotEqual(first['requestSha256'], second['requestSha256'])
        self.assertEqual(second['status'], 'REJECTED')
        self.assertFalse(second['predictionAvailable'])

    def test_rejection_record_has_only_fixed_codes_and_hashes(self):
        altered_message(self.value)
        review = review_course_output(self.body, self.value)
        self.assertEqual(review['findings'], [{'code': 'OUTPUT_EXPLANATION_TEXT'}])
        self.assertEqual(review['status'], 'REJECTED')
        self.assertNotIn('PRIVATE_DETAIL', json.dumps(review))
        self.assertNotIn(self.body['subjectCode'], json.dumps(review))
        self.assert_boundaries(review)

    def test_unsupported_real_request_cannot_receive_acceptance(self):
        self.body['subjectCode'] = 'REAL-PRIVATE_DETAIL'
        review = review_course_output(self.body, self.value)
        self.assertEqual(review['status'], 'REJECTED')
        self.assertNotIn('PRIVATE_DETAIL', json.dumps(review))

    def test_oversize_request_is_rejected_before_copying(self):
        self.body['dataVersion'] = 'demo-' + 'x' * MAX_REQUEST_BYTES
        with patch('python_service.course_graph.copy.deepcopy', side_effect=AssertionError('COPIED')):
            review = review_course_output(self.body, self.value)
        self.assertEqual(review['findings'], [{'code': 'REVIEW_INPUT_SIZE'}])
        self.assertIsNone(review['requestSha256'])

    def test_oversize_result_is_rejected_without_echo(self):
        self.value['limitations'].append('PRIVATE_DETAIL' * (MAX_RESULT_BYTES // 10))
        review = review_course_output(self.body, self.value)
        self.assertEqual(review['findings'], [{'code': 'REVIEW_INPUT_SIZE'}])
        self.assertIsNone(review['resultSha256'])
        self.assertNotIn('PRIVATE_DETAIL', json.dumps(review))

    def test_cyclic_nonjson_nonfinite_and_surrogate_inputs_fail_safely(self):
        cycle = {}
        cycle['cycle'] = cycle
        for malformed in (cycle, {'bad': object()}, {'bad': float('nan')}, {'bad': '\ud800'}):
            review = review_course_output(malformed, self.value)
            self.assertEqual(review['status'], 'REJECTED')
            self.assertEqual(review['findings'], [{'code': 'REVIEW_INPUT_JSON'}])
            self.assert_boundaries(review)

    def test_json_scalars_arrays_and_nonstring_keys_never_accepted(self):
        for malformed in (None, True, [], 1, 'PRIVATE_DETAIL', {1: 'bad'}):
            review = review_course_output(malformed, self.value)
            self.assertEqual(review['status'], 'REJECTED')
            self.assertNotIn('PRIVATE_DETAIL', json.dumps(review))

    def test_policy_io_failure_has_fixed_code(self):
        with patch('python_service.course_safety._policy_digest', side_effect=OSError('PRIVATE_DETAIL')):
            review = review_course_output(self.body, self.value)
        self.assertEqual(review['findings'], [{'code': 'REVIEW_POLICY_UNAVAILABLE'}])
        self.assertNotIn('PRIVATE_DETAIL', json.dumps(review))

    def test_inputs_and_records_are_independent(self):
        before = copy.deepcopy((self.body, self.value))
        first = review_course_output(self.body, self.value)
        first['findings'].append({'code': 'changed'})
        second = review_course_output(self.body, self.value)
        self.assertEqual(second['findings'], [])
        self.assertEqual((self.body, self.value), before)

    def test_review_calls_no_workflow_scorer_network_or_model(self):
        with patch('python_service.deepagent_contract.run_workflow', side_effect=AssertionError('WORKFLOW')), \
             patch('python_service.demo_scoring.score_java_synthetic_payload', side_effect=AssertionError('SCORE')), \
             patch('http.client.HTTPConnection', side_effect=AssertionError('NETWORK')):
            self.assertEqual(review_course_output(self.body, self.value)['status'], 'ACCEPTED')

    def test_actual_http_bad_tool_is_one_safe_500_without_cache(self):
        def bad(body):
            value = score_java_synthetic_payload(body)
            altered_message(value)
            return value
        with peer() as (url, store):
            with patch('python_service.server.score_java_synthetic_payload', side_effect=bad) as scorer:
                with self.assertRaises(CourseClientError) as error: CourseClient(url).create(self.body)
            self.assertEqual(error.exception.http_status, 500)
            self.assertEqual(error.exception.code, 'ASSESSMENT_FAILED')
            self.assertNotIn('PRIVATE_DETAIL', str(error.exception))
            self.assertEqual(scorer.call_count, 1)
            self.assertEqual(store.posts, 1)
            self.assertEqual(store.runs, {})

    def test_actual_post_and_get_recovery_reject_untrusted_peer_without_retry(self):
        with peer(altered_message) as (url, store):
            client = CourseClient(url)
            with self.assertRaises(CourseClientError) as error: client.create(self.body)
            self.assertEqual(error.exception.code, 'OUTPUT_EXPLANATION_TEXT')
            self.assertTrue(error.exception.request_outcome_unknown)
            with self.assertRaises(CourseClientError) as lookup: client.result(self.body['runId'])
            self.assertEqual(lookup.exception.code, 'OUTPUT_EXPLANATION_TEXT')
            self.assertFalse(lookup.exception.request_outcome_unknown)
            recovered = reconcile_course_run(CourseClient(url), self.body)
            self.assertEqual(recovered['lookupStatus'], 'LOOKUP_FAILED')
            self.assertIsNone(recovered['result'])
            self.assertFalse(recovered['submissionAttemptedByRecovery'])
            self.assertFalse(recovered['resubmissionAuthorized'])
            self.assertEqual(store.posts, 1)
            self.assertEqual(store.gets, 2)
            self.assertEqual(len(store.runs), 1)

    def test_actual_blocked_peer_cannot_hide_claim_in_summary(self):
        self.body['predictionWindowMonths'] = 12
        with peer(lambda x: x['stages'][0]['summary'].update(clinicalUseAllowed=True)) as (url, store):
            with self.assertRaises(CourseClientError) as error: CourseClient(url).create(self.body)
            self.assertEqual(error.exception.code, 'OUTPUT_SUMMARY_FIELDS')
            self.assertTrue(error.exception.request_outcome_unknown)
            self.assertEqual(store.posts, 1)

    def test_actual_batch_stops_before_second_submission_and_saves_no_bad_output(self):
        body = json.loads((ROOT / 'python_service/examples/course-batch.synthetic.json').read_text(encoding='utf-8'))
        plan = prepare_course_batch(body['previewInput'], body['runIds'])
        with tempfile.TemporaryDirectory() as temporary, peer(altered_message) as (url, store):
            target = Path(temporary) / 'batch'
            summary = execute_course_batch(plan, CourseClient(url), target)
            self.assertEqual(summary['counts']['UNKNOWN'], 1)
            self.assertEqual(summary['counts']['NOT_ATTEMPTED'], 1)
            self.assertEqual(store.posts, 1)
            self.assertFalse(list(target.glob('*.result.json')))
            self.assertFalse(list(target.glob('*.report.*')))

    def test_reports_for_both_audiences_reject_unreviewed_claims(self):
        for change in (altered_message, lambda x: x['limitations'].append('临床可用'),
                       lambda x: x['graph']['edges'][0].update(note='病因已证明'),
                       lambda x: x['stages'][0]['summary'].update(reviewPassed=True)):
            value = copy.deepcopy(self.value)
            change(value)
            for audience in ('research', 'teaching'):
                with self.assertRaises(CourseReportError): build_course_report(self.body, value, audience=audience)
                with self.assertRaises(CourseReportError): render_course_html(self.body, value, audience=audience)

    def test_all_100_native_results_are_reviewed_without_new_predictions(self):
        bodies = json.loads((ROOT / 'fixtures/synthetic_subjects_100.json').read_text(encoding='utf-8'))['subjects']
        for body in bodies:
            value = result(body)
            with patch('python_service.deepagent_contract.run_workflow', side_effect=AssertionError('EXECUTED')):
                review = review_course_output(body, value)
            self.assertEqual(review['status'], 'ACCEPTED')
            self.assert_boundaries(review)


if __name__ == '__main__': unittest.main()
