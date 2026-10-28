"""In-memory constant models and mocked attributions; no optimizer or regression."""
from copy import deepcopy
import json
import unittest
from unittest.mock import Mock

import numpy as np

from research_runtime import grouped_xai_study as study
from research_runtime.graph_native import make_graph_estimator, FEATURES
from research_runtime.training import checked_design, synthetic_cohort, input_fingerprint, prediction_hash
from research_runtime.discrete import person_period
from research_runtime.tests.test_graph_training import constant_fit


class StudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        torch.set_num_threads(1)
        cls.frame,cls.splits,_=checked_design(synthetic_cohort(),'multimodal_values')
        cls.fingerprint=input_fingerprint(cls.frame,'multimodal_values')
        cls.models={};cls.raw={s:np.empty((90,2)) for s in study.SEEDS};weights=np.empty(90)
        for fold,(train,test) in enumerate(cls.splits,1):
            periods,labels=person_period(cls.frame.iloc[train],list(FEATURES))
            weights[test]=study.horizon_ipcw_weights(cls.frame.iloc[test],study.censor_survival(cls.frame.iloc[train]))
            for seed in study.SEEDS:
                model=make_graph_estimator('prior',seed)
                constant_fit(model.named_steps['hazards'],periods,labels)
                cls.models[seed,fold]=model
                cls.raw[seed][test]=study.checked_cif(model,cls.frame.iloc[test])
        target=cls.frame.event_type.eq(1).to_numpy(float)
        ensemble=np.stack(list(cls.raw.values())).mean(axis=0)
        cls.expected=dict(arm='prior',ad_oof_sha256=prediction_hash(ensemble[:,0]),
            other_oof_sha256=prediction_hash(ensemble[:,1]),pooled_oof_brier=float(np.mean(weights*(target-ensemble[:,0])**2)),
            per_seed=[dict(seed=s,ad_oof_sha256=prediction_hash(cls.raw[s][:,0]),
                other_oof_sha256=prediction_hash(cls.raw[s][:,1]),
                pooled_oof_brier=float(np.mean(weights*(target-cls.raw[s][:,0])**2))) for s in study.SEEDS])

    def fake_shapley(self,model,frame,**kwargs):
        values=self.raw[model.named_steps['hazards'].seed][frame.index]
        return dict(group_names=tuple(n for n,_ in study.GROUPS),contributions=np.zeros((len(frame),9,2)),
                    reference_cif=values.copy(),prediction_cif=values.copy(),cif_calls=0,coalition_evaluations=0)

    def fake_lime(self,model,frame,**kwargs):
        values=self.raw[model.named_steps['hazards'].seed][frame.index]
        return dict(group_names=tuple(n for n,_ in study.GROUPS),contributions=np.zeros((1,9,2)),
            prediction_cif=values.copy(),cif_calls=0,neighborhood_evaluations=0,local_surrogate_fits=0,
            observed_residual=np.zeros((1,2)),weighted_r2=[None,None],
            heldout_fidelity=dict(samples=0,status='MOCK_NO_FITS',weighted_rmse=None,weighted_r2=None))

    def test_full_fixed_matrix_and_aggregate_only_output(self):
        loaded=[];shap=Mock(side_effect=self.fake_shapley);lime=Mock(side_effect=self.fake_lime)
        def loader(seed,fold):loaded.append((seed,fold));return self.models[seed,fold]
        result=study.evaluate(self.frame,self.splits,loader,self.expected,
            expected_input_fingerprint=self.fingerprint,shapley=shap,lime=lime)
        self.assertEqual(len(loaded),15);self.assertEqual(len(set(loaded)),15)
        self.assertEqual((shap.call_count,lime.call_count),(30,600))
        self.assertEqual((result['subjects'],result['lime_subset_subjects']),(90,50))
        self.assertEqual(len(result['sensitivity']),66)
        self.assertEqual(len(result['lime_fidelity']),24)
        self.assertEqual(result['operations'],dict(cif_calls=15,cif_state_rows=270,local_surrogate_fits=0))
        self.assertNotIn('SYNTHETIC-',json.dumps(result))
        self.assertNotIn('prediction_cif',json.dumps(result))
        self.assertFalse(result['participant_outputs_saved'])
        self.assertTrue(all(r['top_rank_agreement'] is None for r in result['sensitivity']))

    def test_input_and_each_seed_OOF_mismatch_stop_before_attribution(self):
        loader=Mock(side_effect=lambda seed,fold:self.models[seed,fold]);attribution=Mock()
        with self.assertRaisesRegex(ValueError,'INPUT_FINGERPRINT'):
            study.evaluate(self.frame,self.splits,loader,self.expected,expected_input_fingerprint='0'*64,
                shapley=attribution,lime=attribution)
        loader.assert_not_called();attribution.assert_not_called()
        expected=deepcopy(self.expected);expected['per_seed'][1]['other_oof_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'SEED_OOF_CHANGED'):
            study.evaluate(self.frame,self.splits,loader,expected,expected_input_fingerprint=self.fingerprint,
                shapley=attribution,lime=attribution)
        self.assertEqual(loader.call_count,15);attribution.assert_not_called()

    def test_budget_is_reserved_before_explanation_or_local_fitting(self):
        attribution=Mock()
        with self.assertRaisesRegex(ValueError,'BUDGET_EXCEEDED'):
            study.evaluate(self.frame,self.splits,lambda seed,fold:self.models[seed,fold],self.expected,
                expected_input_fingerprint=self.fingerprint,max_cif_calls=15,
                shapley=attribution,lime=attribution)
        attribution.assert_not_called()


if __name__=='__main__':
    unittest.main()
