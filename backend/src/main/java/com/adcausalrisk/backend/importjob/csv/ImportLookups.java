package com.adcausalrisk.backend.importjob.csv;

/**
 * The database questions a CSV row needs answered.
 *
 * <p>Kept as a narrow interface so the parser stays a pure function: production supplies a
 * repository-backed implementation, and the unit tests supply a map. That keeps the parser's
 * validation rules testable without a Spring context or a database.
 */
public interface ImportLookups {

    /** The id of an existing subject, or {@code null} when the code is unknown. */
    Long subjectIdOf(String subjectCode);

    /** Whether the subject already has a visit with this code (the DDL is unique per subject). */
    boolean visitExists(Long subjectId, String visitCode);
}
