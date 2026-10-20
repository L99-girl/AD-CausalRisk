import copy
import csv
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from python_service.course_csv import preview_csv, TABLES, CsvPreviewError
from python_service.course_quality import preview_quality, field_dictionary
from python_service.course_protocol import FROZEN_CONTRACT_SHA256

ROOT = Path(__file__).resolve().parents[1]


def example(visits=None, features=None):
    rows = {'subjects': [['DEMO-QUALITY', 'PRIVATE-CONSTRUCTED-ALIAS', 'ACTIVE']],
            'visits': visits if visits is not None else [['DEMO-QUALITY', 'BL', '2025-01-01', '0', '', '0.5'],
                                                       ['DEMO-QUALITY', 'M12', '2026-01-01', '27.25', '24.5', '1.5']],
            'features': features if features is not None else [['DEMO-QUALITY', 'APOE_E4_COUNT', '0', '2025-01-01', 'count'],
                                                              ['DEMO-QUALITY', 'MRI_HIPPOCAMPUS_L', '0.123456789', '2025-01-01', 'normalized'],
                                                              ['DEMO-QUALITY', 'MRI_HIPPOCAMPUS_R', '0.234567891', '2025-01-01', 'normalized']]}
    tables = {}
    for table, data in rows.items():
        output = io.StringIO(newline=''); writer = csv.writer(output, lineterminator='\n')
        writer.writerow(TABLES[table]); writer.writerows(data); tables[table] = output.getvalue()
    return {'input_mode': 'SYNTHETIC_TEST', 'dataVersion': 'demo-quality-review', 'predictionWindowMonths': 24, 'tables': tables}


def first(payload):
    return preview_quality(payload)['qualityReport']['subjects'][0]


class CourseQualityTests(unittest.TestCase):
    def test_original_preview_fields_exact_and_input_unchanged(self):
        payload = example(); original = copy.deepcopy(payload)
        result = preview_quality(payload)
        self.assertEqual({k: v for k, v in result.items() if k != 'qualityReport'}, preview_csv(payload))
        self.assertEqual(payload, original)
        self.assertEqual(result['qualityReport']['requestDigest'], result['requestDigest'])

    def test_zero_is_observed_missing_is_separate_and_fractional_course_values_accepted(self):
        row = first(example()); mmse, moca, _ = row['cognition']
        self.assertEqual((mmse['observedCount'], mmse['missingCount'], mmse['zeroCount']), (2, 0, 1))
        self.assertEqual((moca['observedCount'], moca['missingCount'], moca['zeroCount']), (1, 1, 0))
        self.assertEqual(row['qualityStatus'], 'PASS')
        self.assertEqual(row['featureCoverage'][0]['zeroCount'], 1)

    def test_observed_values_and_input_alias_not_returned(self):
        text = json.dumps(preview_quality(example()), ensure_ascii=False)
        for secret in ('PRIVATE-CONSTRUCTED-ALIAS', '27.25', '24.5', '0.123456789', '0.234567891'):
            self.assertNotIn(secret, text)

    def test_span_uses_declared_calendar_days(self):
        row = first(example())
        self.assertEqual(row['spanDays'], 365)
        self.assertEqual(row['indexDate'], '2026-01-01')
        self.assertIsNone(row['riskScore'])

    def test_recent_null_does_not_erase_earlier_non_null_feature(self):
        payload = example()
        payload['tables']['features'] += 'DEMO-QUALITY,MRI_HIPPOCAMPUS_L,,2026-01-01,normalized\n'
        feature = first(payload)['featureCoverage'][1]
        self.assertEqual((feature['observedCount'], feature['missingCount']), (1, 1))
        self.assertEqual(feature['selectedDate'], '2025-01-01')
        self.assertEqual(feature['selectedSources'], [{'table': 'features', 'row': 3, 'field': 'featureValue'}])

    def test_future_feature_excluded_from_selected_source_and_linked(self):
        payload = example(); payload['tables']['features'] += 'DEMO-QUALITY,APOE_E4_COUNT,2,2026-02-01,count\n'
        row = first(payload); feature = row['featureCoverage'][0]
        self.assertEqual((feature['eligibleRows'], feature['postIndexRows']), (1, 1))
        self.assertEqual(feature['selectedDate'], '2025-01-01')
        decision = next(d for d in row['decisions'] if d['code'] == 'POST_INDEX_FEATURES_EXCLUDED')
        self.assertEqual(decision['sources'], [{'table': 'features', 'row': 5, 'field': 'recordedAt'}])

    def test_no_index_date_keeps_features_unplaced_without_inventing_future_status(self):
        row = first(example(visits=[]))
        self.assertIsNone(row['spanDays']); self.assertIsNone(row['indexDate'])
        self.assertTrue(all(c['indexState'] == 'NO_VISIT' for c in row['cognition']))
        self.assertTrue(all(f['unplacedRows'] == 1 and f['postIndexRows'] == 0 and f['eligibleRows'] == 0 for f in row['featureCoverage']))

    def test_same_day_visit_ambiguity_not_arbitrarily_selected(self):
        payload = example(); payload['tables']['visits'] += 'DEMO-QUALITY,OTHER,2026-01-01,29,25,1\n'
        row = first(payload)
        self.assertEqual(row['qualityStatus'], 'BLOCKED'); self.assertEqual(row['sameDayVisitGroups'], 1)
        self.assertTrue(all(c['indexState'] == 'AMBIGUOUS' for c in row['cognition']))

    def test_same_day_equal_repeats_keep_all_physical_source_candidates(self):
        payload = example(); payload['tables']['features'] += 'DEMO-QUALITY,APOE_E4_COUNT,0,2025-01-01,count\n'
        row = first(payload); f = row['featureCoverage'][0]
        self.assertEqual(row['qualityStatus'], 'PASS')
        self.assertEqual((f['repeatedRows'], f['conflictingDays']), (1, 0))
        self.assertEqual([r['row'] for r in f['selectedSources']], [2, 5])
        self.assertIn('REPEATED_SAME_VALUE', [d['code'] for d in row['decisions']])

    def test_conflicting_values_do_not_claim_a_selected_source(self):
        payload = example(); payload['tables']['features'] += 'DEMO-QUALITY,APOE_E4_COUNT,1,2025-01-01,count\n'
        row = first(payload); f = row['featureCoverage'][0]
        self.assertEqual(row['qualityStatus'], 'BLOCKED'); self.assertEqual(f['conflictingDays'], 1)
        self.assertIsNone(f['selectedDate']); self.assertEqual(f['selectedSources'], [])
        decision = next(d for d in row['decisions'] if d['code'] == 'CONFLICTING_FEATURE_VALUES')
        self.assertEqual([r['row'] for r in decision['sources']], [2, 5])

    def test_missing_and_present_same_day_follow_original_conflict_rule(self):
        payload = example(); payload['tables']['features'] += 'DEMO-QUALITY,APOE_E4_COUNT,,2025-01-01,count\n'
        self.assertEqual(first(payload)['featureCoverage'][0]['conflictingDays'], 1)

    def test_physical_line_locators_survive_quoted_newline_and_bom(self):
        payload = example(visits=[['DEMO-QUALITY', 'B\nL', '2025-01-01', '28', '', '0'],
                                  ['DEMO-QUALITY', 'M12', '2026-01-01', '', '25', '1']])
        payload['tables']['visits'] = '\ufeff' + payload['tables']['visits']
        row = first(payload)
        self.assertEqual(row['cognition'][0]['missingSources'][0]['row'], 4)
        self.assertEqual(row['cognition'][1]['missingSources'][0]['row'], 2)

    def test_invalid_batch_never_generates_partial_subject_details(self):
        payload = example(); payload['tables']['features'] += 'DEMO-ORPHAN,APOE_E4_COUNT,1,2025-01-01,count\n'
        result = preview_quality(payload)
        self.assertEqual(result['status'], 'INVALID'); self.assertEqual(result['subjects'], [])
        self.assertEqual(result['qualityReport']['status'], 'NOT_EVALUATED')
        self.assertEqual(result['qualityReport']['subjects'], [])
        self.assertTrue(result['qualityReport']['fields'])

    def test_unsupported_window_preserves_quality_block_without_scoring(self):
        payload = example(); payload['predictionWindowMonths'] = 12
        with patch('python_service.deepagent_contract.run_workflow', side_effect=AssertionError('MODEL CALLED')):
            row = first(payload)
        self.assertEqual(row['qualityStatus'], 'BLOCKED')
        self.assertIn('UNSUPPORTED_WINDOW', [d['code'] for d in row['decisions']])

    def test_research_mode_and_resource_limits_still_rejected(self):
        for key, value in [('input_mode', 'REAL_RETROSPECTIVE_RESEARCH'), ('tables', {'subjects': 'x' * 40000, 'visits': '', 'features': ''})]:
            payload = example(); payload[key] = value
            with self.assertRaises(CsvPreviewError): preview_quality(payload)

    def test_dictionary_matches_frozen_course_ranges_and_all_csv_columns(self):
        dictionary = field_dictionary()
        self.assertEqual(dictionary['contractSha256'], FROZEN_CONTRACT_SHA256)
        self.assertEqual([(f['table'], f['field']) for f in dictionary['fields']], [(t, c) for t, cs in TABLES.items() for c in cs])
        for name, high in [('mmse', 30), ('moca', 30), ('cdrSb', 18)]:
            f = next(f for f in dictionary['fields'] if f['field'] == name)
            self.assertEqual((f['minimum'], f['maximum'], f['unit'], f['nullable']), (0, high, '分', True))
        self.assertIn('非Global CDR', next(f['label'] for f in dictionary['fields'] if f['field'] == 'cdrSb'))

    def test_report_never_certifies_availability_authenticity_or_prediction(self):
        quality = preview_quality(example())['qualityReport']
        for field in ('modelExecuted', 'persisted', 'predictionProduced', 'clinicalValidityAssessed', 'sourceAuthenticityVerified', 'historicalAvailabilityVerified'):
            self.assertIs(quality[field], False)
        for f in quality['subjects'][0]['featureCoverage']:
            self.assertIsNone(f['availableDate']); self.assertIs(f['historicalAvailabilityVerified'], False)

    def test_all_shipped_subjects_keep_original_preview_and_quality(self):
        payload = example()
        for table in TABLES:
            payload['tables'][table] = (ROOT/f'fixtures/{table}.synthetic.csv').read_text(encoding='utf-8')
        result = preview_quality(payload)
        self.assertEqual(len(result['qualityReport']['subjects']), 100)
        self.assertEqual({k: v for k, v in result.items() if k != 'qualityReport'}, preview_csv(payload))
        self.assertEqual([r['qualityStatus'] for r in result['qualityReport']['subjects']], ['PASS'] * 100)

    def test_replay_deterministic_and_independent_output_objects(self):
        a = preview_quality(example()); b = preview_quality(example())
        self.assertEqual(a, b)
        a['qualityReport']['fields'][0]['label'] = 'MUTATED'
        self.assertNotEqual(a, b); self.assertEqual(b, preview_quality(example()))

    def test_many_duplicate_sources_are_explicitly_truncated_for_decisions(self):
        payload = example(); payload['tables']['features'] += 'DEMO-QUALITY,APOE_E4_COUNT,0,2025-01-01,count\n' * 25
        d = next(d for d in first(payload)['decisions'] if d['code'] == 'REPEATED_SAME_VALUE')
        self.assertEqual(d['sourceCount'], 26); self.assertEqual(len(d['sources']), 20)
        self.assertTrue(d['sourcesTruncated'])

    def test_invalid_batch_has_actionable_guidance_without_repeating_raw_values(self):
        payload = example(); payload['tables']['features'] += 'DEMO-ORPHAN,APOE_E4_COUNT,1,2025-01-01,count\n'
        guidance = preview_quality(payload)['qualityReport']['issueGuidance']
        self.assertEqual(guidance, [{'code': 'SUBJECT_NOT_IN_BATCH', 'message': '访视或特征关联的档案不在本批档案表中。'}])

    def test_repeated_and_conflicting_observations_both_retain_source_evidence(self):
        payload = example(); payload['tables']['features'] += 'DEMO-QUALITY,APOE_E4_COUNT,0,2025-01-01,count\nDEMO-QUALITY,APOE_E4_COUNT,1,2025-01-01,count\n'
        row = first(payload)
        self.assertEqual(row['qualityStatus'], 'BLOCKED')
        d = next(d for d in row['decisions'] if d['code'] == 'REPEATED_SAME_VALUE')
        self.assertEqual([r['row'] for r in d['sources']], [2, 5])

    def test_absent_features_have_zero_denominators_and_unknown_source_date(self):
        row = first(example(features=[]))
        for feature in row['featureCoverage']:
            self.assertEqual((feature['totalRows'], feature['observedCount'], feature['missingCount']), (0, 0, 0))
            self.assertIsNone(feature['selectedDate']); self.assertEqual(feature['selectedSources'], [])
        self.assertEqual(row['qualityStatus'], 'WARN')

    def test_archived_status_does_not_invent_an_assessment_permission_rule(self):
        payload = example(); payload['tables']['subjects'] = payload['tables']['subjects'].replace('ACTIVE', 'ARCHIVED')
        self.assertEqual(first(payload)['qualityStatus'], 'PASS')
