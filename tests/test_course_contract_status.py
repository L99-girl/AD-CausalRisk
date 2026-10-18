import copy
import unittest
from python_service.course_contract_status import summarize_acceptance,REQUIRED_CHECKS,enhance_acceptance_asset

SOURCES={'constructed_source':'a'*64}


def record():
    return {'status':'PASSED','mode':'COURSE_SYNTHETIC','contract_version':'deepagent-v1','http_api_version':'course-agent-http-v1',
            'checks':sorted(REQUIRED_CHECKS)+['constructed-check-'+str(i) for i in range(22-len(REQUIRED_CHECKS))],
            'passed':22,'checked_at_utc':'2026-10-18T00:00:00+00:00','fixture_profiles':100,'repeated_early_rejections':32,
            'owned_server_fault_checks':True,'formal_schema_validated':True,'independent_schema_observations':354,
            'original_api_paths_and_fields_changed':False,'scoring_formula_changed':False,'research_or_private_records_read':False,
            'java_integration_validated':False,'new_fits':0,'source_sha256':dict(SOURCES)}


class ContractStatusTests(unittest.TestCase):
    def test_no_record_is_not_reported_as_passed(self):
        value=summarize_acceptance(None,SOURCES)
        self.assertEqual(value['status'],'NOT_RUN');self.assertIsNone(value['checks_passed'])

    def test_valid_record_matches_sources_without_probing_a_service(self):
        source=record();before=copy.deepcopy(source);value=summarize_acceptance(source,SOURCES)
        self.assertEqual(value['status'],'VERIFIED');self.assertEqual(value['checks_passed'],22)
        self.assertFalse(value['course_service_currently_probed']);self.assertFalse(value['clinical_validity_assessed'])
        self.assertEqual(source,before)

    def test_changed_source_is_stale_and_never_displays_old_pass_count(self):
        value=summarize_acceptance(record(),{'constructed_source':'b'*64})
        self.assertEqual(value['status'],'STALE');self.assertIsNone(value['checks_passed']);self.assertFalse(value['source_matches'])

    def test_incomplete_duplicate_or_wrong_scope_records_are_invalid(self):
        for changes in ({'passed':True},{'fixture_profiles':0},{'formal_schema_validated':False},
                        {'mode':'REAL'},{'java_integration_validated':True},{'new_fits':1},
                        {'checks':['duplicate']*22},{'checked_at_utc':'2026-10-18'}):
            source=record();source.update(changes)
            with self.subTest(changes=changes):self.assertEqual(summarize_acceptance(source,SOURCES)['status'],'INVALID')

    def test_arbitrary_raw_record_fields_are_not_exposed(self):
        source=record();source['raw_response']='CONSTRUCTED_SECRET_BODY'
        self.assertNotIn('CONSTRUCTED_SECRET',str(summarize_acceptance(source,SOURCES)))

    def test_optional_demo_controls_fail_if_original_anchor_changes(self):
        with self.assertRaises(ValueError):enhance_acceptance_asset('index.html','changed')
        html=enhance_acceptance_asset('index.html','<div id="evidence-cards" class="evidence-grid"></div>')
        self.assertIn('aria-live="polite"',html);self.assertIn('重新读取记录',html)


if __name__=='__main__':unittest.main()
