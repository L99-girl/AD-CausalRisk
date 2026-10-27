"""Manually assigned constructed preprocessing/classifier state; zero fit calls."""
from copy import deepcopy
from itertools import permutations
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer, MissingIndicator
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.pipeline import Pipeline
from sklearn.linear_model import LogisticRegression

from adni_algorithm_candidates import StrictHazards
from research_runtime.estimators import SPECS
from research_runtime import table_explanation as table
from research_runtime.discrete import predict_cif


class ConstructedLinear(LogisticRegression):
    def predict_proba(self,x):
        result=super().predict_proba(x)
        if getattr(self,'mutate_marker',False):self.marker_+=1
        return result


def constructed_model(specification='seven'):
    """Assign explicit artificial state; do not call fit on any component."""
    names=list(SPECS[specification]);n=len(names);indicators=np.array([0,2],dtype=int)
    imputer=SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True)
    imputer.statistics_=np.arange(n,dtype=float)+1.5
    imputer.n_features_in_=n;imputer.feature_names_in_=np.array(names,dtype=object)
    imputer._fit_dtype=np.dtype('float64');imputer._fill_dtype=np.dtype('float64')
    indicator=MissingIndicator(error_on_new=False);indicator.features_=indicators
    indicator._precomputed=True;indicator._n_features=n;imputer.indicator_=indicator
    width=n+len(indicators)
    scaler=StandardScaler();scaler.mean_=np.r_[imputer.statistics_+.25,[.1,.2]]
    scaler.var_=np.full(width,4.);scaler.scale_=np.full(width,2.)
    scaler.n_features_in_=width;scaler.n_samples_seen_=100
    clinical=Pipeline([('impute',imputer),('scale',scaler)])
    month=OneHotEncoder(handle_unknown='ignore');month.categories_=[np.arange(1,25,dtype=float)]
    month.n_features_in_=1;month.feature_names_in_=np.array(['month'],dtype=object)
    month._infrequent_enabled=False;month.drop_idx_=None;month._drop_idx_after_grouping=None;month._n_features_outs=[24]
    preprocess=ColumnTransformer([('clinical',clinical,names),('month',month,['month'])])
    preprocess.transformers_=[('clinical',clinical,names),('month',month,['month'])]
    preprocess.feature_names_in_=np.array(names+['month'],dtype=object);preprocess.n_features_in_=n+1
    preprocess._transformer_to_input_indices={'clinical':list(range(n)),'month':[n],'remainder':[]}
    preprocess._columns=[names,['month']];preprocess._remainder=('remainder','drop',[])
    preprocess.sparse_output_=False;preprocess.output_indices_={'clinical':slice(0,width),'month':slice(width,width+24)}
    classifier=ConstructedLinear();classifier.classes_=np.array([0,1,2]);classifier.n_features_in_=width+24
    classifier.coef_=np.zeros((3,width+24));classifier.coef_[1,:2]=[.15,.07];classifier.coef_[2,1]=.03
    classifier.coef_[1,n:n+2]=[.5,-.2];classifier.coef_[1,width]=.02
    classifier.intercept_=np.array([0.,-3.,-4.]);classifier.n_iter_=np.array([0]);classifier.marker_=0
    hazards=StrictHazards(LogisticRegression());hazards.estimator_=classifier;hazards.classes_=classifier.classes_.copy()
    return Pipeline([('preprocess',preprocess),('hazards',hazards)])


def frame_for(model,specification='seven',reference_kind='median',rows=2):
    names=list(SPECS[specification]);stats=table.training_reference_statistics(model,specification)[reference_kind]
    frame=pd.DataFrame(np.tile(stats,(rows,1)),columns=names)
    frame['subject_id']=['CONSTRUCTED-TABLE-'+str(i) for i in range(rows)]
    frame.loc[:,names[:3]]+=1
    return frame


class TableExplanationTests(unittest.TestCase):
    def test_actual_sklearn_transforms_and_original_cif_with_manual_state(self):
        for spec in ('seven','multimodal_values'):
            model=constructed_model(spec);frame=frame_for(model,spec)
            output=predict_cif(model,frame,list(SPECS[spec]))
            self.assertEqual(output.shape,(2,3));self.assertTrue(np.isfinite(output.iloc[:,1:]).all().all())
            clinical=model.named_steps['preprocess'].named_transformers_['clinical']
            self.assertEqual(clinical.transform(frame[list(SPECS[spec])]).shape,(2,len(SPECS[spec])+2))

    def test_saved_median_and_raw_scale_means_exclude_indicator_means(self):
        for spec in ('seven','multimodal_values'):
            model=constructed_model(spec);frame=frame_for(model,spec)
            names=list(SPECS[spec]);stats=table.training_reference_statistics(model,spec)
            np.testing.assert_array_equal(stats['mean'],np.arange(len(names))+1.75)
            np.testing.assert_array_equal(stats['median'],np.arange(len(names))+1.5)
            np.testing.assert_array_equal(stats['indicator_features'],[0,2])
            for kind in ('median','mean'):
                ref=table.table_reference(model,frame,spec,kind)
                np.testing.assert_array_equal(ref[names].iloc[0],stats[kind])

    def test_missing_indicators_stay_fixed_even_for_new_missing_columns(self):
        model=constructed_model();frame=frame_for(model)
        frame.loc[0,'mmse']=np.nan;frame.loc[0,'cdr_sb']=np.nan
        clinical=model.named_steps['preprocess'].named_transformers_['clinical'];before=clinical.named_steps['impute'].transform(frame[list(SPECS['seven'])])
        for kind in ('median','mean'):
            ref=table.table_reference(model,frame,'seven',kind)
            after=clinical.named_steps['impute'].transform(ref[list(SPECS['seven'])])
            np.testing.assert_array_equal(before[:,7:],after[:,7:])
            np.testing.assert_array_equal(frame[list(SPECS['seven'])].isna(),ref[list(SPECS['seven'])].isna())
            self.assertEqual(after.shape[1],9)

    def test_shapley_matches_independent_permutation_average_on_actual_cif(self):
        for spec in ('seven','multimodal_values'):
            for kind in ('median','mean'):
                model=constructed_model(spec);frame=frame_for(model,spec,kind,rows=1)
                result=table.explain_shapley(model,frame,spec,reference_kind=kind,max_coalitions=8)
                ref=table.table_reference(model,frame,spec,kind);names=list(SPECS[spec]);expected=np.zeros((len(names),2))
                for order in permutations(range(3)):
                    state=ref.copy();previous=predict_cif(model,state,names).iloc[:,1:].to_numpy()[0]
                    for index in order:
                        state.loc[:,names[index]]=frame[names[index]].to_numpy()
                        current=predict_cif(model,state,names).iloc[:,1:].to_numpy()[0]
                        expected[index]+=(current-previous)/6;previous=current
                np.testing.assert_allclose(result['contributions'][0,:3],expected[:3],atol=1e-12,rtol=0)
                np.testing.assert_allclose(result['reference_cif']+result['contributions'].sum(axis=1),result['prediction_cif'],atol=1e-12,rtol=0)
                self.assertEqual(result['cif_calls'],8)

    def test_bilateral_group_and_missing_group_zero_do_not_explain_missingness(self):
        model=constructed_model('multimodal_values');frame=frame_for(model,'multimodal_values')
        frame.loc[:,list(SPECS['multimodal_values'])[2:]]=table.training_reference_statistics(model,'multimodal_values')['median'][2:]
        frame.loc[:,['mri_left_hippocampus_volume','mri_right_hippocampus_volume']]+=1
        frame.loc[1,['mri_left_hippocampus_volume','mri_right_hippocampus_volume']]=np.nan
        result=table.explain_shapley(model,frame,'multimodal_values',max_coalitions=8)
        self.assertEqual(result['group_names'][-1],'bilateral_hippocampus')
        np.testing.assert_array_equal(result['contributions'][1,-1],0)
        self.assertFalse(result['missingness_effects_explained'])
        frame.loc[0,'mri_right_hippocampus_volume']=np.nan
        with self.assertRaisesRegex(ValueError,'BILATERAL'):table.explain_shapley(model,frame,'multimodal_values')

    def test_missingness_can_change_prediction_while_missing_group_contribution_is_zero(self):
        model=constructed_model();frame=frame_for(model,rows=1);frame.loc[:,'age_years']=np.nan
        result=table.explain_shapley(model,frame,'seven',max_coalitions=4)
        np.testing.assert_array_equal(result['contributions'][0,0],0)
        changed=frame.copy();changed.loc[:,'age_years']=1.5
        self.assertFalse(np.array_equal(predict_cif(model,frame,list(SPECS['seven'])).iloc[:,1:].to_numpy(),predict_cif(model,changed,list(SPECS['seven'])).iloc[:,1:].to_numpy()))

    def test_nullable_integer_columns_accept_fractional_training_references_without_mutation(self):
        model=constructed_model();frame=frame_for(model,rows=2)
        frame['age_years']=pd.Series([3,4],dtype='int64');frame['education_years']=pd.Series([4,pd.NA],dtype='Int64')
        snapshot=frame.copy(deep=True);identity=table.model_state_identity(model)
        for kind in ('median','mean'):
            table.explain_shapley(model,frame,'seven',reference_kind=kind,max_coalitions=128)
        pd.testing.assert_frame_equal(frame,snapshot);self.assertEqual(table.model_state_identity(model),identity)

    def test_lime_batch_and_serial_match_including_reserved_disjoint_fidelity(self):
        for spec in ('seven','multimodal_values'):
            for kind in ('median','mean'):
                model=constructed_model(spec);frame=frame_for(model,spec,kind,rows=1)
                serial=table.explain_lime(model,frame,spec,reference_kind=kind,batch_predictions=False)
                batches=[];original=table.predict_cif
                def capture(model,current,names):batches.append(current.copy());return original(model,current,names)
                with patch.object(table,'predict_cif',side_effect=capture):
                    batch=table.explain_lime(model,frame,spec,reference_kind=kind,batch_predictions=True)
                self.assertEqual((serial['cif_calls'],batch['cif_calls']),(8,2))
                self.assertEqual(batch['actual_fit_sample_budget'],4);self.assertEqual(batch['heldout_fidelity']['samples'],4)
                self.assertEqual(serial['mask_sha256'],batch['mask_sha256'])
                for key in ('contributions','prediction_cif','reference_cif','observed_residual'):
                    np.testing.assert_allclose(serial[key],batch[key],atol=1e-12,rtol=0)
                sets=[set(map(tuple,x[list(SPECS[spec])[:3]].to_numpy())) for x in batches]
                self.assertFalse(sets[0]&sets[1]);self.assertTrue(all(x.subject_id.is_unique for x in batches))

    def test_lime_small_and_constant_games_keep_undefined_holdout(self):
        model=constructed_model();frame=frame_for(model,rows=1)
        stats=table.training_reference_statistics(model,'seven')['median']
        for i,name in enumerate(SPECS['seven']):frame[name]=stats[i]
        result=table.explain_lime(model,frame,'seven')
        self.assertEqual((result['active_group_count'],result['local_surrogate_fits'],result['cif_calls']),(0,0,1))
        self.assertEqual(result['heldout_fidelity']['samples'],0)
        frame['age_years']+=1;result=table.explain_lime(model,frame,'seven')
        self.assertEqual(result['actual_fit_sample_budget'],2);self.assertEqual(result['heldout_fidelity']['samples'],0)

    def test_lime_reserve_rule_is_fixed_from_active_groups_before_prediction(self):
        model=constructed_model();frame=frame_for(model,rows=1)
        for i,name in enumerate(SPECS['seven']):frame[name]=i+2.5
        result=table.explain_lime(model,frame,'seven')
        self.assertEqual((result['active_group_count'],result['actual_fit_sample_budget'],result['heldout_fidelity']['samples']),(7,64,32))
        self.assertEqual(result['cif_state_rows'],96)

    def test_all_nine_groups_reach_exact_512_coalition_boundary(self):
        model=constructed_model('multimodal_values')
        frame=frame_for(model,'multimodal_values',rows=1)
        for i,name in enumerate(SPECS['multimodal_values']):frame[name]=i+2.5
        result=table.explain_shapley(model,frame,'multimodal_values',max_coalitions=512)
        self.assertEqual((result['cif_calls'],result['cif_state_rows']),(512,512))
        self.assertEqual(result['contributions'].shape,(1,9,2))
        np.testing.assert_allclose(result['reference_cif']+result['contributions'].sum(axis=1),result['prediction_cif'],atol=1e-12,rtol=0)

    def test_budgets_reject_before_any_cif_and_do_not_fit(self):
        model=constructed_model();frame=frame_for(model,rows=1)
        with patch.object(table,'predict_cif') as predict:
            with self.assertRaisesRegex(ValueError,'BUDGET'):table.explain_shapley(model,frame,'seven',max_coalitions=4)
            with self.assertRaisesRegex(ValueError,'BUDGET'):table.explain_lime(model,frame,'seven',max_evaluations=4)
            predict.assert_not_called()

    def test_unsupported_or_malformed_preprocessor_is_not_replaced(self):
        cases=[lambda m:setattr(m.named_steps['preprocess'].named_transformers_['clinical'].named_steps['impute'],'add_indicator',False),
               lambda m:setattr(m.named_steps['preprocess'].named_transformers_['clinical'].named_steps['impute'],'statistics_',np.full(7,np.nan)),
               lambda m:setattr(m.named_steps['preprocess'].named_transformers_['clinical'].named_steps['scale'],'mean_',np.zeros(7)),
               lambda m:m.named_steps['preprocess'].transformers_[0][2].reverse()]
        for change in cases:
            model=constructed_model();frame=frame_for(model);change(model)
            with patch.object(table,'predict_cif') as predict:
                with self.assertRaises(ValueError):table.explain_shapley(model,frame,'seven')
                predict.assert_not_called()
        with self.assertRaisesRegex(ValueError,'VALUE_SPECIFICATION'):table.groups_for('modality_availability')

    def test_actual_mutated_pipeline_state_and_cif_input_or_order_are_rejected(self):
        model=constructed_model();frame=frame_for(model);model.named_steps['hazards'].estimator_.mutate_marker=True
        with self.assertRaisesRegex(ValueError,'MODEL_CHANGED'):table.explain_shapley(model,frame,'seven',max_coalitions=8)
        for mutation in ('input','order'):
            model=constructed_model();original=table.predict_cif
            def callback(m,current,names):
                result=original(m,current,names)
                if mutation=='input':current.loc[:,'mmse']=0
                else:result=result.iloc[::-1]
                return result
            with patch.object(table,'predict_cif',side_effect=callback):
                with self.assertRaisesRegex(ValueError,'ORDER_CHANGED'):table.explain_shapley(model,frame,'seven',max_coalitions=8)

    def test_invalid_frame_values_and_duplicate_subjects_are_rejected(self):
        for mutate in (lambda f:f.assign(age_years=True),lambda f:f.assign(age_years='3'),
                       lambda f:f.assign(age_years=np.inf),lambda f:f.assign(age_years=3+1j),lambda f:f.assign(age_years=2**53+1),
                       lambda f:f.assign(subject_id='DUPLICATE')):
            model=constructed_model();frame=mutate(frame_for(model))
            with self.assertRaises(ValueError):table.explain_shapley(model,frame,'seven')


if __name__=='__main__':unittest.main()
