package com.adcausalrisk.backend.subject.dto;

import java.time.LocalDate;

/**
 * Response item shape for {@code VisitResult}. The frozen contract requires this
 * type as the element of {@code SubjectDetail.visits}, which must always be an
 * array (empty or populated).
 *
 * <p>All seven fields match the contract:
 * <pre>id, subjectId, visitCode, visitDate (date), mmse (number|null),
 * moca (number|null), cdrSb (number|null)</pre>
 *
 * <p>Population is owned by a later PR that implements {@code POST
 * /api/subjects/{subjectId}/visits}; this PR returns empty lists only.
 */
public record VisitResultView(
        Long id,
        Long subjectId,
        String visitCode,
        LocalDate visitDate,
        Double mmse,
        Double moca,
        Double cdrSb
) {
}