package com.adcausalrisk.backend.importjob.dto;

import java.util.List;

/**
 * Response shape for the three import endpoints, matching the contract's {@code ImportJob}
 * schema field for field.
 *
 * <p>{@code status} is the wire string of the entity's enum ({@code PREVIEW_READY} /
 * {@code BLOCKED} / {@code COMMITTED} / {@code FAILED}), because the contract models it as an
 * enum of strings rather than an object.
 *
 * <p>{@code totalRows == validRows + invalidRows}; every data row is either insertable or
 * rejected. {@code errors} may be shorter than {@code invalidRows} - the array is capped, while
 * the counts stay exact.
 */
public record ImportJobView(
        Long jobId,
        String status,
        String dataVersion,
        int totalRows,
        int validRows,
        int invalidRows,
        List<ImportJobErrorView> errors) {
}
