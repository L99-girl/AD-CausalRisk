package com.adcausalrisk.backend.qc.dto;

import java.time.Instant;

/**
 * List item for the QC audit page. Built from the
 * {@link com.adcausalrisk.backend.qc.QcJoinedRow} projection by the service layer.
 *
 * <p>Every string field ({@code targetType}, {@code sourceType}, {@code status})
 * uses the wire value the entity enums produce via {@code EnumType.STRING}
 * (e.g. {@code "PENDING"}, {@code "SUBJECT"}). The DDL CHECK constraint keeps the
 * set bounded, so the frontend can switch on these strings directly.
 */
public record QcListView(
        Long id,
        Long subjectId,
        Long visitId,
        String subjectCode,
        String subjectAlias,
        String visitCode,
        String targetType,
        String sourceType,
        String status,
        String abnormalItems,
        String auditComment,
        String auditorName,
        Instant auditedAt,
        Instant createdAt
) {
}