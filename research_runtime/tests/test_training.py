"""Constructed cohorts only; test leakage, reuse, weighting and delivered artifacts."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd

from research_runtime import training as t
from research_runtime import evaluation as e
from research_runtime.discrete import person_period


class TrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temp.name);cls.frame=t.synthetic_cohort()
        cls.before=cls.frame.copy(deep=True)
        cls.result=t.run_nested(cls.frame,cls.root/'scratch','multimodal_values',('logistic',))
        cls.bases={}
        for row in cls.result['artifacts']:
            cls.bases[row['family'],row['outer_fold']]=joblib.load(cls.root/'scratch'/row['file'])['model']
        cls.states={key:joblib.hash(value) for key,value in cls.bases.items()}
        cls.expected={row['family']:row['oof_prediction_sha256'] for row in cls.result['models'] if row['policy']=='raw'}
        cls.reused=t.run_nested(cls.frame,cls.root/'reuse','multimodal_values',('logistic',),
                                existing_models=cls.bases,expected_oof=cls.expected)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_all_nested_positions_exclude_outer_test_and_cover_train(self):
        work,splits,nested=t.checked_design(self.frame,'multimodal_values')
        for (a,b),inner in zip(splits,nested['outer_inner']):
            seen=[]
            for row in inner:
                x,y=set(row['fit_positions']),set(row['calibration_positions'])
                self.assertFalse(x&y);self.assertFalse((x|y)&set(b))
                self.assertEqual(x|y,set(a));seen.extend(y)
            self.assertEqual(sorted(seen),sorted(a.tolist()))
        self.assertEqual(len(work),90)

    def test_invalid_designs_stop_before_any_fit_or_output_creation(self):
        _,splits,_=t.checked_design(self.frame,'seven')
        bad=list(splits);bad[0]=(np.r_[splits[0][0],splits[0][1][:1]],splits[0][1])
        other=list(splits);other[1]=other[0]
        for i,design in enumerate([bad,other,[(a.astype(float),b) for a,b in splits],splits[:4]]):
            target=self.root/f'invalid-{i}'
            with patch.object(t,'fit_base',side_effect=AssertionError('must not fit')):
                with self.assertRaises(ValueError):t.run_nested(self.frame,target,'seven',('logistic',),splits=design)
            self.assertFalse(target.exists())

    def test_insufficient_competing_support_or_duplicate_subjects_preflight(self):
        for frame in [self.frame[self.frame.event_type.ne(2)],pd.concat([self.frame,self.frame.iloc[:1]])]:
            with self.assertRaises(ValueError):t.checked_design(frame,'seven')

    def test_forbidden_outer_subject_stops_before_inner_fit(self):
        with patch.object(t,'fit_base',side_effect=AssertionError('must not fit')):
            with self.assertRaisesRegex(ValueError,'OUTER_TEST'):
                t.crossfit(self.frame,'logistic','seven',t.SEED,None,'test',forbidden=self.frame.subject_id[:1])

    def test_full_scratch_and_reuse_counts_and_aggregate_identity(self):
        self.assertEqual(self.result['fits'],{'predictive':24,'calibration':6})
        self.assertEqual(self.reused['fits'],{'predictive':18,'calibration':6})
        self.assertEqual(self.result['models'],self.reused['models'])
        self.assertEqual(self.result['paired_calibration_brier'],self.reused['paired_calibration_brier'])
        self.assertEqual(len(self.result['artifacts']),6)
        self.assertEqual(len(self.reused['artifacts']),6)
        self.assertFalse(list((self.root/'reuse').glob('*.joblib')))
        for result in (self.result,self.reused):
            self.assertFalse(result['clinical_use']);self.assertFalse(result['causal_effect_identified'])
            self.assertFalse(result['default_model_changed']);self.assertFalse(result['participant_predictions_saved'])
            self.assertTrue(all(row['maximum_raw_and_calibrated_two_cause_error']==0 for row in result['artifacts']))

    def test_reused_models_and_input_are_unchanged(self):
        self.assertEqual({key:joblib.hash(value) for key,value in self.bases.items()},self.states)
        pd.testing.assert_frame_equal(self.frame,self.before)

    def test_artifacts_bind_input_folds_source_and_training_plan(self):
        folder=self.root/'scratch'
        plan=json.loads((folder/'Training_Plan.json').read_text())
        self.assertEqual(t.sha(folder/'Training_Plan.json'),self.result['training_plan_sha256'])
        self.assertEqual(t.sha(folder/'Folds.private.json'),plan['folds_sha256'])
        self.assertEqual(plan['input_fingerprint'],t.input_fingerprint(self.frame,'multimodal_values'))
        changed=self.frame.copy();changed.loc[0,'mmse']=24.5
        self.assertNotEqual(plan['input_fingerprint'],t.input_fingerprint(changed,'multimodal_values'))
        for row in self.result['artifacts']:
            path=folder/row['file'];self.assertEqual(t.sha(path),row['sha256'])
            self.assertEqual(joblib.load(path)['training_plan_sha256'],self.result['training_plan_sha256'])

    def test_original_oof_mismatch_rejected_before_new_fit_and_failure_recorded(self):
        target=self.root/'wrong-oof'
        with patch.object(t,'fit_base',side_effect=AssertionError('must not fit')):
            with self.assertRaisesRegex(ValueError,'RAW_OOF_MISMATCH'):
                t.run_nested(self.frame,target,'multimodal_values',('logistic',),
                             existing_models=self.bases,expected_oof={'logistic':'0'*64})
        self.assertEqual((target/'Fit_Ledger.jsonl').read_text(),'')
        self.assertEqual(json.loads((target/'Run_State.json').read_text())['status'],'FAILED')

    def test_all_saved_base_keys_required_before_output_creation(self):
        incomplete=dict(self.bases);incomplete.pop(('logistic',None))
        target=self.root/'missing-base'
        with self.assertRaisesRegex(ValueError,'EXACT_SAVED_BASES'):
            t.run_nested(self.frame,target,'multimodal_values',('logistic',),
                         existing_models=incomplete,expected_oof=self.expected)
        self.assertFalse(target.exists())

    def test_training_person_month_imputation_excludes_test_values(self):
        work,splits,_=t.checked_design(self.frame,'multimodal_values')
        train=work.iloc[splits[0][0]]
        periods,_=person_period(train,list(t.SPECS['multimodal_values']))
        model=self.bases['logistic',1]
        actual=model.named_steps['preprocess'].named_transformers_['clinical'].named_steps['impute'].statistics_
        np.testing.assert_array_equal(actual,np.nanmedian(periods[list(t.SPECS['multimodal_values'])],axis=0))
        before=actual.copy();test=work.iloc[splits[0][1]].copy();test['mmse']=1000000
        t.predict(model,test,'multimodal_values')
        np.testing.assert_array_equal(actual,before)

    def test_ipcw_event_left_limit_competing_non_ad_and_full_denominator(self):
        frame=pd.DataFrame({'event_type':[1,2,0,0],'observed_month':[3,3,24,5]})
        g=np.ones(25);g[2]=.5;g[24]=.25
        weights=e.horizon_ipcw_weights(frame,g)
        np.testing.assert_array_equal(weights,[2,2,4,0])
        score=np.array([.7,.3,.2,.9]);m=e.horizon_metrics(frame,score,g)
        expected=(2*.3**2+2*.3**2+4*.2**2)/4
        self.assertAlmostEqual(m['ipcw_brier_24m'],expected)
        self.assertEqual(e.horizon_ipcw_weights(frame,np.zeros(25)).tolist(),[20,20,20,0])

    def test_calibration_two_cause_odds_mapping_and_parameter_rejection(self):
        raw=np.array([[.1,.2],[.8,.1],[0,.4]])
        p={'intercept':.2,'slope':1.}
        values=t.calibrated(raw,p)
        clipped=np.clip(raw[:,0],1e-6,1-1e-6);odds=clipped/(1-clipped)*np.exp(.2)
        expected=odds/(1+odds)
        np.testing.assert_allclose(values[:,0],expected,rtol=1e-14)
        np.testing.assert_allclose(values[:,1],raw[:,1]*(1-expected)/np.maximum(1-raw[:,0],1e-6))
        self.assertTrue((values.sum(axis=1)<=1).all())
        with self.assertRaises(ValueError):t.calibrated(raw,{'intercept':0,'slope':-1})
        with patch.object(e,'weighted_calibration',return_value={'intercept':0,'slope':-1}):
            with self.assertRaisesRegex(ValueError,'NONMONOTONE'):
                e.calibrator_parameters(np.array([.1,.8]),np.array([0,1]),np.ones(2))

    def test_existing_output_and_budget_never_overwrite_or_recompute(self):
        with patch.object(t,'fit_base',side_effect=AssertionError('must not fit')):
            with self.assertRaises(FileExistsError):t.run_nested(self.frame,self.root/'scratch','seven',('logistic',))
        folder=self.root/'journal';folder.mkdir();j=t.Journal(folder,('logistic',),True)
        try:
            for kind,limit in j.limits.items():
                for _ in range(limit):j.attempt(kind)
                with self.assertRaisesRegex(ValueError,'BUDGET'):j.attempt(kind)
                self.assertEqual(j.counts[kind],limit)
        finally:j.close()
        self.assertEqual(len((folder/'Fit_Ledger.jsonl').read_text().splitlines()),24)


if __name__=='__main__':unittest.main()
