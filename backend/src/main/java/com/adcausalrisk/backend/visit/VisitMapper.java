package com.adcausalrisk.backend.visit;

import java.math.BigDecimal;
import java.math.RoundingMode;

import com.adcausalrisk.backend.subject.dto.VisitResultView;
import com.adcausalrisk.backend.visit.dto.VisitCreateRequest;
import com.adcausalrisk.backend.visit.entity.Visit;

/**
 * Hand-written Entity ↔ DTO converters for the visit module, following the same style as
 * {@link com.adcausalrisk.backend.subject.SubjectMapper}: a plain static utility rather than
 * a Spring bean, and no mapping library anywhere in this project.
 */
public final class VisitMapper {

    private VisitMapper() {
        // utility class - no instances
    }

    /**
     * Builds a fresh entity for one subject. {@code id} is owned by the database, and
     * {@code subjectId} comes from the request path rather than the body.
     *
     * <p>Scores are rounded to the scale the DDL can store ({@code DECIMAL(4,1)}) here, at the
     * single boundary between the API and persistence. The contract accepts any precision, so
     * this is where a submitted value becomes storable; because {@code save} returns this entity
     * and later reads come from the same row, the response always reports exactly what was
     * stored.
     *
     * <p>Range validation runs on the submitted value (Bean Validation, before this method), so
     * a value just below the minimum can never be rounded up into the valid range.
     */
    public static Visit toEntity(Long subjectId, VisitCreateRequest request) {
        return new Visit(
                subjectId,
                request.visitCode(),
                request.visitDate(),
                toStorageScale(request.mmse()),
                toStorageScale(request.moca()),
                toStorageScale(request.cdrSb()));
    }

    /**
     * Rounds a submitted score to one decimal ({@code HALF_UP}), matching {@code DECIMAL(4,1)}.
     * {@code null} stays {@code null}: a score that was not recorded is never turned into 0.
     */
    private static BigDecimal toStorageScale(BigDecimal value) {
        return value == null ? null : value.setScale(1, RoundingMode.HALF_UP);
    }

    /**
     * Maps a {@link Visit} to the contract's {@code VisitResult} shape, which is also the
     * element type of {@code SubjectDetail.visits}.
     *
     * <p>The entity keeps the scores as {@link BigDecimal} (required by
     * {@code ddl-auto: validate} against {@code DECIMAL(4,1)}) while
     * {@link VisitResultView} exposes them as {@code Double}; the conversion happens here.
     * A {@code NULL} score stays JSON null - it is never reported as 0.
     */
    public static VisitResultView toResultView(Visit visit) {
        return new VisitResultView(
                visit.getId(),
                visit.getSubjectId(),
                visit.getVisitCode(),
                visit.getVisitDate(),
                toDouble(visit.getMmse()),
                toDouble(visit.getMoca()),
                toDouble(visit.getCdrSb()));
    }

    private static Double toDouble(BigDecimal value) {
        return value == null ? null : value.doubleValue();
    }
}
