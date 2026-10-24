package com.adcausalrisk.backend.importjob.dto;

/**
 * One rejected row, matching the contract's {@code ImportJob.errors} item exactly.
 *
 * <p>{@code field} is the CSV column name, or {@code ""} for a problem that belongs to the whole
 * record (a wrong column count, for example).
 */
public record ImportJobErrorView(int rowNumber, String field, String message) {
}
