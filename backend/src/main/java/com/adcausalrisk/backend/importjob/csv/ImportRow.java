package com.adcausalrisk.backend.importjob.csv;

import java.math.BigDecimal;
import java.time.LocalDate;

/**
 * A row that passed validation, in the shape its table needs for the insert.
 *
 * <p>{@code subjectId} is already resolved against the database: the CSV carries {@code
 * subjectCode}, and the preflight rule is that a row pointing at an unknown subject is invalid
 * rather than something to create on the fly.
 */
public sealed interface ImportRow {

    /** The physical CSV line the row started on, as reported in {@code ImportJob.errors}. */
    int rowNumber();

    record Subject(int rowNumber, String subjectCode, String alias, String status) implements ImportRow {
    }

    record Visit(int rowNumber, Long subjectId, String visitCode, LocalDate visitDate,
                 BigDecimal mmse, BigDecimal moca, BigDecimal cdrSb) implements ImportRow {
    }

    record Feature(int rowNumber, Long subjectId, String featureName, BigDecimal featureValue,
                   LocalDate recordedAt, String unit) implements ImportRow {
    }
}
