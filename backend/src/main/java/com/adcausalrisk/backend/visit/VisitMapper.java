package com.adcausalrisk.backend.visit;

import java.math.BigDecimal;

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
     * <p>Scores are passed through <b>unchanged</b>. The entity derives both stored forms from
     * them - the raw text and the rounded {@code DECIMAL(5,2)} display column - so this mapper
     * must not pre-round or normalise anything.
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
     * <p>Scores come from the {@code raw_*} text columns, which hold the value exactly as it was
     * submitted, so a client that sent 27.555 reads back 27.555 - not the 27.56 kept in the
     * derived DECIMAL column. Rows written before migration {@code V4} have no raw value and fall
     * back to that derived column rather than reporting {@code null}. A {@code NULL} score stays
     * JSON null; it is never reported as 0.
     */
    public static VisitResultView toResultView(Visit visit) {
        return new VisitResultView(
                visit.getId(),
                visit.getSubjectId(),
                visit.getVisitCode(),
                visit.getVisitDate(),
                exactScore(visit.getRawMmse(), visit.getMmse()),
                exactScore(visit.getRawMoca(), visit.getMoca()),
                exactScore(visit.getRawCdrSb(), visit.getCdrSb()));
    }

    /** Raw text first (authoritative), then the derived DECIMAL column, then {@code null}. */
    private static BigDecimal exactScore(String raw, BigDecimal derived) {
        return raw != null ? new BigDecimal(raw) : derived;
    }
}
