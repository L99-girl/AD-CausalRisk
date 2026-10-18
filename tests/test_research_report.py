"""Synthetic report correctness, scope rejection, escaping and reproducibility."""
import copy
import json
from pathlib import Path
import unittest
from python_service.research_report import build_report, render_html, ReportError, LABELS, STAGES, VARIANTS


def task():
    core = {'contractVersion': 'adni-v8-research-v1', 'modelVersion': 'adni-v8-final-materialized-2026-10-11',
            'variant': 'trajectory_graph', 'status': 'RESEARCH_COMPUTATION_COMPLETE', 'scope': 'LOCAL_RESEARCH_ONLY',
            'clinicalUseEstablished': False, 'caseCode': 'LOCAL-SYNTHETIC-REPORT', 'predictionWindowMonths': 24,
            'qualityStatus': 'PASS', 'adCumulativeIncidence': .2, 'otherDementiaCumulativeIncidence': .1,
            'explanation': {'reference': 'source_withdrawal_with_derived_features_and_masks_recomputed',
                            'causalEffectIdentified': False, 'baseline': .1, 'reconstructionResidual': 0.,
                            'contributions': [{'sourceFamily': name, 'contribution': .02} for name in LABELS]},
            'graph': {'nodes': [{'source_visit': 'DEMO-REPORT', 'feature': 'mmse', 'value': 27,
                                 'unit': 'score', 'measurement_date': '2021-01-01'}]},
            'stages': [{'stage': name} for name in STAGES], 'modelArtifactSha256': 'a' * 64, 'missingInputs': []}
    return {'id': 'wb2-' + 'a' * 32, 'status': 'COMPLETED', 'input_mode': 'SYNTHETIC_TEST',
            'variant': 'trajectory_graph', 'created_at_utc': '2026-01-01T00:00:00+00:00',
            'result': {'fixture_sha256': 'b' * 64, 'upstream': {'inputMode': 'SYNTHETIC_TEST', 'result': core}}}


class ReportTests(unittest.TestCase):
    def test_research_report_preserves_model_numbers_and_bindings(self):
        source = task(); report = build_report(source)
        self.assertEqual(report['predictions'], {'ad': .2, 'other_dementia': .1})
        self.assertEqual(report['sources'][0]['value'], 27)
        self.assertFalse(report['clinical_use_established'])
        self.assertFalse(report['causal_effect_identified'])
        self.assertFalse(report['stage_durations_available'])
        self.assertEqual(report['fixture_sha256'], 'b' * 64)

    def test_teaching_view_omits_source_values_and_technical_hash_display(self):
        report = build_report(task(), audience='teaching')
        self.assertEqual(report['sources'], [])
        html = render_html(task(), audience='teaching')
        self.assertIn('教学演示报告', html)
        self.assertNotIn('合成输入来源', html)
        self.assertNotIn('a' * 64, html)
        self.assertIn('非诊疗报告', html)

    def test_report_is_deterministic_and_does_not_mutate_input(self):
        source = task(); before = copy.deepcopy(source)
        self.assertEqual(render_html(source), render_html(source))
        self.assertEqual(source, before)
        report = build_report(source); report['predictions']['ad'] = .9
        self.assertEqual(build_report(source)['predictions']['ad'], .2)

    def test_all_six_saved_variants_supported_without_recomputation(self):
        for variant in VARIANTS:
            source = task(); source['variant'] = source['result']['upstream']['result']['variant'] = variant
            self.assertEqual(build_report(source)['variant'], variant)

    def test_only_completed_synthetic_tasks_can_be_reported(self):
        for state in ('PENDING', 'RUNNING', 'FAILED', 'CANCELLED'):
            source = task(); source['status'] = state
            with self.assertRaisesRegex(ReportError, 'REPORT_TASK_NOT_COMPLETED'):build_report(source)
        source = task(); source['input_mode'] = 'REAL_RETROSPECTIVE_RESEARCH'
        with self.assertRaisesRegex(ReportError, 'REPORT_SCOPE_NOT_ALLOWED'):build_report(source)

    def test_real_alias_or_source_cannot_be_relabelled_as_synthetic_report(self):
        for mutate in (lambda core: core.update(caseCode='LOCAL-REAL-ADNI-R-PRIVATE'),
                       lambda core: core['graph']['nodes'][0].update(source_visit='ADNI-R-PRIVATE')):
            source = task(); mutate(source['result']['upstream']['result'])
            with self.assertRaisesRegex(ReportError, 'REPORT_SCOPE_NOT_ALLOWED'):render_html(source)

    def test_clinical_or_causal_claim_rejected(self):
        for mutate in (lambda core: core.update(clinicalUseEstablished=True),
                       lambda core: core['explanation'].update(causalEffectIdentified=True)):
            source = task(); mutate(source['result']['upstream']['result'])
            with self.assertRaisesRegex(ReportError, 'REPORT_SCOPE_NOT_ALLOWED'):build_report(source)

    def test_invalid_probability_sum_boolean_and_nonfinite_rejected(self):
        for value in (float('nan'), float('inf'), True, -.1, 1.1, .95):
            source = task(); source['result']['upstream']['result']['adCumulativeIncidence'] = value
            with self.assertRaises(ReportError):build_report(source)

    def test_contribution_identity_and_reconstruction_checked(self):
        for mutate in (lambda exp: exp.update(baseline=.3),
                       lambda exp: exp.update(reconstructionResidual=.01),
                       lambda exp: exp['contributions'][0].update(sourceFamily='unknown'),
                       lambda exp: exp['contributions'][0].update(contribution=True)):
            source = task(); mutate(source['result']['upstream']['result']['explanation'])
            with self.assertRaises(ReportError):build_report(source)

    def test_versions_stage_order_and_hashes_checked(self):
        for mutate in (lambda core: core.update(modelVersion='unknown'),
                       lambda core: core.update(stages=[]),
                       lambda core: core.update(predictionWindowMonths=36),
                       lambda core: core.update(modelArtifactSha256='../private')):
            source = task(); mutate(source['result']['upstream']['result'])
            with self.assertRaises(ReportError):build_report(source)

    def test_html_escapes_values_and_has_no_script_or_remote_assets(self):
        source = task()
        source['result']['upstream']['result']['graph']['nodes'][0]['feature'] = '<img src=x onerror=alert(1)>'
        html = render_html(source)
        self.assertNotIn('<img', html)
        self.assertIn('&lt;img', html)
        self.assertNotIn('<script', html)
        self.assertNotIn('https://', html)
        self.assertIn('@media print', html)
        self.assertIn('Ctrl+P', html)

    def test_unselected_request_metadata_cannot_leak_into_report(self):
        source = task(); source['result']['request'] = {'private': 'DO-NOT-EXPORT-UNSELECTED'}
        self.assertNotIn('DO-NOT-EXPORT-UNSELECTED', json.dumps(build_report(source)))
        self.assertNotIn('DO-NOT-EXPORT-UNSELECTED', render_html(source))

    def test_malformed_inputs_return_safe_error_codes(self):
        for source in (None, {}, {'input_mode': []}):
            with self.assertRaises(ReportError) as error:build_report(source)
            self.assertTrue(error.exception.code.startswith('REPORT_'))

    def test_unknown_audience_rejected(self):
        with self.assertRaisesRegex(ReportError, 'REPORT_AUDIENCE_INVALID'):build_report(task(), audience='patient')


if __name__ == '__main__':
    unittest.main()
