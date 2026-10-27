"""Fixed table OOF attribution study: caller-bound memory, aggregates only.

No files, deserialization, predictive fitting, deployment or authorization.
Reuses existing aggregation helpers in the pinned graph-capable environment;
their import does not run graph models, optimizers or graph explanations.
"""
from itertools import combinations
import re
import time

import numpy as np
from sklearn.pipeline import Pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from threadpoolctl import threadpool_limits

from adni_algorithm_candidates import StrictHazards
from . import table_explanation as table
from .discrete import predict_cif
from .estimators import SPECS, FAMILIES
from .training import checked_design, input_fingerprint, prediction_hash
from .evaluation import censor_survival, horizon_ipcw_weights
from .grouped_xai_study import distribution, paired, CONFIGS, REFERENCES
from .graph_acceptance import peak_memory_bytes

SPECIFICATIONS = ('seven','multimodal_values')


def checked_outer_bundle(bundle, candidate):
    """Validate already-deserialized outer metadata against a caller-pinned row.

    The caller must verify trusted archive bytes BEFORE deserialization. A valid
    metadata declaration alone does not attest the archive, rows or model.
    """
    spec=candidate.get('specification');family=candidate.get('family');fold=candidate.get('outer_fold')
    if (spec not in SPECIFICATIONS or family not in FAMILIES or type(fold) is not int or not 1<=fold<=5
            or not isinstance(candidate.get('plan_sha256'),str)
            or re.fullmatch(r'[0-9a-f]{64}',candidate['plan_sha256']) is None
            or not isinstance(bundle,dict)):
        raise ValueError('TABLE_OUTER_CANDIDATE')
    role='NESTED_OUTER_RESEARCH_VALIDATION' if spec=='seven' else 'MULTIMODAL_OUTER_VALIDATION'
    key='training_plan_sha256' if spec=='seven' else 'plan_sha256'
    if (candidate.get('role')!=role or candidate.get('clinical_use') is not False
            or bundle.get('role')!=role or bundle.get('family')!=family or bundle.get('outer_fold')!=fold
            or type(bundle.get('outer_fold')) is not int or bundle.get('columns')!=list(SPECS[spec])
            or bundle.get(key)!=candidate.get('plan_sha256') or bundle.get('clinical_use') is not False):
        raise ValueError('TABLE_OUTER_IDENTITY')
    if spec=='multimodal_values' and (bundle.get('arm')!=spec or bundle.get('retrospective_only') is not True
            or bundle.get('prediction_policy')!='raw_uncalibrated_24month_CIF'):
        raise ValueError('TABLE_OUTER_RAW_POLICY')
    model=bundle.get('model');table.training_reference_statistics(model,spec)
    hazard=model.named_steps['hazards']
    if not isinstance(hazard,StrictHazards):raise ValueError('TABLE_ORIGINAL_HAZARDS_REQUIRED')
    if family=='xgboost':
        from xgboost import XGBClassifier
        expected=XGBClassifier
    else:expected=LogisticRegression if family=='logistic' else RandomForestClassifier
    if not isinstance(getattr(hazard,'estimator_',None),expected):
        raise ValueError('TABLE_OUTER_ESTIMATOR_FAMILY')
    return model


def checked_original_folds(frame, private):
    """Keep the original stored position AND subject sequences; never resample."""
    if not isinstance(private,list) or len(private)!=5:raise ValueError('TABLE_ORIGINAL_FIVE_FOLDS')
    splits=[]
    for row in private:
        if not isinstance(row,dict):raise ValueError('TABLE_ORIGINAL_FOLD_SCHEMA')
        a,b=row.get('train_positions'),row.get('test_positions')
        if (not isinstance(a,list) or not isinstance(b,list) or not a or not b
                or any(type(x) is not int or not 0<=x<len(frame) for x in a+b)):
            raise ValueError('TABLE_ORIGINAL_FOLD_POSITIONS')
        if (frame.iloc[a].subject_id.tolist()!=row.get('train_subjects')
                or frame.iloc[b].subject_id.tolist()!=row.get('test_subjects')):
            raise ValueError('TABLE_ORIGINAL_FOLD_SUBJECTS')
        splits.append((np.asarray(a),np.asarray(b)))
    return checked_design(frame,'multimodal_values',splits)[1]


def checked_baseline(model, frame, specification):
    original=frame.copy(deep=True);identity=table.model_state_identity(model)
    with threadpool_limits(limits=1):result=predict_cif(model,frame,list(SPECS[specification]))
    if (not original.equals(frame) or identity!=table.model_state_identity(model)
            or result.subject_id.tolist()!=frame.subject_id.tolist()):
        raise ValueError('TABLE_BASELINE_INPUT_MODEL_OR_ORDER')
    values=result[['ad_cif_24m','other_dementia_cif_24m']].to_numpy(float)
    if (values.shape!=(len(frame),2) or not np.isfinite(values).all() or (values<0).any()
            or (values>1).any() or (values.sum(axis=1)>1+1e-12).any()):
        raise ValueError('TABLE_BASELINE_TWO_CAUSE_CIF')
    return values


def _masks(frame, model, specification, reference):
    current,groups=table._frame(frame,specification)
    baseline=table.table_reference(model,frame,specification,reference)
    names=list(SPECS[specification]);x=current[names].to_numpy();r=baseline[names].to_numpy()
    observed=np.column_stack([~np.isnan(x[:,list(cols)]).any(axis=1) for _,cols in groups])
    same=(x==r)|(np.isnan(x)&np.isnan(r))
    active=np.column_stack([~same[:,list(cols)].all(axis=1) for _,cols in groups])
    return observed,active


def evaluate(frame, splits, loader, candidates, expected_AD, *, expected_input_fingerprint,
             expected_subjects=1160,max_cif_calls=21630,max_state_rows=4576560,max_local_fits=1200,
             max_elapsed_seconds=7200,max_memory_bytes=2147483648,
             shapley=table.explain_shapley,lime=table.explain_lime,progress=None):
    """Run all six OOF gates first; fail without a partial scientific result.

    ``loader(specification,family,fold)`` returns one caller-verified outer
    bundle. The trusted host handles exact bytes, authorization and hard caps.
    Constructed callers may use smaller cohorts, with identical fixed matrix.
    """
    started=time.perf_counter();original=frame.copy(deep=True)
    work,splits,_=checked_design(frame,'multimodal_values',splits)
    if (len(work)!=expected_subjects or input_fingerprint(work,'multimodal_values')!=expected_input_fingerprint):
        raise ValueError('TABLE_STUDY_INPUT_FINGERPRINT')
    if any(not 10<=len(b)<=256 for _,b in splits):raise ValueError('TABLE_STUDY_TEST_FOLD_SIZE')
    keys={(spec,family,fold) for spec in SPECIFICATIONS for family in FAMILIES for fold in range(1,6)}
    index={(x['specification'],x['family'],x['outer_fold']):x for x in candidates}
    if len(candidates)!=30 or set(index)!=keys:raise ValueError('TABLE_STUDY_CANDIDATE_MATRIX')
    for spec in SPECIFICATIONS:
        if (set(expected_AD.get(spec,{}))!=set(FAMILIES)|{'historical_other_cause_OOF_hash'}
                or expected_AD[spec]['historical_other_cause_OOF_hash'] is not None):
            raise ValueError('TABLE_HISTORICAL_AD_ONLY_EVIDENCE_REQUIRED')
        for family in FAMILIES:
            e=expected_AD[spec][family]
            if (not isinstance(e.get('oof_prediction_sha256'),str) or len(e['oof_prediction_sha256'])!=64
                    or type(e.get('pooled_oof_brier')) not in (int,float) or not np.isfinite(e['pooled_oof_brier'])):
                raise ValueError('TABLE_OOF_EXPECTATION')
    counters=dict(cif_calls=0,cif_state_rows=0,local_surrogate_fits=0)
    def reserve(calls,rows,fits=0):
        if (counters['cif_calls']+calls>max_cif_calls or counters['cif_state_rows']+rows>max_state_rows
                or counters['local_surrogate_fits']+fits>max_local_fits):
            raise ValueError('TABLE_STUDY_BUDGET_EXCEEDED')
        if time.perf_counter()-started>max_elapsed_seconds or peak_memory_bytes()>max_memory_bytes:
            raise ValueError('TABLE_STUDY_TIME_OR_MEMORY_LIMIT')
    def charge(calls,rows,fits=0):
        if any(type(x) is not int or x<0 for x in (calls,rows,fits)):raise ValueError('TABLE_OPERATION_COUNTER')
        reserve(calls,rows,fits)
        for key,value in zip(counters,(calls,rows,fits)):counters[key]+=value
    def event(phase,**labels):
        if progress:progress(dict(phase=phase,**labels,**counters))
    models={};identities={};raw={(s,f):np.empty((len(work),2)) for s in SPECIFICATIONS for f in FAMILIES}
    weights=np.empty(len(work));target=work.event_type.eq(1).to_numpy(float)
    for fold,(train,test) in enumerate(splits,1):
        weights[test]=horizon_ipcw_weights(work.iloc[test],censor_survival(work.iloc[train]))
        for spec in SPECIFICATIONS:
            for family in FAMILIES:
                reserve(1,len(test))
                model=checked_outer_bundle(loader(spec,family,fold),index[spec,family,fold])
                models[spec,family,fold]=model;identities[spec,family,fold]=table.model_state_identity(model)
                table._frame(work.iloc[test],spec)
                raw[spec,family][test]=checked_baseline(model,work.iloc[test],spec);charge(1,len(test))
                event('BASELINE',specification=spec,family=family,fold=fold)
            reference=table.training_reference_statistics(models[spec,FAMILIES[0],fold],spec)
            for family in FAMILIES[1:]:
                other=table.training_reference_statistics(models[spec,family,fold],spec)
                if any(not np.array_equal(reference[k],other[k]) for k in ('median','mean','indicator_features')):
                    raise ValueError('TABLE_FAMILY_TRAINING_REFERENCE_MISMATCH')
    if any(len({id(getter(m)) for m in models.values()})!=30 for getter in (
            lambda m:m,lambda m:m.named_steps['preprocess'],lambda m:m.named_steps['hazards'].estimator_)):
        raise ValueError('TABLE_MODEL_OBJECT_REUSE')
    for (spec,family),values in raw.items():
        expected=expected_AD[spec][family]
        if prediction_hash(values[:,0])!=expected['oof_prediction_sha256']:raise ValueError('TABLE_AD_OOF_CHANGED')
        if abs(float(np.mean(weights*(target-values[:,0])**2))-expected['pooled_oof_brier'])>1e-12:
            raise ValueError('TABLE_AD_BRIER_CHANGED')
    event('ALL_SIX_AD_OOF_VERIFIED')
    rng=np.random.default_rng(20261027)
    selected=[np.sort(rng.choice(test,10,replace=False)) for _,test in splits]
    subset=np.concatenate(selected);slot={int(p):i for i,p in enumerate(subset)}
    observed={};active={};shap={};local={};fidelity={};maximum=0.
    for spec in SPECIFICATIONS:
        g=len(table.groups_for(spec));observed[spec]=np.empty((len(work),g),dtype=bool)
        for ref in REFERENCES:
            active[spec,ref]=np.empty((len(work),g),dtype=bool)
            for family in FAMILIES:shap[spec,family,ref]=np.empty((len(work),g,2))
        for family in FAMILIES:
            for name,*_ in CONFIGS:
                local[spec,family,name]=np.empty((50,g,2));fidelity[spec,family,name]=[]
    def checked_value(value,spec,part,baseline,is_shap):
        g=len(table.groups_for(spec));names=tuple(n for n,_ in table.groups_for(spec))
        v=np.asarray(value['contributions']);out=np.asarray(value['prediction_cif'])
        if (tuple(value['group_names'])!=names or v.shape!=(len(part),g,2) or out.shape!=baseline.shape
                or not np.isfinite(v).all() or not np.isfinite(out).all()
                or np.max(np.abs(out-baseline))>1e-12):raise ValueError('TABLE_XAI_GROUPS_OR_PREDICTION')
        mask=np.column_stack([part[list(SPECS[spec])[cols[0]]].notna().to_numpy() for _,cols in table.groups_for(spec)])
        if np.any(v[~mask]!=0):raise ValueError('TABLE_XAI_MISSING_GROUP_CONTRIBUTION')
        if is_shap:
            err=float(np.max(np.abs(np.asarray(value['reference_cif'])+v.sum(axis=1)-baseline)))
            if not np.isfinite(err) or err>1e-12:raise ValueError('TABLE_SHAPLEY_RECONSTRUCTION')
            return v,err
        return v,0.
    for fold,(_,test) in enumerate(splits,1):
        part=work.iloc[test]
        for spec in SPECIFICATIONS:
            limit=128 if spec=='seven' else 512
            for ref in REFERENCES:
                obs,act=_masks(part,models[spec,FAMILIES[0],fold],spec,ref)
                observed[spec][test]=obs;active[spec,ref][test]=act
            for family in FAMILIES:
                model=models[spec,family,fold]
                for ref in REFERENCES:
                    reserve(limit,len(test)*limit)
                    value=shapley(model,part,spec,reference_kind=ref,max_coalitions=limit)
                    v,err=checked_value(value,spec,part,raw[spec,family][test],True)
                    maximum=max(maximum,err);shap[spec,family,ref][test]=v
                    charge(value['cif_calls'],value['cif_state_rows'])
                    event('SHAPLEY',specification=spec,family=family,fold=fold,reference=ref)
                for position in selected[fold-1]:
                    for name,ref,seed,width in CONFIGS:
                        reserve(2,96,1)
                        value=lime(model,work.iloc[[position]],spec,reference_kind=ref,seed=seed,
                            kernel_width=width,samples=64,ridge=1e-6,holdout_samples=32,
                            reserve_holdout=True,batch_predictions=True,max_evaluations=96)
                        v,_=checked_value(value,spec,work.iloc[[position]],raw[spec,family][[position]],False)
                        local[spec,family,name][slot[int(position)]]=v[0]
                        fidelity[spec,family,name].append((slot[int(position)],value))
                        charge(value['cif_calls'],value['cif_state_rows'],value['local_surrogate_fits'])
                if table.model_state_identity(model)!=identities[spec,family,fold]:raise ValueError('TABLE_STUDY_MODEL_CHANGED')
                event('FOLD_MODEL_COMPLETE',specification=spec,family=family,fold=fold)
    importance=[]
    for (spec,family,ref),values in shap.items():
        for fold,positions in [(None,np.arange(len(work))),*[(i,b) for i,(_,b) in enumerate(splits,1)]]:
            rows=values[positions];obs=observed[spec][positions]
            importance.append(dict(specification=spec,family=family,reference=ref,outer_fold=fold,subjects=len(positions),
                groups=[dict(group=name,observed_subjects=int(obs[:,i].sum()),
                    mean_signed=rows[:,i].mean(axis=0).tolist(),mean_absolute=np.abs(rows[:,i]).mean(axis=0).tolist(),
                    observed_mean_absolute=np.abs(rows[obs[:,i],i]).mean(axis=0).tolist() if obs[:,i].any() else None)
                    for i,(name,_) in enumerate(table.groups_for(spec))]))
    sensitivity=[]
    def compare(kind,spec,left,right,mask,**labels):
        for cause in (0,1):
            sensitivity.append(dict(kind=kind,specification=spec,cause='AD' if cause==0 else 'OTHER_DEMENTIA',
                **labels,**paired(left[:,:,cause],right[:,:,cause],mask)))
    for spec in SPECIFICATIONS:
        for ref in REFERENCES:
            for a,b in combinations(FAMILIES,2):compare('shapley_algorithms',spec,shap[spec,a,ref],shap[spec,b,ref],active[spec,ref],reference=ref,families=[a,b])
        for family in FAMILIES:
            compare('shapley_reference',spec,shap[spec,family,'median'],shap[spec,family,'mean'],active[spec,'median']&active[spec,'mean'],family=family)
            compare('matched_methods',spec,shap[spec,family,'median'][subset],local[spec,family,'base'],active[spec,'median'][subset],family=family)
            for name,ref,_,_ in CONFIGS[1:]:compare('lime_configuration',spec,local[spec,family,'base'],local[spec,family,name],(active[spec,'median']&active[spec,ref])[subset],family=family,configuration=name)
        for name,ref,_,_ in CONFIGS:
            for a,b in combinations(FAMILIES,2):compare('lime_algorithms',spec,local[spec,a,name],local[spec,b,name],active[spec,ref][subset],configuration=name,families=[a,b])
    fits=[];eligibility=[]
    for (spec,family,name),rows in fidelity.items():
        for cause in (0,1):
            held=[r['heldout_fidelity'] for _,r in rows if r['heldout_fidelity']['samples']]
            residual=[abs(float(r['observed_residual'][0,cause])) for _,r in rows]
            rmse=[r['weighted_rmse'][cause] for r in held]
            fits.append(dict(specification=spec,family=family,configuration=name,cause='AD' if cause==0 else 'OTHER_DEMENTIA',
                subjects=len(rows),heldout_eligible_subjects=len(held),undefined_heldout_subjects=len(rows)-len(held),
                neighborhood_RMSE=distribution([r['weighted_rmse'][cause] for _,r in rows]),
                neighborhood_MAE=distribution([r['weighted_mae'][cause] for _,r in rows]),
                neighborhood_R2=distribution([r['weighted_r2'][cause] for _,r in rows]),
                observed_absolute_residual=distribution(residual),observed_residual_over_001=int(sum(x>.01 for x in residual)),
                heldout_RMSE=distribution(rmse),heldout_RMSE_over_001=int(sum(x>.01 for x in rmse)),
                heldout_MAE=distribution([r['weighted_mae'][cause] for r in held]),
                heldout_R2=distribution([r['weighted_r2'][cause] for r in held])))
    for spec in SPECIFICATIONS:
        for name,*_ in CONFIGS:
            eligible=[{i for i,r in fidelity[spec,f,name] if r['heldout_fidelity']['samples']} for f in FAMILIES]
            eligibility.append(dict(specification=spec,configuration=name,selected_unique_people=50,person_model_pairs=150,
                heldout_eligible_person_model_pairs=sum(len(x) for x in eligible),
                unique_people_with_any_heldout=len(set.union(*eligible)),unique_people_with_all_three_heldout=len(set.intersection(*eligible))))
    reserve(0,0)
    if (not frame.equals(original) or input_fingerprint(work,'multimodal_values')!=expected_input_fingerprint
            or any(table.model_state_identity(models[k])!=v for k,v in identities.items())):
        raise ValueError('TABLE_STUDY_INPUT_OR_MODEL_CHANGED')
    return dict(status='FIXED_TABLE_GROUPED_XAI_COMPLETE',subjects=len(work),outer_model_loads=30,
        shapley_model_reference_applications=60,lime_subject_model_config_applications=1200,
        lime_subset_unique_people=50,all_six_AD_OOF_and_Brier_verified=True,historical_other_cause_OOF_hash_verified=False,
        importance=importance,sensitivity=sensitivity,lime_fidelity=fits,lime_heldout_eligibility=eligibility,
        shapley_reconstruction_max_error=maximum,operations=counters,predictive_fits=0,calibration_fits=0,preprocessing_fits=0,
        participant_outputs_saved=False,individual_causal_effect_identified=False,clinical_use=False,independent_validation=False,
        elapsed_seconds=time.perf_counter()-started,peak_memory_bytes=peak_memory_bytes())
