package com.adcausalrisk.backend.visit;

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
     * <p>Scores are passed through <b>unchanged</b>. They are deliberately not rounded or
     * truncated here: the original observation must survive, because later scoring, reads and
     * the value handed to the scoring workflow all depend on recovering exactly what was
     * submitted. The column type ({@code DECIMAL(5,2)}, widened by migration {@code V3}) is what
     * keeps the value, and Bean Validation has already rejected anything outside the permitted
     * range.
     */
    public static Visit toEntity(Long subjectId, VisitCreateRequest request) {
        return new Visit(
                subjectId,
                request.visitCode(),
                request.visitDate(),
                request.mmse(),
                request.moca(),
                request.cdrSb());
    }

    /**
     * Maps a {@link Visit} to the contract's {@code VisitResult} shape, which is also the
     * element type of {@code SubjectDetail.visits}.
     *
     * <p>Scores are passed through as {@link java.math.BigDecimal}, the type the entity stores,
     * so no {@code double} conversion can lose precision on the way out. A {@code NULL} score
     * stays JSON null - it is never reported as 0.
     */
    public static VisitResultView toResultView(Visit visit) {
        return new VisitResultView(
                visit.getId(),
                visit.getSubjectId(),
                visit.getVisitCode(),
                visit.getVisitDate(),
                visit.getMmse(),
                visit.getMoca(),
                visit.getCdrSb());
    }
}
