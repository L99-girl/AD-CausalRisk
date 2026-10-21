"""Reject schema-valid corruption across the fixed four-stage result boundary."""
import copy
from contextlib import contextmanager
import itertools
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker
from python_service.course_batch import execute_course_batch, prepare_course_batch
from python_service.course_client import CourseClient, CourseClientError
from python_service.course_protocol import CourseContract, CourseProtocolError, validate_course_result
from python_service.course_recovery import reconcile_course_run
from python_service.course_report import build_course_report, CourseReportError
from python_service.deepagent_contract import run_workflow
from python_service.demo_scoring import score_java_synthetic_payload
from python_service.server import AgentServer, RunStore

ROOT = Path(__file__).resolve().parents[1]


def request():
    return json.loads((ROOT / 'contracts/examples/deepagent-v1.request.example.json').read_text(encoding='utf-8'))


def result(body):
    return run_workflow(body, score_java_synthetic_payload)


def compensate(value):
    value['explanations'][0]['contribution'] = round(value['explanations'][0]['contribution'] + .01, 4)
    value['explanations'][1]['contribution'] = round(value['explanations'][1]['contribution'] - .01, 4)


class CorruptingStore(RunStore):
    """An intentionally untrusted peer, after the real store's own boundary."""
    def create(self, body):
        value = super().create(body)
        compensate(value)
        return value

    def get(self, run_id):
        value = super().get(run_id)
        compensate(value)
        return value


@contextmanager
def peer():
    server = AgentServer(('127.0.0.1', 0), CorruptingStore())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', server.store
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class ResultIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.body = request()
        self.contract = CourseContract()
        self.validator = Draft202012Validator(self.contract.schemas['AgentResult'], format_checker=FormatChecker())

    def rejects(self, change, code, body=None):
        body = body or self.body
        value = result(body)
        change(value)
        self.validator.validate(value)  # Every negative case passes the independent wire schema.
        with self.assertRaises(CourseProtocolError) as error:
            validate_course_result(value, body, self.contract)
        self.assertEqual(error.exception.code, code)

    def test_balanced_contribution_corruption_cannot_hide_behind_same_total(self):
        self.rejects(compensate, 'EXPLANATION_RULE_VALUES')

    def test_result_from_other_input_with_same_identity_dates_and_terms_is_rejected(self):
        value = result(self.body)
        self.body['visits'][-1]['mmse'] = 29.555
        self.validator.validate(value)
        with self.assertRaises(CourseProtocolError):
            validate_course_result(value, self.body, self.contract)

    def test_clipped_score_does_not_mask_incorrect_contributions(self):
        for visit in self.body['visits']:
            visit.update(mmse=0, moca=0, cdrSb=18)
        self.body['visits'][0]['mmse'] = 30
        for feature in self.body['features']:
            feature['featureValue'] = 2 if feature['featureName'] == 'APOE_E4_COUNT' else 0
        self.assertEqual(result(self.body)['riskScore'], .95)
        self.rejects(lambda x: x['explanations'][0].update(contribution=.3), 'EXPLANATION_RULE_VALUES')

    def test_direction_is_bound_to_original_unrounded_rule_term(self):
        self.rejects(lambda x: x['explanations'][0].update(direction='DOWN'), 'EXPLANATION_DIRECTION')

    def test_subprecision_term_change_is_not_accepted_by_aggregate_tolerance(self):
        self.rejects(lambda x: x['explanations'][0].update(contribution=x['explanations'][0]['contribution'] + 1e-8),
                     'EXPLANATION_RULE_VALUES')

    def test_one_last_decimal_score_shift_is_rejected_even_within_aggregate_tolerance(self):
        self.rejects(lambda x: x.update(riskScore=round(x['riskScore'] + .0001, 4)), 'SCORE_RULE_VALUE')

    def test_exact_level_uses_unrounded_score_at_display_rounding_boundary(self):
        self.body['visits'] = [dict(self.body['visits'][-1], mmse=24.5, moca=25, cdrSb=1.3)]
        self.body['features'] = [dict(self.body['features'][0], featureValue=2),
                                 dict(self.body['features'][1], featureValue=.283637)]
        value = result(self.body)
        self.assertEqual(value['riskScore'], .65)
        self.assertEqual(value['riskLevel'], 'MEDIUM')
        self.rejects(lambda x: x.update(riskLevel='HIGH'), 'SCORE_RULE_VALUE')

    def test_partial_cognition_cannot_be_relabelled_pass_by_removing_warnings(self):
        self.body['visits'][-1]['moca'] = None
        self.rejects(lambda x: x.update(qualityStatus='PASS', warnings=[]), 'QUALITY_WARNINGS')

    def test_invented_warning_is_not_a_real_quality_decision(self):
        self.rejects(lambda x: x.update(qualityStatus='WARN', warnings=['invented']), 'QUALITY_WARNINGS')

    def test_blocked_quality_reasons_must_include_the_actual_window_failure(self):
        self.body['predictionWindowMonths'] = 12
        self.rejects(lambda x: x.update(warnings=['invented']), 'QUALITY_WARNINGS')

    def test_duplicate_warning_does_not_create_additional_evidence(self):
        self.body['features'] = []
        self.rejects(lambda x: x['warnings'].append(x['warnings'][0]), 'QUALITY_WARNINGS')

    def test_warning_order_does_not_change_its_meaning(self):
        self.body['features'] = []
        value = result(self.body)
        value['warnings'].reverse()
        validate_course_result(value, self.body, self.contract)

    def test_model_node_cannot_be_relabelled_prior_evidence(self):
        self.rejects(lambda x: next(n for n in x['graph']['nodes'] if n['id'] == 'WARNING').update(evidenceLevel='PRIOR'),
                     'GRAPH_EVIDENCE')

    def test_cognition_node_cannot_claim_a_fabricated_source_date(self):
        self.rejects(lambda x: next(n for n in x['graph']['nodes'] if n['id'] == 'COGNITION').update(observedAt='2025-01-01'),
                     'GRAPH_SOURCE_DATE')

    def test_graph_stage_active_path_count_matches_actual_graph(self):
        self.rejects(lambda x: x['stages'][1]['summary'].update(activePaths=0), 'STAGE_EVIDENCE')

    def test_boolean_path_count_is_not_an_integer_count(self):
        self.rejects(lambda x: x['stages'][1]['summary'].update(activePaths=True), 'STAGE_EVIDENCE')

    def test_scoring_stage_method_cannot_claim_a_different_algorithm(self):
        self.rejects(lambda x: x['stages'][2]['summary'].update(method='fitted-clinical-model'), 'STAGE_EVIDENCE')

    def test_explanation_stage_count_is_bound_to_actual_terms(self):
        self.rejects(lambda x: x['stages'][3]['summary'].update(contributionCount=0), 'STAGE_EVIDENCE')

    def test_required_scientific_limitations_cannot_be_replaced(self):
        self.rejects(lambda x: x.update(limitations=['independently validated clinical prediction']), 'RESULT_SCOPE')

    def test_additional_metadata_and_limitations_are_compatible(self):
        value = result(self.body)
        value['stages'][1]['summary']['extraMetadata'] = 'not a known semantic field'
        value['limitations'].append('additional restriction')
        validate_course_result(value, self.body, self.contract)

    def test_direct_result_limitations_do_not_mutate_later_runs_or_required_text(self):
        first = result(self.body)
        before = copy.deepcopy(first['limitations'])
        first['limitations'].append('one result only')
        self.assertEqual(result(self.body)['limitations'], before)

    def test_validator_does_not_execute_workflow_or_score_tool(self):
        value = result(self.body)
        before = copy.deepcopy((value, self.body))
        with patch('python_service.deepagent_contract.run_workflow', side_effect=AssertionError('EXECUTED')), \
             patch('python_service.demo_scoring.score_java_synthetic_payload', side_effect=AssertionError('SCORED')):
            validate_course_result(value, self.body, self.contract)
        self.assertEqual((value, self.body), before)

    def test_all_100_original_profiles_remain_compatible(self):
        bodies = json.loads((ROOT / 'fixtures/synthetic_subjects_100.json').read_text(encoding='utf-8'))['subjects']
        for body in bodies:
            value = result(body)
            self.validator.validate(value)
            validate_course_result(value, body, self.contract)

    def test_every_cognition_and_modality_missing_combination_remains_compatible(self):
        for cognition, modalities in itertools.product(range(8), range(8)):
            body = request()
            for bit, name in enumerate(('mmse', 'moca', 'cdrSb')):
                if cognition & (1 << bit):
                    body['visits'][-1][name] = None
            body['features'] = [row for bit, row in enumerate(body['features']) if not modalities & (1 << bit)]
            value = result(body)
            self.validator.validate(value)
            validate_course_result(value, body, self.contract)

    def test_raw_direction_thresholds_are_checked_before_four_decimal_rounding(self):
        for cdr, direction in [(.01999, 'NEUTRAL'), (.02, 'NEUTRAL'), (.02001, 'UP')]:
            self.body['visits'] = [dict(self.body['visits'][-1], mmse=None, moca=None, cdrSb=cdr)]
            value = result(self.body)
            term = next(row for row in value['explanations'] if row['feature'] == 'CDR_SB')
            self.assertEqual(term['contribution'], .002)
            self.assertEqual(term['direction'], direction)
            validate_course_result(value, self.body, self.contract)

    def test_left_zero_and_right_fallback_follow_existing_scorer_preference(self):
        for left in (None, 0, .8):
            self.body['features'][1]['featureValue'] = left
            self.body['features'][2]['featureValue'] = .1
            value = result(self.body)
            validate_course_result(value, self.body, self.contract)

    def test_corrupt_success_is_refused_by_report_generation(self):
        value = result(self.body)
        compensate(value)
        with self.assertRaises(CourseReportError):
            build_course_report(self.body, value)

    def test_actual_http_client_and_read_only_recovery_reject_balanced_corruption(self):
        with peer() as (url, store):
            client = CourseClient(url)
            with self.assertRaises(CourseClientError) as error:
                client.create(self.body)
            self.assertTrue(error.exception.request_outcome_unknown)
            self.assertEqual(error.exception.code, 'EXPLANATION_RULE_VALUES')
            recovered = reconcile_course_run(CourseClient(url), self.body)
            self.assertEqual(recovered['lookupStatus'], 'LOOKUP_FAILED')
            self.assertIsNone(recovered['result'])
            self.assertFalse(recovered['submissionAttemptedByRecovery'])
            self.assertEqual(len(store.runs), 1)

    def test_actual_batch_stops_and_saves_no_untrusted_result_or_report(self):
        body = json.loads((ROOT / 'python_service/examples/course-batch.synthetic.json').read_text(encoding='utf-8'))
        plan = prepare_course_batch(body['previewInput'], body['runIds'])
        with tempfile.TemporaryDirectory() as temporary, peer() as (url, store):
            target = Path(temporary) / 'batch'
            summary = execute_course_batch(plan, CourseClient(url), target)
            self.assertEqual(summary['counts']['UNKNOWN'], 1)
            self.assertEqual(summary['counts']['NOT_ATTEMPTED'], 1)
            self.assertEqual(len(store.runs), 1)
            self.assertFalse(list(target.glob('*.result.json')))
            self.assertFalse(list(target.glob('*.report.*')))


if __name__ == '__main__':
    unittest.main()
