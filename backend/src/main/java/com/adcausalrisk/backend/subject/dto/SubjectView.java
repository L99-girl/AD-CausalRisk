package com.adcausalrisk.backend.subject.dto;

import java.time.Instant;

/**
 * Response item shape for {@code Subject} in the frozen contract.
 *
 * <p>Used both as the {@code data} payload of {@code POST /api/subjects} and as
 * each element of the {@code PageSubject.items} array for {@code GET /api/subjects}.
 */
public record SubjectView(
        Long id,
        String subjectCode,
        String alias,
        String status,
        String dataVersion,
        Instant createdAt
) {
}