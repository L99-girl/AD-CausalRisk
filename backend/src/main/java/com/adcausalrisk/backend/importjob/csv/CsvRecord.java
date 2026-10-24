package com.adcausalrisk.backend.importjob.csv;

import java.util.List;

/**
 * One CSV record, with the <b>physical line</b> it starts on.
 *
 * <p>That is the line numbering the Python preflight reports: a record whose quoted field spans
 * three lines is still identified by the line where it began, not by its index among the parsed
 * objects.
 */
public record CsvRecord(int lineNumber, List<String> fields) {

    public String field(int index) {
        return index < fields.size() ? fields.get(index) : "";
    }
}
