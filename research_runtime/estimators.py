"""The fixed seven/ten-variable estimator specifications, without data readers."""
from importlib.metadata import version

from sklearn.ensemble import RandomForestClassifier
from adni_algorithm_candidates import StrictHazards
from .discrete import make_estimator

SEED = 20260926
FAMILIES = ('logistic', 'random_forest', 'xgboost')
BASE = ('age_years', 'education_years', 'mmse', 'cdr_sb', 'cdr_global',
        'adas__total13', 'faq__faqtotal')
ADDED = ('apoe4_count', 'mri_left_hippocampus_volume', 'mri_right_hippocampus_volume')
SPECS = {'seven': BASE, 'modality_availability': BASE + ADDED, 'multimodal_values': BASE + ADDED}


def make_candidate(family, specification, seed=SEED):
    """Construct an unfitted pipeline. No implicit fit or model selection."""
    if family not in FAMILIES or specification not in SPECS:
        raise ValueError('UNKNOWN_MODEL_SPECIFICATION')
    model = make_estimator(list(SPECS[specification]), seed)
    estimator = model.named_steps['hazards']
    if family == 'random_forest':
        estimator = RandomForestClassifier(
            n_estimators=200, max_depth=6, min_samples_leaf=5, n_jobs=1,
            random_state=seed, criterion='gini', max_features='sqrt',
            bootstrap=True, class_weight=None)
    elif family == 'xgboost':
        if version('xgboost') != '3.2.0':
            raise ValueError('XGBOOST_VERSION_MISMATCH')
        from xgboost import XGBClassifier
        estimator = XGBClassifier(
            n_estimators=200, max_depth=3, learning_rate=0.05,
            reg_lambda=1, reg_alpha=0, min_child_weight=1, gamma=0,
            subsample=1, colsample_bytree=1, n_jobs=1, random_state=seed,
            objective='multi:softprob', num_class=3, eval_metric='mlogloss',
            tree_method='hist', device='cpu', max_bin=256,
            base_score=0.5, booster='gbtree', verbosity=0)
    return model.set_params(hazards=StrictHazards(estimator))


def information_arm(frame, specification):
    if specification not in SPECS:
        raise ValueError('UNKNOWN_MODEL_SPECIFICATION')
    result = frame.copy(deep=True)
    if specification == 'modality_availability':
        for feature in ADDED:
            result.loc[result[feature].notna(), feature] = 0.
    return result
