"""Frozen schema parity plus semantic failures schema shape alone cannot detect."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from python_service.course_protocol import (CourseContract,CourseProtocolError,decode_json,
    validate_course_request,validate_course_result)
from python_service.deepagent_contract import run_workflow
from python_service.demo_scoring import score_java_synthetic_payload

ROOT=Path(__file__).resolve().parents[1]


def request():return json.loads((ROOT/'contracts/examples/deepagent-v1.request.example.json').read_text(encoding='utf-8'))
def result(payload=None):return run_workflow(payload or request(),score_java_synthetic_payload)


class CourseProtocolTests(unittest.TestCase):
    def setUp(self):self.contract=CourseContract();self.payload=request();self.value=result(self.payload)
    def rejects(self,change,code=None):
        change(self.value)
        with self.assertRaises(CourseProtocolError) as error:validate_course_result(self.value,self.payload,self.contract)
        if code:self.assertEqual(error.exception.code,code)

    def test_schema_and_semantics_accept_original_result_without_mutation(self):
        before=copy.deepcopy(self.value)
        self.assertIs(validate_course_result(self.value,self.payload,self.contract),self.value)
        self.assertEqual(self.value,before)

    def test_supported_wire_rules_match_independent_jsonschema_on_mutations(self):
        from jsonschema import Draft202012Validator,FormatChecker
        validator=Draft202012Validator(self.contract.schemas['AgentResult'],format_checker=FormatChecker())
        mutations=[lambda x:None,lambda x:x.pop('runId'),lambda x:x.update(extra=True),
                   lambda x:x.update(riskScore=True),lambda x:x.update(riskScore=-.1),
                   lambda x:x.update(riskScore=None),lambda x:x.update(status='RUNNING'),
                   lambda x:x['stages'][0].update(durationMs=-1),
                   lambda x:x['stages'][0].update(durationMs=False),
                   lambda x:x['stages'][0].update(status='FAILED'),
                   lambda x:x['graph']['nodes'][2].update(observedAt='20260101'),
                   lambda x:x['graph']['nodes'][2].update(observedAt=None),
                   lambda x:x['explanations'][0].update(contribution='0.2'),
                   lambda x:x['explanations'][0].update(evidenceLevel='CAUSAL'),
                   lambda x:x.update(reviewRequired=1)]
        for change in mutations:
            value=copy.deepcopy(self.value);change(value)
            with self.subTest(change=mutations.index(change)):
                self.assertEqual(self.contract.matches(self.contract.schemas['AgentResult'],value),validator.is_valid(value))

    def test_wrong_run_data_and_model_identity_are_rejected(self):
        for field,value in [('runId','run-other'),('dataVersion','demo-other'),('modelVersion','other')]:
            self.value=result();self.rejects(lambda x:x.update({field:value}))

    def test_wrong_synthetic_scope_review_and_workflow_are_rejected(self):
        for field,value in [('dataSource','REAL'),('reviewRequired',False),('workflowVersion','other'),('limitations',[])]:
            self.value=result();self.rejects(lambda x:x.update({field:value}))

    def test_stage_order_and_current_stage_must_agree(self):
        self.rejects(lambda x:x['stages'].reverse(),'STAGE_SEQUENCE')
        self.value=result();self.rejects(lambda x:x.update(currentStage='DATA_FUSION'),'STAGE_SEQUENCE')

    def test_summary_counts_dates_and_missing_sources_are_checked(self):
        for field,value in [('indexDate','2025-01-01'),('visitCount',True),('featureCount',0),
                            ('excludedPostIndexFeatures',1),('missingModalities',None)]:
            self.value=result();self.rejects(lambda x:x['stages'][0]['summary'].update({field:value}),'FUSION_EVIDENCE')

    def test_graph_duplicate_nodes_wrong_edges_and_paths_are_rejected(self):
        self.rejects(lambda x:x['graph']['nodes'].append(copy.deepcopy(x['graph']['nodes'][0])),'GRAPH_NODES')
        self.value=result();self.rejects(lambda x:x['graph']['edges'][0].update(to='WARNING'),'GRAPH_EDGES')
        self.value=result();self.rejects(lambda x:x['graph']['paths'][0].update(status='MISSING'),'GRAPH_PATHS')

    def test_graph_activation_and_source_dates_match_eligible_request_values(self):
        self.rejects(lambda x:x['graph']['nodes'][2].update(status='MISSING'),'GRAPH_ACTIVATION')
        self.value=result();self.rejects(lambda x:x['graph']['nodes'][2].update(observedAt='2026-01-02'),'GRAPH_SOURCE_DATE')

    def test_explanation_terms_and_source_cannot_be_relabelled(self):
        self.rejects(lambda x:x['explanations'].pop(),'EXPLANATION_SOURCES')
        self.value=result();self.rejects(lambda x:x['explanations'][0].update(source='clinical-model'),'EXPLANATION_SOURCES')

    def test_reconstruction_uses_rounding_bound_and_clipping(self):
        self.rejects(lambda x:x['explanations'][0].update(contribution=.99),'EXPLANATION_RECONSTRUCTION')
        for level in ('lower','upper'):
            body=request()
            for visit in body['visits']:visit.update(mmse=30 if level=='lower' else 0,moca=30 if level=='lower' else 0,cdrSb=0 if level=='lower' else 18)
            if level=='upper':body['visits'][0]['mmse']=30
            for feature in body['features']:feature['featureValue']=(0 if level=='lower' else 2) if feature['featureName']=='APOE_E4_COUNT' else (1 if level=='lower' else 0)
            value=result(body);validate_course_result(value,body,self.contract)
            self.assertEqual(value['riskScore'],.05 if level=='lower' else .95)

    def test_score_precision_and_level_cannot_disagree_with_wire_value(self):
        self.rejects(lambda x:x.update(riskScore=.500001),'SCORE_PRECISION')
        self.value=result();self.rejects(lambda x:x.update(riskLevel='LOW'),'SCORE_LEVEL')

    def test_blocked_never_contains_score_graph_or_explanation(self):
        body=request();body['visits']=[];value=result(body)
        validate_course_result(value,body,self.contract)
        value['riskScore']=0
        with self.assertRaises(CourseProtocolError):validate_course_result(value,body,self.contract)
        value=result(body);value['graph']['nodes']=copy.deepcopy(self.value['graph']['nodes'])
        with self.assertRaises(CourseProtocolError) as error:validate_course_result(value,body,self.contract)
        self.assertEqual(error.exception.code,'BLOCKED_HAS_OUTPUT')

    def test_schema_valid_false_block_for_eligible_input_is_rejected(self):
        body=request();body['predictionWindowMonths']=12;self.value=result(body)
        self.rejects(lambda x:None,'STAGE_SEQUENCE')

    def test_parser_rejects_duplicates_nonfinite_nonobjects_and_secret_body(self):
        for raw in (b'[]',b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":1e999}',b'CONSTRUCTED_SECRET_BODY'):
            with self.assertRaises(CourseProtocolError) as error:decode_json(raw)
            self.assertNotIn('CONSTRUCTED_SECRET',str(error.exception))

    def test_contract_changes_and_unsupported_keywords_fail_closed(self):
        with self.assertRaises(CourseProtocolError):CourseContract.check_keywords({'type':'number','multipleOf':2})
        raw=(ROOT/'contracts/python-agent.openapi.json').read_bytes()+b'\n'
        with patch('python_service.course_protocol.CONTRACT_FILE',SimpleNamespace(read_bytes=lambda:raw)):
            with self.assertRaises(CourseProtocolError) as error:CourseContract()
        self.assertEqual(error.exception.code,'FROZEN_CONTRACT_CHANGED')

    def test_request_preflight_preserves_server_integer_date_and_demo_rules(self):
        for change in (lambda x:x.update(subjectCode='REAL-1'),lambda x:x.update(predictionWindowMonths=True),
                       lambda x:x.update(predictionWindowMonths=24.),lambda x:x['visits'][0].update(visitDate='20250101')):
            body=request();change(body)
            with self.assertRaises(CourseProtocolError):validate_course_request(body,self.contract)


if __name__=='__main__':unittest.main()
