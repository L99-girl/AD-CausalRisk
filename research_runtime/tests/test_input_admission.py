"""Constructed declaration and independently held context checks; no fitting."""
from copy import deepcopy
from datetime import date, timedelta
import json
import unittest

from research_runtime.input_admission import (
    AdmissionError, FEATURES, UNITS, validate_snapshot, validate_json, mapping_digest,
)
from research_runtime.examples.input_admission_constructed import constructed_pair


def item(request, name):
    return request['records'][0]['features'][name]


def attest(request, context, name):
    value = item(request, name)
    context['evidence'][value['evidenceRef']]['observation'] = deepcopy(value)


def remap(request, context):
    digest = mapping_digest(context['sourceMappings'])
    context['model']['sourceMappingSha256'] = digest
    request['model']['sourceMappingSha256'] = digest


def missing(request, name, reason='UNKNOWN', context=None):
    item(request, name).update(value=None, measuredDate=None, availableDate=None,
        dateBasis='UNKNOWN', sourceRef=None, qc='FAIL' if reason == 'QC_FAILED' else 'UNKNOWN',
        completion='UNKNOWN', missingReason=reason, scanId=None, evidenceRef=None)
    if context is not None:
        observation=item(request,name)
        observation['evidenceRef']='CONSTRUCTED-MISSING-'+name
        context['evidence'][observation['evidenceRef']]=dict(subjectCode=request['records'][0]['subjectCode'],
            feature=name,observation=deepcopy(observation))


def codes(result):
    return {row['code'] for row in result['issues']}


class InputAdmissionTests(unittest.TestCase):
    def test_constructed_final_model_matrix_and_never_grants_prediction(self):
        combinations = [('multimodal_values', 'prior_graph')]
        combinations += [(s, f) for s in ('seven', 'multimodal_values')
                         for f in ('logistic', 'random_forest', 'xgboost')]
        for spec, family in combinations:
            request, context = constructed_pair(spec, family)
            original = deepcopy((request, context))
            result = validate_snapshot(request, trusted_context=context)
            self.assertEqual(result['status'], 'METADATA_CONSISTENT')
            self.assertFalse(any(result[k] for k in ('predictionAllowed', 'clinicalUse',
                'sourceAuthenticityCertified', 'historicalAvailabilityCertified', 'individualCausalEffectIdentified')))
            self.assertEqual((request, context), original)
            self.assertEqual(result['featureOrder'], list(FEATURES[:7] if spec == 'seven' else FEATURES))

    def test_each_identity_hash_is_pinned_independently(self):
        for key in ('manifestSha256', 'artifactSha256', 'trainingPlanSha256',
                    'runtimeSourceSha256', 'softwareLockSha256', 'sourceMappingSha256', 'graphProtocolSha256'):
            request, context = constructed_pair(); request['model'][key] = '0'*64
            result = validate_snapshot(request, trusted_context=context)
            self.assertEqual(result['status'], 'BLOCKED')
            self.assertIn('REQUEST_CONTEXT_BINDING_MISMATCH', codes(result))

    def test_foreign_final_family_does_not_select_a_model(self):
        request, context = constructed_pair('multimodal_values', 'logistic')
        request['model']['family'] = 'random_forest'
        self.assertEqual(validate_snapshot(request, trusted_context=context)['status'], 'BLOCKED')

    def test_outer_calibrated_and_wrong_feature_order_rejected(self):
        for key, value in [('role', 'GRAPH_OUTER_VALIDATION'), ('features', list(reversed(FEATURES))),
                           ('predictionPolicy', 'calibrated'), ('family', 'auto')]:
            request, context = constructed_pair(); request['model'][key] = value
            with self.assertRaises(AdmissionError): validate_snapshot(request, trusted_context=context)

    def test_index_version_and_policy_cannot_be_downgraded_by_request(self):
        for key,value in [('indexDate', '2021-01-02'), ('dataVersion', 'other-snapshot'),
                          ('availabilityPolicy', 'AS_OF_INDEX')]:
            request, context = constructed_pair(); request[key] = value
            self.assertIn('REQUEST_CONTEXT_BINDING_MISMATCH', codes(validate_snapshot(request, trusted_context=context)))

    def test_mapping_change_requires_pinned_revision(self):
        request, context = constructed_pair(); context['sourceMappings']['mmse']['release'] = 'other-release'
        with self.assertRaisesRegex(AdmissionError, '^CONTEXT_MAPPING_HASH$'):
            validate_snapshot(request, trusted_context=context)
        context['model']['sourceMappingSha256'] = mapping_digest(context['sourceMappings'])
        self.assertEqual(validate_snapshot(request, trusted_context=context)['status'], 'BLOCKED')

    def test_generic_source_catalog_cannot_supply_record_evidence(self):
        request, context = constructed_pair(); context['evidence'] = {}
        result = validate_snapshot(request, trusted_context=context)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIn('RECORD_EVIDENCE_MISMATCH', codes(result))
        for obs in request['records'][0]['features'].values(): obs['evidenceRef'] = None
        self.assertIn('RECORD_EVIDENCE_UNKNOWN', codes(validate_snapshot(request, trusted_context=context)))

    def test_record_evidence_binds_subject_feature_value_dates_quality_and_scan(self):
        mutations = [('subjectCode', 'CONSTRUCTED-OTHER'), ('feature', 'faq__faqtotal')]
        for key, value in mutations:
            request, context = constructed_pair()
            context['evidence'][item(request,'mmse')['evidenceRef']][key] = value
            self.assertEqual(validate_snapshot(request, trusted_context=context)['status'], 'BLOCKED')
        request, context = constructed_pair()
        context['evidence'][item(request,'mmse')['evidenceRef']]['feature'] = 'education_years'
        with self.assertRaisesRegex(AdmissionError, '^FEATURE_UNIT$'):
            validate_snapshot(request, trusted_context=context)
        for key,value in [('value', 27), ('measuredDate', '2019-12-31'), ('availableDate', '2020-01-01'),
                          ('qc', 'UNKNOWN'), ('completion', 'UNKNOWN'), ('sourceRef', 'CONSTRUCTED-FOREIGN')]:
            request, context = constructed_pair(); item(request,'mmse')[key] = value
            self.assertIn('RECORD_EVIDENCE_MISMATCH', codes(validate_snapshot(request, trusted_context=context)))

    def test_unknown_quality_is_a_blocker_not_fabricated_pass_or_parse_error(self):
        for key, value, expected in [('qc', 'UNKNOWN', 'QC_UNKNOWN'), ('qc', 'FAIL', 'QC_FAIL'),
                                      ('completion', 'UNKNOWN', 'COMPLETION_UNKNOWN'),
                                      ('completion', 'INCOMPLETE', 'COMPLETION_INCOMPLETE')]:
            request, context = constructed_pair(); item(request,'mmse')[key] = value; attest(request,context,'mmse')
            result = validate_snapshot(request, trusted_context=context)
            self.assertEqual(result['status'], 'BLOCKED'); self.assertIn(expected, codes(result))
            self.assertNotIn('RECORD_EVIDENCE_MISMATCH', codes(result))

    def test_unknown_language_version_release_or_processing_remains_blocked(self):
        for name,key in [('mmse','language'), ('mmse','instrumentVersion'), ('mmse','release'),
                         (FEATURES[8],'processingVersion')]:
            request,context=constructed_pair(); context['sourceMappings'][name][key]=None;remap(request,context)
            self.assertIn('SOURCE_METADATA_UNKNOWN', codes(validate_snapshot(request,trusted_context=context)))

    def test_retrospective_unknown_and_late_availability_are_warnings(self):
        for available, expected in [(None,'AVAILABILITY_UNKNOWN'), ('2020-01-03','POST_INDEX_AVAILABILITY')]:
            request,context=constructed_pair();item(request,'mmse')['availableDate']=available;attest(request,context,'mmse')
            result=validate_snapshot(request,trusted_context=context)
            self.assertEqual(result['status'],'METADATA_CONSISTENT');self.assertIn(expected,codes(result))
            request['availabilityPolicy']=context['availabilityPolicy']='AS_OF_INDEX'
            self.assertEqual(validate_snapshot(request,trusted_context=context)['status'],'BLOCKED')

    def test_registry_proxy_is_not_promoted_to_measurement_date(self):
        request,context=constructed_pair();item(request,'mmse')['dateBasis']='REGISTRY_PROXY';attest(request,context,'mmse')
        self.assertEqual(validate_snapshot(request,trusted_context=context)['status'],'METADATA_CONSISTENT')
        request['availabilityPolicy']=context['availabilityPolicy']='AS_OF_INDEX'
        self.assertIn('REGISTRY_DATE_PROXY',codes(validate_snapshot(request,trusted_context=context)))
        self.assertEqual(item(request,'mmse')['dateBasis'],'REGISTRY_PROXY')

    def test_unknown_measurement_post_index_and_impossible_order_block(self):
        for changes,expected in [({'measuredDate':None,'dateBasis':'UNKNOWN'},'MEASUREMENT_DATE_UNKNOWN'),
                                  ({'measuredDate':'2020-01-03','availableDate':'2020-01-04'},'POST_INDEX_MEASUREMENT'),
                                  ({'availableDate':'2019-12-31'},'SOURCE_DATE_ORDER')]:
            request,context=constructed_pair();item(request,'mmse').update(changes);attest(request,context,'mmse')
            self.assertIn(expected,codes(validate_snapshot(request,trusted_context=context)))

    def test_age_derived_at_index_has_explicit_scope(self):
        request,context=constructed_pair();item(request,'age_years').update(dateBasis='DERIVED_AT_INDEX',measuredDate=request['indexDate']);attest(request,context,'age_years')
        self.assertEqual(validate_snapshot(request,trusted_context=context)['status'],'METADATA_CONSISTENT')
        item(request,'mmse')['dateBasis']='DERIVED_AT_INDEX';attest(request,context,'mmse')
        self.assertIn('DERIVED_DATE_SCOPE',codes(validate_snapshot(request,trusted_context=context)))

    def test_missing_masks_are_counted_without_imputation_or_dropping(self):
        request,context=constructed_pair();missing(request,'mmse',context=context);missing(request,FEATURES[8],context=context);missing(request,FEATURES[9],context=context)
        before=deepcopy((request,context));result=validate_snapshot(request,trusted_context=context)
        self.assertEqual(result['status'],'METADATA_CONSISTENT');self.assertEqual(result['missingFeatureCounts']['mmse'],1)
        self.assertEqual(result['recordCount'],1);self.assertEqual((request,context),before)
        for name in FEATURES[:7]:missing(request,name)
        self.assertIn('NO_CORE_INPUT',codes(validate_snapshot(request,trusted_context=context)))

    def test_missing_reason_dates_and_completion_are_not_silently_repaired(self):
        for changes in ({'missingReason':None},{'measuredDate':'2020-01-01'}, {'completion':'COMPLETE'},
                        {'qc':'PASS'},{'missingReason':'QC_FAILED','qc':'UNKNOWN'}):
            request,context=constructed_pair();missing(request,'mmse');item(request,'mmse').update(changes)
            with self.assertRaises(AdmissionError):validate_snapshot(request,trusted_context=context)
        request,context=constructed_pair();missing(request,'mmse','QC_FAILED',context=context)
        self.assertEqual(validate_snapshot(request,trusted_context=context)['status'],'METADATA_CONSISTENT')

    def test_nulling_an_unknown_quality_observation_cannot_bypass_evidence(self):
        request,context=constructed_pair();item(request,'mmse')['qc']='UNKNOWN';attest(request,context,'mmse')
        self.assertIn('QC_UNKNOWN',codes(validate_snapshot(request,trusted_context=context)))
        old_ref=item(request,'mmse')['evidenceRef'];missing(request,'mmse')
        self.assertIn('MISSING_EVIDENCE_UNKNOWN',codes(validate_snapshot(request,trusted_context=context)))
        item(request,'mmse')['evidenceRef']=old_ref
        self.assertIn('RECORD_EVIDENCE_MISMATCH',codes(validate_snapshot(request,trusted_context=context)))

    def test_bilateral_scan_dates_processing_and_window(self):
        request,context=constructed_pair();missing(request,FEATURES[8])
        self.assertIn('BILATERAL_MRI_PAIR_REQUIRED',codes(validate_snapshot(request,trusted_context=context)))
        for key,value in [('scanId','CONSTRUCTED-OTHER-SCAN'),('measuredDate','2019-12-31'),
                          ('availableDate',None),('dateBasis','REGISTRY_PROXY')]:
            request,context=constructed_pair();item(request,FEATURES[9])[key]=value;attest(request,context,FEATURES[9])
            self.assertIn('SAME_SCAN_AND_PROCESSING_REQUIRED',codes(validate_snapshot(request,trusted_context=context)))
        request,context=constructed_pair();context['sourceMappings'][FEATURES[9]]['processingVersion']='different-version';remap(request,context)
        self.assertIn('SAME_SCAN_AND_PROCESSING_REQUIRED',codes(validate_snapshot(request,trusted_context=context)))
        for days in (365,366):
            request,context=constructed_pair()
            for name in FEATURES[8:]:
                item(request,name)['measuredDate']=(date.fromisoformat(request['indexDate'])-timedelta(days=days)).isoformat();attest(request,context,name)
            result=validate_snapshot(request,trusted_context=context)
            self.assertEqual(result['status'],'METADATA_CONSISTENT' if days==365 else 'BLOCKED')

    def test_exact_units_features_and_no_outcome_input(self):
        for mutate in (lambda q:q.update(event_type=1),lambda q:q['records'][0]['features'].pop('mmse'),
                       lambda q:item(q,FEATURES[8]).update(unit='cm3'),lambda q:q.update(predictionWindowMonths=True)):
            request,context=constructed_pair();mutate(request)
            with self.assertRaises(AdmissionError):validate_snapshot(request,trusted_context=context)

    def test_numeric_types_and_apoe_mri_boundaries(self):
        for name,value in [('mmse',True),('mmse',float('nan')),('mmse',float('inf')),('mmse','26'),
                           ('apoe4_count',1.0),('apoe4_count',3),('apoe4_count',-1),(FEATURES[8],0),(FEATURES[8],-1)]:
            request,context=constructed_pair();item(request,name)['value']=value
            with self.assertRaises(AdmissionError):validate_snapshot(request,trusted_context=context)

    def test_batch_failure_preserves_denominator_and_aggregate_privacy(self):
        request,context=constructed_pair();other=deepcopy(request['records'][0]);other['subjectCode']='CONSTRUCTED-SECRET-002'
        for name,obs in other['features'].items():
            obs['evidenceRef']+='-other';context['evidence'][obs['evidenceRef']]=dict(subjectCode=other['subjectCode'],feature=name,observation=deepcopy(obs))
        other['features']['mmse']['qc']='UNKNOWN';context['evidence'][other['features']['mmse']['evidenceRef']]['observation']['qc']='UNKNOWN'
        request['records'].append(other)
        result=validate_snapshot(request,trusted_context=context);self.assertEqual((result['recordCount'],result['blockedRecordCount']),(2,1))
        encoded=json.dumps(result)
        for secret in ('CONSTRUCTED-SECRET','subjectCode','evidenceRef','scanId','observed_month','ad_cif_24m'):
            self.assertNotIn(secret,encoded)

    def test_errors_do_not_echo_inputs_and_requests_are_bounded(self):
        request,context=constructed_pair();request['indexDate']='CONSTRUCTED-PRIVATE-INVALID-DATE'
        with self.assertRaises(AdmissionError) as caught:validate_snapshot(request,trusted_context=context)
        self.assertEqual(str(caught.exception),'DATE_FORMAT');self.assertIsNone(caught.exception.__cause__)
        for records in ([],[{}]*101):
            request,context=constructed_pair();request['records']=records
            with self.assertRaisesRegex(AdmissionError,'RECORD_COUNT'):validate_snapshot(request,trusted_context=context)
        request,context=constructed_pair();request['extra']='x'*131072
        with self.assertRaisesRegex(AdmissionError,'REQUEST_TOO_LARGE'):validate_snapshot(request,trusted_context=context)

    def test_duplicate_json_numbers_encoding_and_deep_payloads_rejected(self):
        request,context=constructed_pair();raw=json.dumps(request).encode()
        self.assertEqual(validate_json(raw,trusted_context=context),validate_snapshot(request,trusted_context=context))
        invalid=[b'{"a":1,"a":2}',b'{"a":{"x":1,"x":2}}',b'{"x":NaN}',b'{"x":Infinity}',
                 b'{"x":1e999}',b'\xff',b'\xef\xbb\xbf'+raw,b'['*2000+b']'*2000,b'x'*131073]
        for payload in invalid:
            with self.assertRaises(AdmissionError):validate_json(payload,trusted_context=context)

    def test_matched_context_is_not_an_authenticity_or_access_certificate(self):
        request,context=constructed_pair();item(request,'mmse')['value']=27;attest(request,context,'mmse')
        result=validate_snapshot(request,trusted_context=context)
        self.assertEqual(result['status'],'METADATA_CONSISTENT')
        self.assertFalse(result['sourceAuthenticityCertified']);self.assertFalse(result['predictionAllowed'])

    def test_no_file_loader_or_predictor_is_exposed(self):
        import ast
        from pathlib import Path
        import research_runtime.input_admission as module
        tree=ast.parse(Path(module.__file__).read_text(encoding='utf-8'))
        calls={n.func.id for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
        self.assertFalse(calls & {'open','predict_cif','load_final_model','eval','exec','compile','__import__'})


if __name__ == '__main__':
    unittest.main()
