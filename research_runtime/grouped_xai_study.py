"""Fixed prior-model OOF attribution study; in-memory inputs, aggregate outputs.

No file readers, fitting of risk models, model selection or case persistence.
Callers must bind the reviewed input/folds/model manifest before invoking this.
"""
from itertools import combinations
import time

import numpy as np

from . import group_lime, group_shapley
from .graph_explanation import GROUPS, model_identity, observation_groups, rank
from .graph_training import checked_cif
from .graph_acceptance import peak_memory_bytes
from .training import checked_design, input_fingerprint, prediction_hash
from .evaluation import censor_survival, horizon_ipcw_weights


SEEDS = (20260926, 20260927, 20260928)
REFERENCES = ('median', 'mean')
CONFIGS = (
    ('base', 'median', 20261027, .75),
    ('sampling_seed', 'median', 20261028, .75),
    ('kernel_width', 'median', 20261027, .30),
    ('reference', 'mean', 20261027, .75),
)


def distribution(values):
    a = np.asarray([x for x in values if x is not None], dtype=float)
    if not len(a):
        return dict(n=0, mean=None, median=None, p05=None, p95=None)
    if not np.isfinite(a).all():
        raise ValueError('NONFINITE_XAI_AGGREGATE')
    return dict(n=len(a), mean=float(a.mean()), median=float(np.median(a)),
                p05=float(np.quantile(a, .05)), p95=float(np.quantile(a, .95)))


def paired(left, right, observed):
    rhos = []; tops = []; insufficient = constant = ties = flips = eligible = 0
    for a, b, mask in zip(left, right, observed):
        if mask.sum() < 3:
            insufficient += 1
        else:
            rho = rank(np.abs(a[mask]), np.abs(b[mask]))
            if rho is None: constant += 1
            else: rhos.append(rho)
            aa, bb = np.abs(a[mask]), np.abs(b[mask])
            if (np.isclose(aa, aa.max(), atol=1e-12, rtol=0).sum() != 1
                    or np.isclose(bb, bb.max(), atol=1e-12, rtol=0).sum() != 1):
                ties += 1
            else:
                tops.append(int(np.argmax(aa) == np.argmax(bb)))
        usable = mask & (np.abs(a) > 1e-6) & (np.abs(b) > 1e-6)
        eligible += int(usable.sum()); flips += int((np.sign(a[usable]) != np.sign(b[usable])).sum())
    return dict(subjects=len(left), spearman=distribution(rhos), insufficient_groups=insufficient,
                constant_ranks=constant, top_rank_ties=ties, top_rank_eligible=len(tops),
                top_rank_agreement=float(np.mean(tops)) if tops else None,
                signed_L1=distribution(np.abs(left-right).sum(axis=1)),
                sign_flip_groups=flips, sign_eligible_groups=eligible)


def evaluate(frame, splits, loader, expected_prior, *, expected_input_fingerprint,
             max_cif_calls=16575, max_local_fits=600, max_state_rows=3663000,
             max_elapsed_seconds=7200, max_memory_bytes=2147483648,
             shapley=group_shapley.explain_graph, lime=group_lime.explain_graph, progress=None):
    """Verify all original OOF outputs first, then run the fixed method matrix.

    ``loader(seed, fold)`` supplies each previously verified prior outer model
    once. No final/other-arm model is accepted. Source byte/manifest binding and
    the one permitted input read belong to the controlled caller, not this API.
    Exceptions yield no result; caller must retain its failed execution ledger.
    """
    started = time.perf_counter()
    work, splits, _ = checked_design(frame, 'multimodal_values', splits)
    if input_fingerprint(work, 'multimodal_values') != expected_input_fingerprint:
        raise ValueError('XAI_INPUT_FINGERPRINT_MISMATCH')
    if (expected_prior.get('arm') != 'prior' or len(expected_prior['per_seed']) != 3
            or {r['seed'] for r in expected_prior['per_seed']} != set(SEEDS)):
        raise ValueError('XAI_PRIOR_BASELINE_REQUIRED')
    counters = dict(cif_calls=0, cif_state_rows=0, local_surrogate_fits=0)

    def reserve(calls, states, fits=0):
        if (counters['cif_calls']+calls > max_cif_calls
                or counters['cif_state_rows']+states > max_state_rows
                or counters['local_surrogate_fits']+fits > max_local_fits):
            raise ValueError('XAI_STUDY_BUDGET_EXCEEDED')
        if time.perf_counter()-started > max_elapsed_seconds or peak_memory_bytes() > max_memory_bytes:
            raise ValueError('XAI_STUDY_TIME_OR_MEMORY_LIMIT')

    def charge(calls, states, fits=0):
        reserve(calls, states, fits)
        counters['cif_calls'] += calls; counters['cif_state_rows'] += states
        counters['local_surrogate_fits'] += fits

    models = {}; identities = {}; raw = {s:np.empty((len(work), 2)) for s in SEEDS}
    weights = np.empty(len(work)); target = work.event_type.eq(1).to_numpy(float)
    for fold, (train, test) in enumerate(splits, 1):
        weights[test] = horizon_ipcw_weights(work.iloc[test], censor_survival(work.iloc[train]))
        for seed in SEEDS:
            model = loader(seed, fold)
            e = model.named_steps['hazards']
            if e.arm != 'prior' or e.seed != seed:
                raise ValueError('XAI_WRONG_MODEL_ROLE_OR_SEED')
            identities[seed, fold] = model_identity(model)
            models[seed, fold] = model
            reserve(1, len(test)); raw[seed][test] = checked_cif(model, work.iloc[test])
            charge(1, len(test))
            if progress: progress(dict(phase='BASELINE', fold=fold, model_seed=seed, **counters))
        for name in ('medians_', 'mean_'):
            if not all(np.array_equal(getattr(models[SEEDS[0], fold].named_steps['hazards'], name),
                                      getattr(models[s, fold].named_steps['hazards'], name)) for s in SEEDS[1:]):
                raise ValueError('XAI_SEED_TRAINING_REFERENCE_MISMATCH')
    # All seed-level hashes and Brier must pass before any explanation.
    if len({id(m) for m in models.values()}) != 15:
        raise ValueError('XAI_REUSED_MODEL_OBJECT_ACROSS_FOLDS_OR_SEEDS')
    for item in expected_prior['per_seed']:
        values = raw[item['seed']]
        if prediction_hash(values[:, 0]) != item['ad_oof_sha256'] or prediction_hash(values[:, 1]) != item['other_oof_sha256']:
            raise ValueError('XAI_SEED_OOF_CHANGED')
        if abs(np.mean(weights*(target-values[:, 0])**2)-item['pooled_oof_brier']) > 1e-12:
            raise ValueError('XAI_SEED_BRIER_CHANGED')
    ensemble = np.stack(list(raw.values())).mean(axis=0)
    if (prediction_hash(ensemble[:, 0]) != expected_prior['ad_oof_sha256']
            or prediction_hash(ensemble[:, 1]) != expected_prior['other_oof_sha256']
            or abs(np.mean(weights*(target-ensemble[:, 0])**2)-expected_prior['pooled_oof_brier']) > 1e-12):
        raise ValueError('XAI_ENSEMBLE_OOF_CHANGED')
    if progress: progress(dict(phase='ALL_OOF_VERIFIED', **counters))

    rng = np.random.default_rng(20261027)
    selected = [np.sort(rng.choice(test, 10, replace=False)) for _, test in splits]
    subset = np.concatenate(selected); subset_slot = {int(p):i for i, p in enumerate(subset)}
    observed = observation_groups(work)
    shap = {(r,s):np.empty((len(work),9,2)) for r in REFERENCES for s in SEEDS}
    local = {(c[0],s):np.empty((len(subset),9,2)) for c in CONFIGS for s in SEEDS}
    fidelity = {(c[0],s):[] for c in CONFIGS for s in SEEDS}
    max_error = 0.
    for fold, (_, test) in enumerate(splits, 1):
        part = work.iloc[test]
        for seed in SEEDS:
            model = models[seed, fold]
            for reference in REFERENCES:
                reserve(512, len(test)*512)
                value = shapley(model, part, reference_kind=reference)
                if value['group_names'] != tuple(n for n, _ in GROUPS):
                    raise ValueError('XAI_GROUP_ORDER_CHANGED')
                contributions = np.asarray(value['contributions'])
                error = max(float(np.max(np.abs(value['prediction_cif']-raw[seed][test]))),
                            float(np.max(np.abs(value['reference_cif']+contributions.sum(axis=1)-raw[seed][test]))))
                if (contributions.shape != (len(test),9,2) or not np.isfinite(contributions).all()
                        or error > 1e-12 or np.any(contributions[~observed[test]] != 0)):
                    raise ValueError('XAI_SHAPLEY_FAITHFULNESS_OR_MISSINGNESS')
                max_error = max(max_error,error); shap[reference,seed][test] = contributions
                charge(value['cif_calls'], len(test)*value['coalition_evaluations'])
                if progress: progress(dict(phase='SHAPLEY',fold=fold,model_seed=seed,reference=reference,**counters))
            for position in selected[fold-1]:
                for name, reference, sampling_seed, width in CONFIGS:
                    reserve(2,160,1)
                    value = lime(model,work.iloc[[position]],reference_kind=reference,
                                 seed=sampling_seed,kernel_width=width,samples=128,
                                 ridge=1e-6,batch_predictions=True,holdout_samples=32)
                    if value['group_names'] != tuple(n for n, _ in GROUPS):
                        raise ValueError('XAI_GROUP_ORDER_CHANGED')
                    contributions = np.asarray(value['contributions'])
                    if (contributions.shape != (1,9,2) or not np.isfinite(contributions).all()
                            or np.max(np.abs(value['prediction_cif']-raw[seed][position])) > 1e-12
                            or np.any(contributions[0,~observed[position]] != 0)):
                        raise ValueError('XAI_LIME_INPUT_OR_MISSINGNESS')
                    local[name,seed][subset_slot[int(position)]] = contributions[0]
                    fidelity[name,seed].append(value)
                    charge(value['cif_calls'],value['neighborhood_evaluations']+value['heldout_fidelity']['samples'],value['local_surrogate_fits'])
            if model_identity(model) != identities[seed,fold]:
                raise ValueError('XAI_MODEL_CHANGED')
            if progress: progress(dict(phase='FOLD_MODEL_COMPLETE',fold=fold,model_seed=seed,**counters))

    importance = []
    for (reference,seed), values in shap.items():
        importance.append(dict(reference=reference,model_seed=seed,groups=[dict(
            group=name,observed_subjects=int(observed[:,i].sum()),
            mean_signed=values[:,i].mean(axis=0).tolist(),mean_abs=np.abs(values[:,i]).mean(axis=0).tolist(),
            observed_mean_abs=np.abs(values[observed[:,i],i]).mean(axis=0).tolist() if observed[:,i].any() else None)
            for i,(name,_) in enumerate(GROUPS)]))
    comparisons = []
    def add(kind,left,right,mask,**labels):
        for cause in (0,1):
            comparisons.append(dict(kind=kind,cause='AD' if cause == 0 else 'OTHER_DEMENTIA',**labels,**paired(left[:,:,cause],right[:,:,cause],mask)))
    for reference in REFERENCES:
        for a,b in combinations(SEEDS,2):add('shapley_model_seed',shap[reference,a],shap[reference,b],observed,reference=reference,seeds=[a,b])
    for seed in SEEDS:
        add('shapley_reference',shap['median',seed],shap['mean',seed],observed,model_seed=seed)
        add('matched_methods',shap['median',seed][subset],local['base',seed],observed[subset],model_seed=seed)
        for name,_,_,_ in CONFIGS[1:]:add('lime_configuration',local['base',seed],local[name,seed],observed[subset],model_seed=seed,configuration=name)
    for name,_,_,_ in CONFIGS:
        for a,b in combinations(SEEDS,2):add('lime_model_seed',local[name,a],local[name,b],observed[subset],configuration=name,seeds=[a,b])
    fits = []
    for (name,seed), rows in fidelity.items():
        for cause in (0,1):
            residual = [abs(r['observed_residual'][0,cause]) for r in rows]
            heldout = [r['heldout_fidelity']['weighted_rmse'][cause] for r in rows if r['heldout_fidelity']['samples']]
            fits.append(dict(configuration=name,model_seed=seed,cause='AD' if cause == 0 else 'OTHER_DEMENTIA',subjects=len(rows),
                neighborhood_R2=distribution([r['weighted_r2'][cause] for r in rows]),
                observed_absolute_residual=distribution(residual),observed_residual_over_001=int(sum(x>.01 for x in residual)),
                heldout_RMSE=distribution(heldout),heldout_RMSE_over_001=int(sum(x>.01 for x in heldout)),
                heldout_R2=distribution([r['heldout_fidelity']['weighted_r2'][cause] for r in rows if r['heldout_fidelity']['samples']]),
                undefined_heldout_subjects=sum(not r['heldout_fidelity']['samples'] for r in rows)))
    reserve(0,0)
    if (input_fingerprint(work, 'multimodal_values') != expected_input_fingerprint
            or any(model_identity(models[key]) != value for key,value in identities.items())):
        raise ValueError('XAI_STUDY_INPUT_OR_MODEL_CHANGED')
    return dict(status='FIXED_GROUPED_XAI_COMPLETE',subjects=len(work),model_loads=15,
        lime_subset_subjects=len(subset),prior_OOF_verified=True,importance=importance,
        sensitivity=comparisons,lime_fidelity=fits,shapley_reconstruction_max_error=max_error,
        operations=counters,predictive_fits=0,calibration_fits=0,
        participant_outputs_saved=False,individual_causal_effect_identified=False,
        clinical_use=False,independent_validation=False,
        elapsed_seconds=time.perf_counter()-started,peak_memory_bytes=peak_memory_bytes())
