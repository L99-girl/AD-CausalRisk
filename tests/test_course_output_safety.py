"""Schema-valid claims must not pass the fixed course output boundary."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator
from python_service.course_protocol import CourseContract, CourseProtocolError, validate_course_result
from python_service.deepagent_contract import AgentContractError, run_workflow
from python_service.demo_scoring import score_java_synthetic_payload
from python_service.server import RunStore

ROOT = Path(__file__).resolve().parents[1]


def request():
    return json.loads((ROOT / 'contracts/examples/deepagent-v1.request.example.json').read_text(encoding='utf-8'))


def result(body):
    return run_workflow(body, score_java_synthetic_payload)


class OutputSafetyTests(unittest.TestCase):
    def setUp(self):
        self.body = request()
        self.value = result(self.body)
        self.contract = CourseContract()
        self.schema = Draft202012Validator(self.contract.schemas['AgentResult'])

    def reject(self, change, code):
        value = copy.deepcopy(self.value)
        change(value)
        self.schema.validate(value)
        with self.assertRaises(CourseProtocolError) as error:
            validate_course_result(value, self.body, self.contract)
        self.assertEqual(error.exception.code, code)

    def test_every_explanation_label_message_and_interpretation_is_checked(self):
        for i in range(len(self.value['explanations'])):
            for field in ('label', 'message', 'interpretation'):
                with self.subTest(i=i, field=field):
                    self.reject(lambda x: x['explanations'][i].update({field: '已确诊；治疗必然有效'}),
                                'OUTPUT_EXPLANATION_TEXT')

    def test_disclaimer_prefix_unicode_and_hidden_text_do_not_excuse_changes(self):
        for claim in ('仅供研究。该因素已证明导致疾病', 'Clinically validated', '必\u200b然患病',
                      '<span hidden>临床可用</span>', '预测贡献，不是因果效应\n请立即用药',
                      '预测贡献，不是因果效应。', '预测贡献，不是因果效应\x00'):
            self.reject(lambda x: x['explanations'][0].update(interpretation=claim), 'OUTPUT_EXPLANATION_TEXT')

    def test_every_graph_label_is_checked(self):
        for i in range(5):
            self.reject(lambda x: x['graph']['nodes'][i].update(label='已识别个体病因'), 'OUTPUT_GRAPH_TEXT')

    def test_every_edge_note_is_checked(self):
        for i in range(4):
            self.reject(lambda x: x['graph']['edges'][i].update(note='该干预保证获益'), 'OUTPUT_GRAPH_TEXT')

    def test_edge_direction_remains_rejected_by_original_schema(self):
        for i in range(4):
            value = copy.deepcopy(self.value)
            value['graph']['edges'][i]['direction'] = 'CAUSES'
            self.assertFalse(self.schema.is_valid(value))
            with self.assertRaises(CourseProtocolError) as error:
                validate_course_result(value, self.body, self.contract)
            self.assertEqual(error.exception.code, 'WIRE_SCHEMA_MISMATCH')

    def test_extra_limitations_are_not_automatically_trusted(self):
        for text in ('additional restriction', '所有结果可临床使用', '未验证，但已证明治疗收益'):
            self.reject(lambda x: x['limitations'].append(text), 'OUTPUT_LIMITATIONS')

    def test_duplicate_limitations_are_rejected(self):
        self.reject(lambda x: x['limitations'].append(x['limitations'][0]), 'OUTPUT_LIMITATIONS')

    def test_each_summary_rejects_unknown_keys_and_nested_claims(self):
        for i in range(4):
            for key, claim in (('clinicalUseAllowed', True), ('extraMetadata', {'text': '确诊'}),
                               ('安全审查', '已通过临床认证')):
                self.reject(lambda x: x['stages'][i]['summary'].update({key: claim}), 'OUTPUT_SUMMARY_FIELDS')

    def test_blocked_extra_summary_is_rejected_before_return(self):
        self.body['predictionWindowMonths'] = 12
        self.value = result(self.body)
        self.reject(lambda x: x['stages'][0]['summary'].update(clinicalUseAllowed=True), 'OUTPUT_SUMMARY_FIELDS')

    def test_blocked_additional_limitations_are_rejected(self):
        self.body['visits'] = []
        self.value = result(self.body)
        self.reject(lambda x: x['limitations'].append('未评估也能确诊'), 'OUTPUT_LIMITATIONS')

    def test_wrong_but_allowed_message_polarity_is_rejected(self):
        self.reject(lambda x: next(y for y in x['explanations'] if y['feature'] == 'MMSE').update(
            message='当前认知评分对风险排序贡献偏低'), 'OUTPUT_EXPLANATION_TEXT')

    def test_raw_sign_not_rounded_zero_or_direction_controls_mmse_message(self):
        for mmse, expected in ((26.99999, '偏高'), (27., '偏高'), (27.00001, '偏低')):
            body = request()
            body['visits'] = [dict(body['visits'][-1], mmse=mmse)]
            value = result(body)
            item = next(x for x in value['explanations'] if x['feature'] == 'MMSE')
            self.assertEqual(item['contribution'], 0)
            self.assertEqual(item['direction'], 'NEUTRAL')
            self.assertTrue(item['message'].endswith(expected))
            validate_course_result(value, body, self.contract)

    def test_zero_delta_uses_original_nonpositive_wording(self):
        for mmse, expected in ((23.99999, '纵向变化使排序分数上移'),
                               (24., '纵向变化暂未使排序分数上移'),
                               (24.00001, '纵向变化暂未使排序分数上移')):
            body = request()
            body['visits'][0]['mmse'] = 24
            body['visits'][-1]['mmse'] = mmse
            value = result(body)
            item = next(x for x in value['explanations'] if x['feature'] == 'MMSE_DELTA')
            self.assertEqual(item['message'], expected)
            self.assertEqual(item['direction'], 'NEUTRAL')
            validate_course_result(value, body, self.contract)

    def test_zero_cdr_and_negative_mri_preserve_original_descriptive_text(self):
        body = request()
        body['visits'][-1]['cdrSb'] = 0
        for x in body['features']:
            if x['featureName'].startswith('MRI'): x['featureValue'] = 1
        value = result(body)
        cdr = next(x for x in value['explanations'] if x['feature'] == 'CDR_SB')
        mri = next(x for x in value['explanations'] if x['feature'] == 'MRI_HIPPOCAMPUS')
        self.assertEqual(cdr['contribution'], 0)
        self.assertLess(mri['contribution'], 0)
        validate_course_result(value, body, self.contract)

    def test_permutation_of_unordered_collections_remains_accepted(self):
        for key in ('limitations', 'warnings', 'explanations'):
            self.value[key].reverse()
        for key in ('nodes', 'edges', 'paths'): self.value['graph'][key].reverse()
        validate_course_result(self.value, self.body, self.contract)

    def test_checker_never_calls_scorer_or_workflow_and_does_not_mutate(self):
        before = copy.deepcopy((self.body, self.value))
        with patch('python_service.deepagent_contract.run_workflow', side_effect=AssertionError('EXECUTED')), \
             patch('python_service.demo_scoring.score_java_synthetic_payload', side_effect=AssertionError('SCORED')):
            validate_course_result(self.value, self.body, self.contract)
        self.assertEqual((self.body, self.value), before)

    def test_bad_tool_text_is_execution_500_and_uncached(self):
        store = RunStore()
        def bad_tool(body):
            value = score_java_synthetic_payload(body)
            value['explanations'][0]['message'] = 'PRIVATE_DETAIL治疗保证有效'
            return value
        with patch('python_service.server.score_java_synthetic_payload', side_effect=bad_tool) as tool:
            with self.assertRaises(AgentContractError) as error: store.create(self.body)
        self.assertEqual(error.exception.status, 500)
        self.assertNotIn('PRIVATE_DETAIL', str(error.exception))
        self.assertEqual(tool.call_count, 1)
        self.assertEqual(store.runs, {})

    def test_store_rejects_invalid_workflow_text_even_when_tool_check_is_bypassed(self):
        for change in (lambda x: x['limitations'].append('可供临床使用'),
                       lambda x: x['stages'][0]['summary'].update(clinicalUseAllowed=True),
                       lambda x: x['graph']['nodes'][0].update(label='确定患病')):
            value = copy.deepcopy(self.value)
            change(value)
            store = RunStore()
            with patch('python_service.server.run_workflow', return_value=value):
                with self.assertRaises(AgentContractError) as error: store.create(self.body)
            self.assertEqual(error.exception.status, 500)
            self.assertEqual(store.runs, {})


if __name__ == '__main__': unittest.main()
