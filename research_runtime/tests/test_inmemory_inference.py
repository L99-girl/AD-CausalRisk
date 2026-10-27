"""Constructed request/context and replacement predictor acceptance only."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import pickle
from threading import Event
import unittest

from research_runtime.examples.input_admission_constructed import constructed_pair
from research_runtime.input_admission import AdmissionError
from research_runtime.inmemory_inference import (
    BoundPredictor, InferenceError, PREDICTOR_SCHEMA, authorize_once, run_in_memory,
)


def permit_for(request, context):
    return authorize_once(request, trusted_context=context,
                          authorization_ref='CONSTRUCTED-AUTH', authorization_granted=True)


def prediction(identity, rows):
    return dict(schemaVersion=PREDICTOR_SCHEMA, model=deepcopy(identity),
                predictionWindowMonths=24, predictionPolicy=identity['predictionPolicy'],
                records=[dict(subject_id=row['subject_id'], ad_cif_24m=.1+i/100,
                              other_dementia_cif_24m=.02) for i,row in enumerate(rows)])


def fixture():
    request,context=constructed_pair()
    calls=[];state=['1'*64]
    def predict(rows):
        calls.append(deepcopy(rows))
        return prediction(context['model'],rows)
    predictor=BoundPredictor(context['model'],predict=predict,state_token=lambda:state[0])
    return request,context,predictor,calls,state


def add_second(request,context):
    row=deepcopy(request['records'][0]);row['subjectCode']='CONSTRUCTED-002'
    for name,obs in row['features'].items():
        obs['evidenceRef']+='-second'
        context['evidence'][obs['evidenceRef']]=dict(subjectCode=row['subjectCode'],feature=name,observation=deepcopy(obs))
    request['records'].append(row)


class InMemoryInferenceTests(unittest.TestCase):
    def test_metadata_agreement_without_permission_never_calls_predictor(self):
        request,context,predictor,calls,_=fixture()
        result=run_in_memory(request,trusted_context=context,predictor=predictor)
        self.assertEqual(result['status'],'PERMISSION_REQUIRED');self.assertIsNone(result['predictions'])
        self.assertEqual(result['predictionCalls'],0);self.assertEqual(calls,[])
        self.assertFalse(result['admission']['predictionAllowed'])

    def test_blocked_input_returns_no_scores_even_with_a_prior_permit(self):
        request,context,predictor,calls,_=fixture();permit=permit_for(request,context)
        obs=request['records'][0]['features']['mmse'];obs['qc']='UNKNOWN'
        context['evidence'][obs['evidenceRef']]['observation']['qc']='UNKNOWN'
        result=run_in_memory(request,trusted_context=context,predictor=predictor,permit=permit)
        self.assertEqual(result['status'],'BLOCKED');self.assertIsNone(result['predictions'])
        self.assertEqual(calls,[]);self.assertEqual(permit.prediction_calls,0)

    def test_permission_requires_external_true_not_a_json_flag(self):
        request,context,predictor,calls,_=fixture()
        for value in (False,None,1,'true'):
            with self.assertRaisesRegex(InferenceError,'INDEPENDENT_EXECUTION_PERMISSION_REQUIRED'):
                authorize_once(request,trusted_context=context,authorization_ref='CONSTRUCTED-AUTH',authorization_granted=value)
        with self.assertRaisesRegex(InferenceError,'IN_MEMORY_PERMIT_REQUIRED'):
            run_in_memory(request,trusted_context=context,predictor=predictor,permit={'authorized':True})
        request['authorization_granted']=True
        with self.assertRaises(AdmissionError):run_in_memory(request,trusted_context=context,predictor=predictor)
        self.assertEqual(calls,[])

    def test_authorization_itself_cannot_override_blocked_evidence(self):
        request,context=constructed_pair();context['evidence']={}
        with self.assertRaisesRegex(InferenceError,'ADMISSION_BLOCKED'):permit_for(request,context)

    def test_completed_result_is_bound_to_full_snapshot_and_not_certified(self):
        request,context,predictor,calls,_=fixture();add_second(request,context)
        original=deepcopy((request,context));permit=permit_for(request,context)
        result=run_in_memory(request,trusted_context=context,predictor=predictor,permit=permit)
        self.assertEqual(result['status'],'COMPLETED');self.assertEqual(len(calls),1)
        self.assertEqual([r['subject_id'] for r in result['predictions']],['CONSTRUCTED-001','CONSTRUCTED-002'])
        self.assertEqual(result['model'],context['model']);self.assertEqual(result['dataVersion'],request['dataVersion'])
        self.assertEqual((permit.state,permit.prediction_calls),('COMPLETED',1))
        self.assertEqual((request,context),original)
        self.assertFalse(any(result[k] for k in ('clinicalUse','sourceAuthenticityCertified',
            'historicalAvailabilityCertified','individualCausalEffectIdentified','defaultModelChanged')))
        self.assertFalse(result['admission']['predictionAllowed']);self.assertTrue(result['executionPermissionUsed'])
        self.assertNotIn('requestSha256',result);self.assertNotIn('authorization_ref',result)

    def test_rows_contain_only_original_order_features_and_no_targets_or_dates(self):
        request,context,predictor,calls,_=fixture();permit=permit_for(request,context)
        run_in_memory(request,trusted_context=context,predictor=predictor,permit=permit)
        self.assertEqual(list(calls[0][0]),['subject_id',*context['model']['features']])
        for name in context['model']['features']:
            self.assertEqual(calls[0][0][name],request['records'][0]['features'][name]['value'])

    def test_reusing_completed_permit_cannot_recompute(self):
        request,context,predictor,calls,_=fixture();permit=permit_for(request,context)
        run_in_memory(request,trusted_context=context,predictor=predictor,permit=permit)
        with self.assertRaisesRegex(InferenceError,'PERMIT_ALREADY_USED'):
            run_in_memory(request,trusted_context=context,predictor=predictor,permit=permit)
        self.assertEqual(len(calls),1);self.assertEqual(permit.prediction_calls,1)

    def test_concurrent_calls_share_a_one_call_budget_without_cached_replay(self):
        request,context=constructed_pair();entered=Event();release=Event();calls=[]
        def callback(rows):
            calls.append(1);entered.set()
            if not release.wait(3):raise RuntimeError('CONSTRUCTED_TIMEOUT')
            return prediction(context['model'],rows)
        predictor=BoundPredictor(context['model'],predict=callback,state_token=lambda:'1'*64)
        permit=permit_for(request,context)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(run_in_memory,request,trusted_context=context,predictor=predictor,permit=permit)
            try:
                self.assertTrue(entered.wait(2))
                second=pool.submit(run_in_memory,request,trusted_context=context,predictor=predictor,permit=permit)
                with self.assertRaisesRegex(InferenceError,'PERMIT_ALREADY_USED'):second.result(timeout=2)
            finally:release.set()
            self.assertEqual(first.result(timeout=2)['status'],'COMPLETED')
        self.assertEqual(calls,[1]);self.assertEqual(permit.prediction_calls,1)

    def test_changed_valid_snapshot_or_order_requires_new_permission(self):
        for mode in ('value','order','index','model'):
            request,context,predictor,calls,_=fixture();add_second(request,context);permit=permit_for(request,context)
            if mode=='value':
                obs=request['records'][0]['features']['mmse'];obs['value']=27
                context['evidence'][obs['evidenceRef']]['observation']['value']=27
            elif mode=='order':request['records'].reverse()
            elif mode=='index':request['indexDate']=context['indexDate']='2020-01-03'
            else:request['model']['artifactSha256']=context['model']['artifactSha256']='0'*64
            with self.assertRaisesRegex(InferenceError,'PERMIT_SNAPSHOT_MISMATCH'):
                run_in_memory(request,trusted_context=context,predictor=predictor,permit=permit)
            self.assertEqual(calls,[]);self.assertEqual(permit.prediction_calls,0)

    def test_json_object_key_order_does_not_change_the_binding(self):
        request,context,predictor,calls,_=fixture();permit=permit_for(request,context)
        request=dict(reversed(list(request.items())))
        result=run_in_memory(request,trusted_context=context,predictor=predictor,permit=permit)
        self.assertEqual(result['status'],'COMPLETED');self.assertEqual(len(calls),1)

    def test_predictor_identity_is_checked_before_any_prediction(self):
        request,context,predictor,calls,_=fixture();permit=permit_for(request,context)
        other=deepcopy(context['model']);other['artifactSha256']='0'*64
        predictor=BoundPredictor(other,predict=lambda rows:calls.append(rows),state_token=lambda:'1'*64)
        with self.assertRaisesRegex(InferenceError,'PREDICTOR_MODEL_IDENTITY'):
            run_in_memory(request,trusted_context=context,predictor=predictor,permit=permit)
        self.assertEqual((permit.state,permit.prediction_calls),('FAILED',0));self.assertEqual(calls,[])

    def test_model_state_changes_before_or_during_prediction_are_rejected(self):
        request,context,predictor,calls,state=fixture();permit=permit_for(request,context);state[0]='2'*64
        with self.assertRaisesRegex(InferenceError,'PREDICTOR_STATE_CHANGED'):
            run_in_memory(request,trusted_context=context,predictor=predictor,permit=permit)
        self.assertEqual(calls,[])
        state[0]='1'*64;permit=permit_for(request,context)
        def callback(rows):state[0]='2'*64;return prediction(context['model'],rows)
        predictor=BoundPredictor(context['model'],predict=callback,state_token=lambda:state[0])
        with self.assertRaisesRegex(InferenceError,'PREDICTOR_STATE_CHANGED'):
            run_in_memory(request,trusted_context=context,predictor=predictor,permit=permit)
        self.assertEqual((permit.state,permit.prediction_calls),('FAILED',1))

    def test_input_mutation_discards_all_results_and_does_not_mutate_caller(self):
        request,context=constructed_pair();original=deepcopy(request)
        def callback(rows):rows[0]['mmse']=0;return prediction(context['model'],rows)
        predictor=BoundPredictor(context['model'],predict=callback,state_token=lambda:'1'*64);permit=permit_for(request,context)
        with self.assertRaisesRegex(InferenceError,'PREDICTOR_MUTATED_INPUT'):
            run_in_memory(request,trusted_context=context,predictor=predictor,permit=permit)
        self.assertEqual(request,original);self.assertEqual((permit.state,permit.prediction_calls),('FAILED',1))

    def test_callback_failure_is_sanitized_and_never_retried(self):
        request,context=constructed_pair();calls=[]
        def callback(rows):calls.append(1);raise ValueError('CONSTRUCTED-PRIVATE-VALUE')
        predictor=BoundPredictor(context['model'],predict=callback,state_token=lambda:'1'*64);permit=permit_for(request,context)
        with self.assertRaisesRegex(InferenceError,'^PREDICTOR_CALL_FAILED$') as error:
            run_in_memory(request,trusted_context=context,predictor=predictor,permit=permit)
        self.assertTrue(error.exception.__suppress_context__)
        with self.assertRaisesRegex(InferenceError,'PERMIT_ALREADY_USED'):
            run_in_memory(request,trusted_context=context,predictor=predictor,permit=permit)
        self.assertEqual(calls,[1]);self.assertEqual(permit.state,'FAILED')

    def test_wrong_result_model_policy_window_or_fields_are_rejected(self):
        for key,value in [('schemaVersion','other'),('model',{}),('predictionWindowMonths',True),
                          ('predictionPolicy','calibrated'),('extra','CONSTRUCTED-PRIVATE')]:
            request,context=constructed_pair()
            def callback(rows):
                result=prediction(context['model'],rows);result[key]=value;return result
            predictor=BoundPredictor(context['model'],predict=callback,state_token=lambda:'1'*64);permit=permit_for(request,context)
            with self.assertRaises(InferenceError):run_in_memory(request,trusted_context=context,predictor=predictor,permit=permit)
            self.assertEqual(permit.state,'FAILED')

    def test_invalid_row_counts_order_or_numeric_cifs_never_return_partial_results(self):
        changes=[lambda r:r.update(records=[]),lambda r:r['records'][0].update(subject_id='OTHER'),
                 lambda r:r['records'][0].update(ad_cif_24m=True),lambda r:r['records'][0].update(ad_cif_24m=None),
                 lambda r:r['records'][0].update(ad_cif_24m=float('nan')),
                 lambda r:r['records'][0].update(ad_cif_24m=-.1),lambda r:r['records'][0].update(ad_cif_24m=1.1),
                 lambda r:r['records'][0].update(ad_cif_24m=.8,other_dementia_cif_24m=.3),
                 lambda r:r['records'][0].update(extra='PRIVATE')]
        for change in changes:
            request,context=constructed_pair()
            def callback(rows):r=prediction(context['model'],rows);change(r);return r
            predictor=BoundPredictor(context['model'],predict=callback,state_token=lambda:'1'*64);permit=permit_for(request,context)
            with self.assertRaises(InferenceError):run_in_memory(request,trusted_context=context,predictor=predictor,permit=permit)
            self.assertEqual(permit.prediction_calls,1)

    def test_result_copy_does_not_alias_callback_or_context(self):
        request,context=constructed_pair();held=[]
        def callback(rows):r=prediction(context['model'],rows);held.append(r);return r
        predictor=BoundPredictor(context['model'],predict=callback,state_token=lambda:'1'*64)
        result=run_in_memory(request,trusted_context=context,predictor=predictor,permit=permit_for(request,context))
        held[0]['records'][0]['ad_cif_24m']=.9
        self.assertEqual(result['predictions'][0]['ad_cif_24m'],.1)
        result['model']['features'].reverse();self.assertEqual(context['model']['features'][0],'age_years')

    def test_capabilities_do_not_serialize_or_expose_private_bindings(self):
        request,context,predictor,_,_=fixture();permit=permit_for(request,context)
        for value in (permit,predictor):
            with self.assertRaisesRegex(InferenceError,'IN_MEMORY_CAPABILITY_ONLY'):pickle.dumps(value)
            self.assertNotIn('CONSTRUCTED',repr(value));self.assertNotIn('aaaaaaaa',repr(value))

    def test_predictor_reference_and_state_callback_must_be_valid(self):
        _,context=constructed_pair()
        with self.assertRaisesRegex(InferenceError,'PREDICTOR_CALLBACK_REQUIRED'):
            BoundPredictor(context['model'],predict=None,state_token=lambda:'1'*64)
        with self.assertRaisesRegex(InferenceError,'PREDICTOR_STATE_TOKEN_REQUIRED'):
            BoundPredictor(context['model'],predict=lambda x:None,state_token=lambda:'bad')
        def bad():raise ValueError('CONSTRUCTED-PRIVATE')
        with self.assertRaisesRegex(InferenceError,'^PREDICTOR_STATE_CHECK_FAILED$'):
            BoundPredictor(context['model'],predict=lambda x:None,state_token=bad)


if __name__=='__main__':unittest.main()
