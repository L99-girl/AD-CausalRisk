"""Serialization compatibility for the existing research models.

Only the original hazard wrapper is retained here. This module deliberately has
no data reader, experiment runner, or application-service imports.
"""
import warnings
import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin, clone
from sklearn.exceptions import ConvergenceWarning
from sklearn.utils.validation import check_is_fitted

class NotEstimable(ValueError):
    """The fixed experiment cannot be estimated without changing its protocol."""

class StrictHazards(ClassifierMixin, BaseEstimator):
    """Reject missing causes and malformed probabilities without filling them."""
    def __init__(self, estimator):
        self.estimator = estimator

    def fit(self, x, y):
        # A failed refit must never expose a previous fitted estimator as success.
        for name in ('classes_', 'estimator_'):
            if hasattr(self, name):
                delattr(self, name)
        if not np.array_equal(np.unique(y), [0, 1, 2]):
            raise NotEstimable('Training person-months must contain all three original causes')
        fitted = clone(self.estimator)
        with warnings.catch_warnings():
            warnings.simplefilter('error', ConvergenceWarning)
            fitted.fit(x, y)
        classes = np.asarray(fitted.classes_)
        if not np.array_equal(np.sort(classes), [0, 1, 2]):
            raise NotEstimable('Fitted estimator changed the original cause set')
        self.estimator_, self.classes_ = fitted, classes
        return self

    def predict_proba(self, x):
        check_is_fitted(self, 'classes_')
        p = np.asarray(self.estimator_.predict_proba(x))
        if (p.shape != (x.shape[0], 3) or not np.isfinite(p).all()
                or (p < 0).any() or (p > 1).any()
                or not np.allclose(p.sum(axis=1), 1, rtol=0, atol=1e-6)):
            raise ValueError('Invalid three-cause conditional monthly probabilities')
        return p

    def predict(self, x):
        return self.classes_[np.argmax(self.predict_proba(x), axis=1)]
