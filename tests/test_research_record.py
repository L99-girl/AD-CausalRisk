import copy
import importlib.util
import json
from pathlib import Path
import unittest
from python_service.research_record import build_research_record, ResearchRecordError, STAGES, digest

spec=importlib.util.spec_from_file_location('constructed_client_fixture',Path(__file__).with_name('test_workbench_client.py'))
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
PIN='a'*64


def result():
    value=fixture.result();core=value['core']
    value['qualification'].update(index_date='2021-02-11',historical_availability_verified=False,future_outcomes_used_as_features=False)
    value.update(training_membership='NOT_REVERIFIED_POSSIBLE_DEVELOPMENT_RECORD',source_bindings={'constructed_source':{'sha256':'b'*64}})
    core.update(modelArtifactSha256=PIN,qualityStatus='PASS',missingInputs=[],stages=[{'stage':name} for name in STAGES],
                graph={'nodes':[{'id':'mmse','feature':'mmse','value':27,'unit':'score','source_table':'CONSTRUCTED',
                                 'source_visit':'constructed-visit','measurement_date':'2021-01-01','days_before_landmark':41}],
                       'derived_nodes':[],'current_feature_nodes':{'mmse':'mmse'},'chronological_edges':[],
                       'interaction_edges':[{'endpoints':['mmse','cdr_sb'],'node_endpoints':['mmse',None],'active':False,'causal_effect_identified':False}]})
    return value


def build(value):return build_research_record(value,expected_alias=fixture.ALIAS,expected_model_sha256=PIN)


class ResearchRecordTests(unittest.TestCase):
    def test_cifs_and_contributions_preserve_exact_original_numbers(self):
        source=result();record=build(source)
        self.assertEqual(record['probabilities']['adCif'],source['core']['adCumulativeIncidence'])
        self.assertEqual(record['probabilities']['otherDementiaCif'],.1)
        self.assertEqual(record['attribution']['contributions'],source['core']['explanation']['contributions'])
        self.assertEqual(record['probabilities']['unit'],'proportion');self.assertNotIn('riskScore',record)

    def test_unknown_availability_membership_uncertainty_and_timing_remain_unknown(self):
        record=build(result())
        self.assertIsNone(record['sourceNodes'][0]['availableDate'])
        self.assertIsNone(record['boundaries']['outOfSample'])
        self.assertIsNone(record['boundaries']['individualPredictionInterval'])
        self.assertTrue(all(stage['durationMs'] is None for stage in record['stages']))
        self.assertFalse(record['boundaries']['exportAllowed']);self.assertFalse(record['boundaries']['clinicalUseEstablished'])

    def test_immutable_whitelist_drops_arbitrary_private_fields(self):
        source=result();source['diagnostic_history']={'private':'do-not-copy'}
        source['core']['explanation']['contributions'][0]['raw_record']='do-not-copy'
        source['core']['graph']['nodes'][0]['raw_record']='do-not-copy'
        source['source_bindings']['constructed_source']['path']='do-not-copy'
        before=copy.deepcopy(source);record=build(source)
        self.assertNotIn('do-not-copy',str(record));self.assertEqual(source,before)
        record['sourceNodes'][0]['value']=0;self.assertEqual(source,before)

    def test_digest_is_deterministic_and_detects_field_change(self):
        record=build(result());self.assertEqual(record,build(result()))
        expected=record.pop('recordSha256');self.assertEqual(digest(record),expected)
        record['sourceNodes'][0]['value']=28;self.assertNotEqual(digest(record),expected)

    def test_independent_model_pin_is_required_and_mismatch_fails(self):
        for pin in (None,'', 'not-a-sha', 'c'*64):
            with self.assertRaises(ResearchRecordError):build_research_record(result(),expected_alias=fixture.ALIAS,expected_model_sha256=pin)

    def test_wrong_identity_synthetic_mode_and_clinical_claims_are_rejected(self):
        for changes in ({'alias':'ADNI-R-WRONG'},{'mode':'SYNTHETIC_TEST'},{'clinical_use_established':True},{'export_allowed':True}):
            source=result();source.update(changes)
            with self.assertRaises(ResearchRecordError):build(source)

    def test_probability_and_attribution_corruption_are_rejected(self):
        for key,value in (('adCumulativeIncidence',float('nan')),('otherDementiaCumulativeIncidence',.9)):
            source=result();source['core'][key]=value
            with self.assertRaises(ResearchRecordError):build(source)
        source=result();source['core']['explanation']['baseline']=.11
        with self.assertRaises(ResearchRecordError):build(source)

    def test_units_discrete_scores_and_source_chronology_are_enforced(self):
        for changes in ({'unit':'percent'},{'value':27.25},{'value':True},{'days_before_landmark':40},
                        {'measurement_date':'2022-01-01'},{'measurement_date':'20210101'},{'source_visit':'DEMO-1'}):
            source=result();source['core']['graph']['nodes'][0].update(changes)
            with self.assertRaises(ResearchRecordError):build(source)

    def test_missing_or_duplicate_source_links_are_rejected(self):
        for mutate in (lambda source:source['availability'].update(extra=None),
                       lambda source:source['core']['graph']['nodes'].append(copy.deepcopy(source['core']['graph']['nodes'][0])),
                       lambda source:source.update(source_bindings={})):
            source=result();mutate(source)
            with self.assertRaises(ResearchRecordError):build(source)

    def test_stage_progress_and_quality_are_not_fabricated(self):
        for changes in ({'stages':[]},{'stages':[{'stage':'FAKE'}]},{'qualityStatus':'BLOCKED'},{'missingInputs':['mmse']},
                        {'missingInputs':['mmse','mmse'],'qualityStatus':'WARN'}):
            source=result();source['core'].update(changes)
            with self.assertRaises(ResearchRecordError):build(source)

    def test_warn_and_missing_inputs_are_retained(self):
        source=result();source['core'].update(qualityStatus='WARN',missingInputs=['cdr_sb_slope'])
        record=build(source);self.assertEqual(record['missingInputs'],['cdr_sb_slope']);self.assertEqual(record['qualityStatus'],'WARN')

    def test_claimed_availability_causality_or_training_independence_is_rejected(self):
        for changes in ({'historical_availability_verified':True},{'future_outcomes_used_as_features':True},{'out_of_sample':True}):
            source=result();source['qualification'].update(changes)
            with self.assertRaises(ResearchRecordError):build(source)
        source=result();source['core']['graph']['interaction_edges'][0]['causal_effect_identified']=True
        with self.assertRaises(ResearchRecordError):build(source)

    def test_dangling_derived_dependencies_are_rejected(self):
        source=result();source['core']['graph']['derived_nodes']=[{'id':'mmse_slope','value':1,'source_nodes':['not-a-source']}]
        with self.assertRaises(ResearchRecordError):build(source)

    def test_derived_age_keeps_source_dependency_and_units(self):
        source=result();graph=source['core']['graph']
        node={'id':'birth','feature':'birth_year','value':1949,'unit':'year','source_table':'CONSTRUCTED','source_visit':'constructed-birth','measurement_date':'2021-01-01','days_before_landmark':41}
        graph['nodes'].append(node);source['availability']['birth']=None
        graph['derived_nodes']=[{'id':'age_years_at_landmark','value':72,'source_nodes':['birth'],'unit':'years'}]
        graph['current_feature_nodes']['age_years']='age_years_at_landmark'
        record=build(source)
        self.assertEqual(record['derivedNodes'][0]['sourceNodeIds'],['birth'])
        self.assertEqual(record['derivedNodes'][0]['unit'],'years')
        graph['derived_nodes'][0]['value']=73
        with self.assertRaises(ResearchRecordError):build(source)

    def test_current_feature_alias_cannot_point_to_missing_or_wrong_source(self):
        for aliases in ({'mmse':'unknown'},{'education_years':'mmse'}):
            source=result();source['core']['graph']['current_feature_nodes']=aliases
            with self.assertRaises(ResearchRecordError):build(source)

    def test_chronology_cannot_add_unsupported_links(self):
        source=result();source['core']['graph']['chronological_edges']=[{'source':'mmse','target':'unknown'}]
        with self.assertRaises(ResearchRecordError):build(source)

    def test_active_interactions_require_the_actual_source_references(self):
        for changes in ({'active':True},{'node_endpoints':['mmse','unknown']}):
            source=result();source['core']['graph']['interaction_edges'][0].update(changes)
            with self.assertRaises(ResearchRecordError):build(source)

    def test_portable_backend_fixture_keeps_success_and_failure_contracts(self):
        path=Path(__file__).parents[1]/'python_service/examples/research_record_acceptance.json'
        example=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(example['fixtureScope'],'CONSTRUCTED_ONLY_NOT_LIVE_MODEL_OR_PATIENT')
        def normalize(value):return build_research_record(value,expected_alias=example['expectedAlias'],expected_model_sha256=example['trustedModelSha256'])
        self.assertEqual(normalize(example['inputResult']),example['expectedRecord'])
        for case in example['negativeCases']:
            value=copy.deepcopy(example['inputResult']);target=value
            for key in case['path'][:-1]:target=target[key]
            target[case['path'][-1]]=case['value']
            with self.subTest(path=case['path']):
                with self.assertRaises(ResearchRecordError) as error:normalize(value)
                self.assertEqual(str(error.exception),case['expectedError'])


if __name__=='__main__':unittest.main()
