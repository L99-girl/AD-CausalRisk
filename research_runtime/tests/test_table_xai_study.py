"""Artificial fixed state and mock full matrix; no risk/preprocessor fit/load."""
from copy import deepcopy
import json
import unittest
from unittest.mock import Mock,patch

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier

from research_runtime import table_xai_study as study, table_explanation as table
from research_runtime.training import synthetic_cohort,checked_design,input_fingerprint,prediction_hash
from research_runtime.tests.test_table_explanation import constructed_model,frame_for


def bundle_for(spec,family,fold):
    model=constructed_model(spec)
    if family!='logistic':
        # Correct classifier type, intentionally unfitted; full-matrix predictions
        # are mocked. These are not artificial RF/XGB performance probes.
        model.named_steps['hazards'].estimator_=RandomForestClassifier() if family=='random_forest' else XGBClassifier()
    role='NESTED_OUTER_RESEARCH_VALIDATION' if spec=='seven' else 'MULTIMODAL_OUTER_VALIDATION'
    row=dict(specification=spec,family=family,outer_fold=fold,role=role,clinical_use=False,plan_sha256='a'*64)
    bundle=dict(model=model,role=role,family=family,outer_fold=fold,columns=list(study.SPECS[spec]),clinical_use=False)
    if spec=='seven':bundle.update(training_plan_sha256='a'*64,calibrator={'not_used':True})
    else:bundle.update(plan_sha256='a'*64,arm=spec,retrospective_only=True,prediction_policy='raw_uncalibrated_24month_CIF')
    return row,bundle


class TableStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame,cls.splits,_=checked_design(synthetic_cohort(),'multimodal_values')
        cls.fingerprint=input_fingerprint(cls.frame,'multimodal_values')
        cls.candidates=[];cls.bundles={};cls.model_keys={};cls.raw={};weights=np.empty(len(cls.frame))
        for spec in study.SPECIFICATIONS:
            for family in study.FAMILIES:cls.raw[spec,family]=np.empty((len(cls.frame),2))
        for fold,(train,test) in enumerate(cls.splits,1):
            weights[test]=study.horizon_ipcw_weights(cls.frame.iloc[test],study.censor_survival(cls.frame.iloc[train]))
            for si,spec in enumerate(study.SPECIFICATIONS):
                for fi,family in enumerate(study.FAMILIES):
                    row,bundle=bundle_for(spec,family,fold);key=spec,family,fold
                    cls.candidates.append(row);cls.bundles[key]=bundle;cls.model_keys[id(bundle['model'])]=key
                    cls.raw[spec,family][test]=[.10+fold*.01+si*.003+fi*.002,.025]
        target=cls.frame.event_type.eq(1).to_numpy(float);cls.expected={}
        for spec in study.SPECIFICATIONS:
            cls.expected[spec]={'historical_other_cause_OOF_hash':None}
            for family in study.FAMILIES:
                p=cls.raw[spec,family][:,0]
                cls.expected[spec][family]=dict(oof_prediction_sha256=prediction_hash(p),pooled_oof_brier=float(np.mean(weights*(target-p)**2)))

    def baseline(self,model,frame,spec):return self.raw[spec,self.model_keys[id(model)][1]][frame.index].copy()

    def fake_shapley(self,model,frame,spec,**kwargs):
        p=self.baseline(model,frame,spec);g=len(table.groups_for(spec))
        return dict(group_names=tuple(n for n,_ in table.groups_for(spec)),contributions=np.zeros((len(frame),g,2)),
            prediction_cif=p.copy(),reference_cif=p.copy(),cif_calls=0,cif_state_rows=0)

    def fake_lime(self,model,frame,spec,**kwargs):
        result=self.fake_shapley(model,frame,spec);eligible=int(frame.index[0]%3!=0)
        result.update(local_surrogate_fits=0,weighted_rmse=[.002,.003],weighted_mae=[.001,.002],weighted_r2=[None,-.5],
            observed_residual=np.zeros((1,2)),heldout_fidelity=dict(samples=eligible,weighted_rmse=[.02,.001] if eligible else None,
                weighted_mae=[.01,.0005] if eligible else None,weighted_r2=[None,-1.] if eligible else None))
        return result

    def invoke(self,**changes):
        options=dict(expected_input_fingerprint=self.fingerprint,expected_subjects=90,
            shapley=self.fake_shapley,lime=self.fake_lime)
        options.update(changes);loader=options.pop('loader',lambda s,f,k:self.bundles[s,f,k])
        expected=options.pop('expected',self.expected);candidates=options.pop('candidates',self.candidates)
        with patch.object(study,'checked_baseline',side_effect=self.baseline):
            return study.evaluate(self.frame,self.splits,loader,candidates,expected,**options)

    def test_full_fixed_60_1200_matrix_aggregate_only_and_denominators(self):
        loaded=[];events=[];shap=Mock(side_effect=self.fake_shapley);lime=Mock(side_effect=self.fake_lime)
        def loader(s,f,k):loaded.append((s,f,k));return self.bundles[s,f,k]
        result=self.invoke(loader=loader,shapley=shap,lime=lime,progress=events.append)
        self.assertEqual((len(loaded),len(set(loaded)),shap.call_count,lime.call_count),(30,30,60,1200))
        self.assertEqual(result['operations'],dict(cif_calls=30,cif_state_rows=540,local_surrogate_fits=0))
        self.assertEqual((len(result['importance']),len(result['sensitivity']),len(result['lime_fidelity']),len(result['lime_heldout_eligibility'])),(72,132,48,8))
        self.assertFalse(result['historical_other_cause_OOF_hash_verified']);self.assertEqual(result['lime_subset_unique_people'],50)
        self.assertEqual(events[30]['phase'],'ALL_SIX_AD_OOF_VERIFIED')
        for row in result['lime_heldout_eligibility']:
            self.assertEqual(row['heldout_eligible_person_model_pairs'],3*row['unique_people_with_any_heldout'])
            self.assertEqual(row['unique_people_with_any_heldout'],row['unique_people_with_all_three_heldout'])
        self.assertTrue(all(r['heldout_RMSE_over_001']==r['heldout_eligible_subjects'] for r in result['lime_fidelity'] if r['cause']=='AD'))
        self.assertTrue(all(r['heldout_R2']['median']==-1. for r in result['lime_fidelity'] if r['cause']=='OTHER_DEMENTIA'))
        self.assertNotIn('SYNTHETIC-',json.dumps(result));self.assertNotIn('prediction_cif',json.dumps(result))
        self.assertFalse(result['participant_outputs_saved']);json.dumps(result,allow_nan=False)

    def test_input_and_OOF_hash_or_Brier_fail_before_any_attribution(self):
        callback=Mock();loader=Mock()
        with self.assertRaisesRegex(ValueError,'INPUT_FINGERPRINT'):self.invoke(loader=loader,expected_input_fingerprint='0'*64,shapley=callback,lime=callback)
        loader.assert_not_called()
        for field,value in [('oof_prediction_sha256','0'*64),('pooled_oof_brier',.99)]:
            expected=deepcopy(self.expected);expected['multimodal_values']['xgboost'][field]=value
            with self.assertRaisesRegex(ValueError,'AD_OOF_CHANGED|AD_BRIER_CHANGED'):self.invoke(expected=expected,shapley=callback,lime=callback)
        callback.assert_not_called()

    def test_outer_archive_metadata_role_policy_family_and_fold_reject(self):
        for spec in study.SPECIFICATIONS:
            row,bundle=bundle_for(spec,'logistic',1)
            self.assertIs(study.checked_outer_bundle(bundle,row),bundle['model'])
            fields=[('role','FULL_COHORT_SEVEN_VARIABLE_RESEARCH_MODEL'),('outer_fold',True),('family','xgboost'),
                ('columns',list(reversed(bundle['columns']))),('clinical_use',True),
                ('training_plan_sha256' if spec=='seven' else 'plan_sha256','b'*64)]
            if spec!='seven':fields += [('arm','modality_availability'),('prediction_policy','calibrated'),('retrospective_only',False)]
            for key,value in fields:
                wrong=dict(bundle);wrong[key]=value
                with self.assertRaises(ValueError):study.checked_outer_bundle(wrong,row)
            wrong=deepcopy(row);wrong['family']='random_forest';wrongbundle=dict(bundle,family='random_forest')
            with self.assertRaisesRegex(ValueError,'ESTIMATOR_FAMILY'):study.checked_outer_bundle(wrongbundle,wrong)
            missing=dict(row);missing.pop('plan_sha256')
            incomplete=dict(bundle);incomplete.pop('training_plan_sha256' if spec=='seven' else 'plan_sha256')
            with self.assertRaisesRegex(ValueError,'OUTER_CANDIDATE'):study.checked_outer_bundle(incomplete,missing)

    def test_stored_fold_positions_and_subject_lists_must_both_match(self):
        private=[dict(train_positions=a.tolist(),test_positions=b.tolist(),train_subjects=self.frame.iloc[a].subject_id.tolist(),test_subjects=self.frame.iloc[b].subject_id.tolist()) for a,b in self.splits]
        checked=study.checked_original_folds(self.frame,private)
        for (a,b),(x,y) in zip(checked,self.splits):np.testing.assert_array_equal(a,x);np.testing.assert_array_equal(b,y)
        for mutation in ('subject','position','boolean','repeat'):
            wrong=deepcopy(private)
            if mutation=='subject':wrong[0]['test_subjects'][0]='CONSTRUCTED-WRONG'
            elif mutation=='position':wrong[0]['test_positions'][0]=9999
            elif mutation=='boolean':wrong[0]['test_positions'][0]=True
            else:wrong[1]=deepcopy(wrong[0])
            with self.assertRaises(ValueError):study.checked_original_folds(self.frame,wrong)

    def test_study_budget_reserved_and_resource_checked_before_attribution(self):
        attribution=Mock()
        with self.assertRaisesRegex(ValueError,'BUDGET_EXCEEDED'):self.invoke(max_cif_calls=30,shapley=attribution,lime=attribution)
        attribution.assert_not_called()
        loader=Mock()
        with self.assertRaisesRegex(ValueError,'TIME_OR_MEMORY_LIMIT'):self.invoke(loader=loader,max_memory_bytes=0)
        loader.assert_not_called()

    def test_reference_mismatch_and_candidate_matrix_are_rejected(self):
        attribution=Mock();bundles=deepcopy(self.bundles)
        bundles['seven','xgboost',1]['model'].named_steps['preprocess'].named_transformers_['clinical'].named_steps['scale'].mean_[0]+=.1
        with patch.object(study,'checked_baseline',return_value=np.tile([.1,.02],(18,1))):
            with self.assertRaisesRegex(ValueError,'TRAINING_REFERENCE_MISMATCH'):
                study.evaluate(self.frame,self.splits,lambda s,f,k:bundles[s,f,k],self.candidates,self.expected,
                    expected_input_fingerprint=self.fingerprint,expected_subjects=90,shapley=attribution,lime=attribution)
        attribution.assert_not_called()
        with self.assertRaisesRegex(ValueError,'CANDIDATE_MATRIX'):self.invoke(candidates=self.candidates[:-1])

    def test_bad_group_order_and_reconstruction_reject_partial_result(self):
        for bad in ('order','reconstruction'):
            def shap(model,frame,spec,**kwargs):
                value=self.fake_shapley(model,frame,spec,**kwargs)
                if bad=='order':value['group_names']=tuple(reversed(value['group_names']))
                else:value['reference_cif']+=.01
                return value
            with self.assertRaisesRegex(ValueError,'GROUPS_OR_PREDICTION|RECONSTRUCTION'):self.invoke(shapley=shap)

    def test_original_CIF_baseline_and_LIME_MAE_use_only_existing_evaluations(self):
        row,bundle=bundle_for('seven','logistic',1);model=study.checked_outer_bundle(bundle,row)
        frame=frame_for(model,rows=1);output=study.checked_baseline(model,frame,'seven')
        recorded=[];original=table.predict_cif
        def collect(m,current,names):
            result=original(m,current,names);recorded.append((current.copy(),result.iloc[:,1:].to_numpy()))
            return result
        with patch.object(table,'predict_cif',side_effect=collect):value=table.explain_lime(model,frame,'seven')
        self.assertEqual(value['cif_calls'],2);np.testing.assert_allclose(output,value['prediction_cif'],atol=1e-12,rtol=0)
        for index,(states,outcomes) in enumerate(recorded):
            names=list(study.SPECS['seven']);masks=(states[names[:3]].to_numpy()==frame[names[:3]].to_numpy()).astype(float)
            pred=value['surrogate_intercept']+masks@value['contributions'][0,:3]
            weights=np.exp(-np.mean((1-masks)**2,axis=1)/.75**2)
            expected=np.average(np.abs(outcomes-pred),axis=0,weights=weights)
            actual=value['weighted_mae'] if index==0 else value['heldout_fidelity']['weighted_mae']
            np.testing.assert_allclose(expected,actual,atol=1e-15,rtol=0)
        baseline=frame_for(model,rows=1)
        for i,name in enumerate(study.SPECS['seven']):baseline[name]=i+1.5
        value=table.explain_lime(model,baseline,'seven')
        self.assertEqual(value['local_surrogate_fits'],0);self.assertEqual(value['weighted_mae'],[0.,0.])
        self.assertIsNone(value['heldout_fidelity']['weighted_mae'])

    def test_baseline_model_mutation_is_rejected(self):
        model=constructed_model();frame=frame_for(model)
        model.named_steps['hazards'].estimator_.mutate_marker=True
        with self.assertRaisesRegex(ValueError,'INPUT_MODEL_OR_ORDER'):study.checked_baseline(model,frame,'seven')


if __name__=='__main__':unittest.main()
