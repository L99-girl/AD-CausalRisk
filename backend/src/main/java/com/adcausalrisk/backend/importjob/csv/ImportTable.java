package com.adcausalrisk.backend.importjob.csv;

import java.util.List;

/**
 * The three tables a CSV upload may contain.
 *
 * <p>The contract's request body is only {@code file} - there is no {@code importType} field - so
 * the table is identified by its <b>exact</b> header row. Those headers are the ones the fixtures
 * use, in their original order: the Python preflight rule is "use the original fixture headers,
 * do not guess column names", and guessing would silently accept a reordered or renamed file.
 *
 * <p>Row limits mirror the Python preflight caps (subjects 200, visits 1000, features 2000).
 */
public enum ImportTable {

    SUBJECT("subjects", List.of("subjectCode", "alias", "status"), 200),

    VISIT("visits", List.of("subjectCode", "visitCode", "visitDate", "mmse", "moca", "cdrSb"), 1000),

    FEATURE("features",
            List.of("subjectCode", "featureName", "featureValue", "recordedAt", "unit"), 2000);

    private final String displayName;

    private final List<String> header;

    private final int maxRows;

    ImportTable(String displayName, List<String> header, int maxRows) {
        this.displayName = displayName;
        this.header = header;
        this.maxRows = maxRows;
    }

    public String displayName() {
        return displayName;
    }

    public List<String> header() {
        return header;
    }

    public int maxRows() {
        return maxRows;
    }

    /** The header, joined for error messages. */
    public String headerLine() {
        return String.join(",", header);
    }
}
