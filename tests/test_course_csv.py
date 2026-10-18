import copy
import csv
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from python_service.course_csv import preview_csv, prepare_csv, quality_summary, CsvPreviewError, TABLES
from python_service.deepagent_contract import run_workflow
from python_service.demo_scoring import score_java_synthetic_payload as assess_python_request

ROOT = Path(__file__).resolve().parents[1]


def sample():
    tables = {}
    for table in TABLES:
        with (ROOT / f'fixtures/{table}.synthetic.csv').open(encoding='utf-8', newline='') as stream:
            rows = list(csv.reader(stream))
        selected = [rows[0]] + [row for row in rows[1:] if row[0] == 'DEMO-001']
        output = io.StringIO(newline=''); csv.writer(output, lineterminator='\n').writerows(selected)
        tables[table] = output.getvalue()
    return {'input_mode': 'SYNTHETIC_TEST', 'dataVersion': 'demo-csv-check', 'predictionWindowMonths': 24, 'tables': tables}


class CourseCsvTests(unittest.TestCase):
    def mutate(self, table, old, new):
        payload = sample(); self.assertIn(old, payload['tables'][table])
        payload['tables'][table] = payload['tables'][table].replace(old, new)
        return payload

    def assert_issue(self, payload, code, table=None, row=None, field=None):
        report, requests = prepare_csv(payload)
        self.assertEqual(report['status'], 'INVALID'); self.assertFalse(requests); self.assertFalse(report['subjects'])
        matches = [issue for issue in report['issues'] if issue['code'] == code]
        self.assertTrue(matches, report)
        if table:self.assertEqual(matches[0]['table'], table)
        if row:self.assertEqual(matches[0]['row'], row)
        if field:self.assertEqual(matches[0]['field'], field)
        return report

    def parity(self, payload):
        report, requests = prepare_csv(payload); self.assertEqual(report['status'], 'PREVIEW_ONLY')
        for request, quality in zip(sorted(requests, key=lambda item:item['subjectCode']), report['subjects']):
            result = run_workflow(request, assess_python_request)
            self.assertEqual(quality['qualityStatus'], result['qualityStatus'])
            self.assertEqual(sorted(quality['missingModalities']), sorted(result['missingModalities']))
            self.assertEqual(quality['indexDate'], result['stages'][0]['summary']['indexDate'])
            self.assertEqual(quality['excludedPostIndexFeatures'], result['stages'][0]['summary']['excludedPostIndexFeatures'])
            self.assertIsNone(quality['riskScore']); self.assertFalse(quality['predictionProduced'])
        return report

    def test_all_shipped_tables_link_and_preserve_typed_requests(self):
        payload = sample()
        for table in TABLES:payload['tables'][table] = (ROOT / f'fixtures/{table}.synthetic.csv').read_text(encoding='utf-8')
        report = self.parity(payload)
        self.assertEqual(report['rows'], {'subjects':100, 'visits':200, 'features':300})
        self.assertEqual(report['qualityCounts'], {'PASS':100, 'WARN':0, 'BLOCKED':0})

    def test_preview_never_executes_scoring_or_returns_raw_alias(self):
        with patch('python_service.demo_scoring.score_java_synthetic_payload', side_effect=AssertionError('SCORING_FORBIDDEN')):
            report = preview_csv(sample())
        text = json.dumps(report, ensure_ascii=False)
        self.assertNotIn('合成档案001', text)
        for key in ('persisted','modelExecuted','predictionProduced','commitSupported','clinicalValidityAssessed'):
            self.assertIs(report[key], False)

    def test_digest_exact_replay_and_immutable_input(self):
        payload = sample(); before = copy.deepcopy(payload); first = preview_csv(payload)
        self.assertEqual(first, preview_csv(payload)); self.assertEqual(payload, before)
        payload['dataVersion'] = 'demo-new'
        self.assertNotEqual(first['requestDigest'], preview_csv(payload)['requestDigest'])

    def test_mode_version_window_and_exact_fields_rejected(self):
        for key, value in [('input_mode','REAL'),('dataVersion','adni-real'),('predictionWindowMonths',True),('predictionWindowMonths',5),('predictionWindowMonths',24.0),('extra',None)]:
            with self.subTest(key=key,value=value), self.assertRaises(CsvPreviewError):
                payload=sample();payload[key]=value;preview_csv(payload)

    def test_missing_table_unknown_table_and_size_rejected(self):
        for change in ('missing','extra','size','surrogate'):
            with self.subTest(change=change), self.assertRaises(CsvPreviewError):
                payload=sample()
                if change=='missing':del payload['tables']['features']
                elif change=='extra':payload['tables']['other']='x'
                elif change=='size':payload['tables']['subjects']='x'*30001
                else:payload['tables']['subjects']='\ud800'
                preview_csv(payload)

    def test_reordered_or_duplicate_header_is_not_guessed(self):
        for header in ('alias,subjectCode,status','subjectCode,subjectCode,status'):
            self.assert_issue(self.mutate('subjects','subjectCode,alias,status',header),'HEADER_EXACT_REQUIRED','subjects',1)

    def test_bom_crlf_and_quoted_multiline_alias(self):
        payload=sample();payload['tables']['subjects']='\ufeffsubjectCode,alias,status\r\nDEMO-001,"构造,档案\r\n第二行",ACTIVE\r\n'
        self.parity(payload)

    def test_multiline_following_error_has_physical_start_line(self):
        payload=sample();payload['tables']['subjects']='subjectCode,alias,status\rDEMO-001,"构造\r换行",ACTIVE\rNOT-DEMO,alias,ACTIVE\r'
        self.assert_issue(payload,'SYNTHETIC_ALIAS_REQUIRED','subjects',4,'subjectCode')

    def test_csv_syntax_and_column_count(self):
        self.assert_issue(self.mutate('subjects','合成档案001','"unclosed'),'CSV_SYNTAX')
        self.assert_issue(self.mutate('subjects',',ACTIVE',',ACTIVE,extra'),'COLUMN_COUNT','subjects',2)

    def test_no_subjects_is_invalid_but_no_visits_quality_blocks(self):
        payload=sample();payload['tables']['subjects']='subjectCode,alias,status\n'
        self.assert_issue(payload,'SUBJECTS_REQUIRED')
        payload=sample();payload['tables']['visits']=','.join(TABLES['visits'])+'\n'
        self.assertEqual(self.parity(payload)['qualityCounts']['BLOCKED'],1)

    def test_orphan_and_duplicate_subject_or_visit(self):
        self.assert_issue(self.mutate('features','DEMO-001','DEMO-999'),'SUBJECT_NOT_IN_BATCH','features',2)
        payload=sample();payload['tables']['subjects'] += 'DEMO-001,duplicate,ACTIVE\n';self.assert_issue(payload,'DUPLICATE_SUBJECT')
        payload=sample();payload['tables']['visits'] += payload['tables']['visits'].splitlines()[1]+'\n';self.assert_issue(payload,'DUPLICATE_SUBJECT_VISIT')

    def test_unknown_features_units_and_archived_metadata(self):
        self.assert_issue(self.mutate('features','APOE_E4_COUNT','UNKNOWN'),'FEATURE_NOT_ALLOWED')
        self.assert_issue(self.mutate('features','normalized','mm3'),'UNIT_MISMATCH','features',3,'unit')
        self.assertEqual(self.parity(self.mutate('subjects','ACTIVE','ARCHIVED'))['qualityCounts']['PASS'],1)
        self.assert_issue(self.mutate('subjects','ACTIVE','DELETED'),'SUBJECT_STATUS')

    def test_dates_are_calendar_valid_and_never_in_future(self):
        for raw in ('2025-02-30','9999-01-01','20250101',''):
            self.assert_issue(self.mutate('visits','2025-01-01',raw),'DATE_INVALID_OR_FUTURE','visits',2,'visitDate')

    def test_nonfinite_ranges_boolean_text_and_null_token_rejected(self):
        for raw in ('NaN','inf','1e999','31','-1','true','null',' 25'):
            self.assert_issue(self.mutate('visits',',28,',','+raw+','),'NUMBER_INVALID_OR_RANGE')

    def test_cognition_fraction_retains_original_course_range(self):
        payload=self.mutate('visits',',28,',',27.25,');self.parity(payload)
        _,requests=prepare_csv(payload);self.assertEqual(requests[0]['visits'][0]['mmse'],27.25)

    def test_apoe_integer_token_and_zero_retained(self):
        for raw in ('1.0','1e0','-1','3'):
            self.assert_issue(self.mutate('features',',1,2025',','+raw+',2025'),'NUMBER_INVALID_OR_RANGE')
        payload=self.mutate('features',',1,2025',',0,2025');self.parity(payload)
        _,requests=prepare_csv(payload);self.assertIs(type(requests[0]['features'][0]['featureValue']),int)

    def test_empty_numeric_missing_and_zero_are_distinct(self):
        payload=self.mutate('visits',',25,22,1.5',',0,,')
        report=self.parity(payload);self.assertEqual(report['qualityCounts']['WARN'],1)
        _,requests=prepare_csv(payload);self.assertEqual(requests[0]['visits'][1]['mmse'],0)
        self.assertIsNone(requests[0]['visits'][1]['moca'])

    def test_missing_core_and_unsupported_window_block_without_score(self):
        payload=self.mutate('visits',',25,22,1.5',',,,');self.assertEqual(self.parity(payload)['qualityCounts']['BLOCKED'],1)
        payload=sample();payload['predictionWindowMonths']=12;self.assertEqual(self.parity(payload)['qualityCounts']['BLOCKED'],1)

    def test_ambiguous_index_and_conflict_block_but_exact_duplicate_warn_only(self):
        payload=sample();payload['tables']['visits']+='DEMO-001,OTHER,2026-01-01,25,22,1.5\n';self.assertEqual(self.parity(payload)['qualityCounts']['BLOCKED'],1)
        payload=sample();payload['tables']['features']+='DEMO-001,APOE_E4_COUNT,2,2025-01-01,count\n';self.assertEqual(self.parity(payload)['qualityCounts']['BLOCKED'],1)
        payload=sample();payload['tables']['features']+='DEMO-001,APOE_E4_COUNT,1,2025-01-01,count\n';report=self.parity(payload)
        self.assertEqual(report['qualityCounts']['PASS'],1);self.assertEqual(report['issues'][0]['severity'],'WARN')

    def test_post_index_features_and_latest_null_use_original_semantics(self):
        payload=sample();payload['tables']['features']+='DEMO-001,APOE_E4_COUNT,2,2026-02-01,count\nDEMO-001,APOE_E4_COUNT,,2026-01-01,count\n'
        report=self.parity(payload);self.assertEqual(report['subjects'][0]['excludedPostIndexFeatures'],1)
        self.assertEqual(report['qualityCounts']['WARN'],1)

    def test_row_limit_and_per_subject_limit(self):
        payload=sample();payload['tables']['subjects']='subjectCode,alias,status\n'+''.join(f'DEMO-{i},x,ACTIVE\n' for i in range(201))
        self.assert_issue(payload,'ROW_LIMIT')
        payload=sample();payload['tables']['visits']=','.join(TABLES['visits'])+'\n'+''.join(f'DEMO-001,V{i},2025-01-01,27,25,0.5\n' for i in range(101))
        self.assert_issue(payload,'SUBJECT_RECORD_LIMIT')

    def test_issue_cap_preserves_invalid_and_total_not_partial_success(self):
        payload=sample();payload['tables']['visits']=','.join(TABLES['visits'])+'\n'+('BAD,B,2025-02-30,NaN,true,-1\n'*100)
        report=self.assert_issue(payload,'SYNTHETIC_ALIAS_REQUIRED')
        self.assertEqual(len(report['issues']),200);self.assertTrue(report['issuesTruncated']);self.assertGreater(report['errorCount'],200)

    def test_nul_and_blank_physical_record_rejected(self):
        self.assert_issue(self.mutate('subjects','合成档案001','\x00'),'NUL_CHARACTER')
        payload=sample();payload['tables']['visits']+='\n';self.assert_issue(payload,'COLUMN_COUNT')

    def test_quality_summary_matches_all_existing_json_profiles(self):
        rows=json.loads((ROOT/'fixtures/synthetic_subjects_100.json').read_text(encoding='utf-8'))['subjects']
        for profile in rows:
            # Fixture top-level shape is checked by the existing contract suite.
            payload={'contractVersion':'deepagent-v1','modelVersion':'deepagent-causal-warning-v1','runId':'run-quality-'+profile['subjectCode'],
                     'subjectCode':profile['subjectCode'],'dataVersion':'demo-csv-parity','predictionWindowMonths':24,'visits':profile['visits'],'features':profile['features']}
            quality=quality_summary(payload);result=run_workflow(payload,assess_python_request)
            self.assertEqual(quality['qualityStatus'],result['qualityStatus'])
