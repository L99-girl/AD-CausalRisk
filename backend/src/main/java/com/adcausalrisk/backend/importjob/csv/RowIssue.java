package com.adcausalrisk.backend.importjob.csv;

/**
 * One rejected row detail, shaped exactly like the contract's {@code ImportJob.errors} item.
 *
 * <p>{@code field} is the CSV column name for a field-level problem, or the empty string for a
 * problem that belongs to the whole record (for example a wrong column count). The contract
 * requires {@code field} to be present but allows it to be empty.
 */
public record RowIssue(int rowNumber, String field, String message) {
}
