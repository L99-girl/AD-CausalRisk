package com.adcausalrisk.backend.subject.dto;

import java.util.List;

/**
 * Response shape for {@code GET /api/subjects/{subjectId}} - the frozen contract
 * schema {@code SubjectDetail}.
 *
 * <p>{@code visits} and {@code features} are required by the contract and must be
 * present in every response as empty arrays in this PR, because the visit/feature
 * write endpoints are implemented later.
 */
public record SubjectDetailView(
        SubjectView subject,
        List<VisitResultView> visits,
        List<FeatureResultView> features
) {
}