package com.adcausalrisk.backend.subject.dto;

import java.time.LocalDate;

/**
 * Response item shape for {@code FeatureResult}. The frozen contract requires
 * this type as the element of {@code SubjectDetail.features}, which must always
 * be an array (empty or populated).
 *
 * <p>All six fields match the contract:
 * <pre>id, subjectId, featureName (enum), featureValue (number|null),
 * recordedAt (date), unit (enum)</pre>
 *
 * <p>Population is owned by a later PR that implements {@code POST
 * /api/subjects/{subjectId}/features}; this PR returns empty lists only.
 */
public record FeatureResultView(
        Long id,
        Long subjectId,
        String featureName,
        Double featureValue,
        LocalDate recordedAt,
        String unit
) {
}