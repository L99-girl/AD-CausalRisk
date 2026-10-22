"""Input failures stay 400; invalid computation cannot produce cached success."""
import copy
from contextlib import contextmanager
import http.client
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker
from python_service.course_protocol import CourseContract, CourseProtocolError, decode_json, validate_course_result
from python_service.deepagent_contract import AgentContractError, payload_digest, run_workflow
from python_service.demo_scoring import ContractError, score_java_synthetic_payload
from python_service.server import AgentServer, RunStore

ROOT = Path(__file__).resolve().parents[1]


def request():
    return json.loads((ROOT / 'contracts/examples/deepagent-v1.request.example.json').read_text(encoding='utf-8'))


@contextmanager
def service():
    server = AgentServer(('127.0.0.1', 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, server.store
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def post(port, body):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        # ASCII escaping can represent a malformed Unicode scalar in otherwise
        # valid JSON bytes; the semantic input boundary must reject it safely.
        raw = json.dumps(body, ensure_ascii=True).encode('ascii')
        connection.request('POST', '/api/agent/v1/runs', raw,
                           {'Content-Type': 'application/json', 'X-Trace-Id': 'execution-integrity'})
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


class ExecutionIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.body = request()
        self.contract = CourseContract()

    def test_huge_cognition_integers_are_validation_400_before_scoring(self):
        for field in ('mmse', 'moca', 'cdrSb'):
            for sign in (-1, 1):
                body = request()
                body['visits'][-1][field] = sign * 10**400
                with patch('python_service.server.score_java_synthetic_payload') as scorer:
                    with self.assertRaises(AgentContractError) as error:
                        RunStore().create(body)
                    self.assertEqual(error.exception.status, 400)
                    self.assertEqual(error.exception.code, 'VALIDATION_400')
                    scorer.assert_not_called()

    def test_huge_mri_integers_are_validation_400(self):
        for side in ('MRI_HIPPOCAMPUS_L', 'MRI_HIPPOCAMPUS_R'):
            body = request()
            next(row for row in body['features'] if row['featureName'] == side)['featureValue'] = 10**400
            with self.assertRaises(AgentContractError) as error:
                RunStore().create(body)
            self.assertEqual(error.exception.status, 400)

    def test_unicode_surrogates_in_data_version_and_visit_code_are_validation_400(self):
        for location in ('dataVersion', 'visitCode'):
            body = request()
            if location == 'dataVersion':
                body['dataVersion'] = 'demo-\ud800'
            else:
                body['visits'][0]['visitCode'] = 'BL-\udfff'
            with self.assertRaises(AgentContractError) as error:
                run_workflow(body, score_java_synthetic_payload)
            self.assertEqual(error.exception.status, 400)

    def test_valid_non_ascii_visit_codes_still_work(self):
        self.body['visits'][0]['visitCode'] = '基线访视'
        self.body['dataVersion'] = 'demo-构造数据'
        value = RunStore().create(self.body)
        validate_course_result(value, self.body, self.contract)

    def test_actual_http_huge_integer_and_surrogates_leave_no_run_and_recover(self):
        invalid = []
        huge = request()
        huge['visits'][-1]['mmse'] = 10**400
        invalid.append(huge)
        for field in ('dataVersion', 'visitCode'):
            body = request()
            if field == 'dataVersion':
                body[field] = 'demo-\ud800'
            else:
                body['visits'][0][field] = '\ud800'
            invalid.append(body)
        validator = Draft202012Validator(self.contract.schemas['AgentError'], format_checker=FormatChecker())
        with service() as (port, store):
            for body in invalid:
                status, error = post(port, body)
                self.assertEqual(status, 400)
                self.assertEqual(error['code'], 'VALIDATION_400')
                self.assertEqual(error['traceId'], 'execution-integrity')
                validator.validate(error)
                self.assertEqual(store.runs, {})
            self.assertEqual(post(port, request())[0], 200)
            self.assertEqual(len(store.runs), 1)

    def reject_tool(self, change):
        def tool(body):
            value = score_java_synthetic_payload(body)
            change(value)
            return value
        with self.assertRaises(AgentContractError) as error:
            run_workflow(self.body, tool)
        self.assertEqual(error.exception.status, 500)
        self.assertEqual(error.exception.code, 'ASSESSMENT_FAILED')
        self.assertNotIn('CONSTRUCTED_PRIVATE_DETAIL', str(error.exception))

    def test_null_nonfinite_wrong_and_false_scores_cannot_complete_a_workflow(self):
        for score in (None, float('nan'), float('inf'), True, .4):
            with self.subTest(score=score):
                self.reject_tool(lambda value: value.update(score=score))

    def test_legacy_tool_identity_and_versions_are_checked_before_mapping(self):
        for field, value in [('status', 'failed'), ('provider', 'CONSTRUCTED_PRIVATE_DETAIL'),
                             ('contractVersion', 'other'), ('modelVersion', 'other'), ('dataVersion', 'demo-other')]:
            with self.subTest(field=field):
                self.reject_tool(lambda row: row.update({field: value}))

    def test_legacy_tool_quality_flag_must_match_its_warnings(self):
        self.reject_tool(lambda value: value.update(qualityStatus='WARN'))

    def test_legacy_tool_missing_fields_and_nonobjects_are_safe_500(self):
        for replacement in (None, [], {}, {'score': .5}):
            with self.subTest(replacement=replacement):
                with self.assertRaises(AgentContractError) as error:
                    run_workflow(self.body, lambda _: replacement)
                self.assertEqual(error.exception.status, 500)

    def test_tool_exceptions_are_execution_500_even_when_tool_uses_input_error_type(self):
        for failure in (ValueError('CONSTRUCTED_PRIVATE_DETAIL'),
                        ContractError('CONSTRUCTED_PRIVATE_DETAIL'),
                        AgentContractError('CONSTRUCTED_PRIVATE_DETAIL', 409, 'AGENT_CONTRACT_MISMATCH')):
            with self.subTest(failure=type(failure).__name__):
                with self.assertRaises(AgentContractError) as error:
                    run_workflow(self.body, lambda _: self.raise_error(failure))
                self.assertEqual(error.exception.status, 500)
                self.assertNotIn('CONSTRUCTED_PRIVATE_DETAIL', str(error.exception))

    @staticmethod
    def raise_error(failure):
        raise failure

    def test_balanced_tool_contributions_are_not_accepted_as_valid_explanations(self):
        def change(value):
            value['explanations'][0]['contribution'] += .01
            value['explanations'][1]['contribution'] -= .01
        self.reject_tool(change)

    def test_invalid_unicode_in_tool_output_is_rejected_before_json_write(self):
        self.reject_tool(lambda value: value['explanations'][0].update(label='\ud800'))

    def test_escaped_surrogates_in_response_values_and_metadata_keys_are_invalid_json(self):
        for raw in (b'{"label":"\\ud800"}', b'{"summary":{"\\udfff":1}}'):
            with self.assertRaises(CourseProtocolError) as error:
                decode_json(raw)
            self.assertEqual(error.exception.code, 'INVALID_RESPONSE_JSON')

    def test_actual_http_invalid_unicode_tool_output_is_safe_500_and_uncached(self):
        def bad_text(body):
            value = score_java_synthetic_payload(body)
            value['explanations'][0]['label'] = '\ud800'
            return value
        with service() as (port, store):
            with patch('python_service.server.score_java_synthetic_payload', side_effect=bad_text):
                status, error = post(port, self.body)
            self.assertEqual(status, 500)
            self.assertEqual(error['code'], 'ASSESSMENT_FAILED')
            self.assertEqual(store.runs, {})

    def test_workflow_snapshot_survives_caller_mutation_during_score_call(self):
        original = copy.deepcopy(self.body)
        def tool(body):
            self.body['runId'] = 'run-mutated'
            self.body['dataVersion'] = 'demo-mutated'
            self.body['visits'][-1]['mmse'] = 30
            return score_java_synthetic_payload(body)
        value = run_workflow(self.body, tool)
        validate_course_result(value, original, self.contract)
        self.assertEqual(value['runId'], original['runId'])

    def test_store_snapshot_binds_digest_and_result_to_same_request(self):
        original = copy.deepcopy(self.body)
        store = RunStore()
        def workflow(body, tool):
            self.body['runId'] = 'run-mutated'
            self.body['visits'][-1]['mmse'] = 30
            return run_workflow(body, tool)
        with patch('python_service.server.run_workflow', side_effect=workflow):
            value = store.create(self.body)
        self.assertEqual(value['runId'], original['runId'])
        self.assertEqual(store.runs[original['runId']][0], payload_digest(original))
        self.assertEqual(store.create(original), value)

    def test_store_result_is_independent_of_workflow_return_reference(self):
        source = run_workflow(self.body, score_java_synthetic_payload)
        store = RunStore()
        with patch('python_service.server.run_workflow', return_value=source):
            value = store.create(self.body)
        source['riskScore'] = .1
        source['explanations'].clear()
        self.assertEqual(store.get(self.body['runId']), value)

    def test_invalid_workflow_return_is_rejected_before_cache_commit(self):
        source = run_workflow(self.body, score_java_synthetic_payload)
        source['riskScore'] = None
        store = RunStore()
        with patch('python_service.server.run_workflow', return_value=source):
            with self.assertRaises(AgentContractError) as error:
                store.create(self.body)
        self.assertEqual(error.exception.status, 500)
        self.assertEqual(store.runs, {})
        # Only this explicit subsequent call is a new attempt; the store never retries.
        self.assertEqual(store.create(self.body)['status'], 'COMPLETED')

    def test_actual_http_invalid_score_is_safe_500_uncached_and_not_automatic_retry(self):
        def bad_score(body):
            value = score_java_synthetic_payload(body)
            value['score'] = None
            return value
        with service() as (port, store):
            with patch('python_service.server.score_java_synthetic_payload', side_effect=bad_score) as scorer:
                status, error = post(port, self.body)
                self.assertEqual(status, 500)
                self.assertEqual(error['code'], 'ASSESSMENT_FAILED')
                self.assertEqual(scorer.call_count, 1)
                self.assertEqual(store.runs, {})
            self.assertEqual(post(port, self.body)[0], 200)
            self.assertEqual(len(store.runs), 1)

    def test_actual_http_tool_contract_error_is_execution_500(self):
        with service() as (port, store):
            with patch('python_service.server.score_java_synthetic_payload', side_effect=ContractError('CONSTRUCTED_PRIVATE_DETAIL')):
                status, error = post(port, self.body)
            self.assertEqual(status, 500)
            self.assertEqual(error['code'], 'ASSESSMENT_FAILED')
            self.assertNotIn('CONSTRUCTED_PRIVATE_DETAIL', json.dumps(error))
            self.assertEqual(store.runs, {})


if __name__ == '__main__':
    unittest.main()
