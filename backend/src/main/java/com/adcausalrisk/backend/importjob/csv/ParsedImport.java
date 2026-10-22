package com.adcausalrisk.backend.importjob.csv;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.List;

/**
 * Result of validating one uploaded CSV.
 *
 * <p>{@code totalRows} counts data records only (the header is not a row), and every data record
 * is either valid or rejected, so {@code totalRows == validRows + invalidRows}.
 *
 * <p>{@code issues} may be longer than the response shows: the contract's {@code errors} array is
 * capped at {@link CsvImportParser#MAX_ISSUES}, while the counts stay exact.
 */
public record ParsedImport(
        ImportTable table,
        int totalRows,
        int validRows,
        int invalidRows,
        List<RowIssue> issues,
        List<ImportRow> rows) {

    /**
     * A fingerprint of the rows that passed validation: sorted, fully rendered, SHA-256, hex.
     *
     * <p>It exists because a count is not an identity. Between preview and commit one valid row
     * can stop being valid while a rejected row starts being valid, leaving {@code validRows}
     * unchanged but the set completely different - and commit would then insert a row the caller
     * never approved. Comparing this digest proves the set, not just its size.
     *
     * <p>Sorting makes the digest independent of row order, so reordering the CSV does not force
     * a re-preview. Values are included, not just keys, so the digest covers what will be written.
     */
    public String digest() {
        try {
            MessageDigest sha256 = MessageDigest.getInstance("SHA-256");
            rows.stream()
                    .map(ParsedImport::identify)
                    .sorted()
                    .forEach(line -> {
                        sha256.update(line.getBytes(StandardCharsets.UTF_8));
                        sha256.update((byte) '\n');
                    });
            return HexFormat.of().formatHex(sha256.digest());
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is required by the JVM", exception);
        }
    }

    private static String identify(ImportRow row) {
        return switch (row) {
            case ImportRow.Subject subject -> String.join("|", "SUBJECT",
                    subject.subjectCode(), subject.alias(), subject.status());
            case ImportRow.Visit visit -> String.join("|", "VISIT",
                    String.valueOf(visit.subjectId()), visit.visitCode(),
                    String.valueOf(visit.visitDate()), String.valueOf(visit.mmse()),
                    String.valueOf(visit.moca()), String.valueOf(visit.cdrSb()));
            case ImportRow.Feature feature -> String.join("|", "FEATURE",
                    String.valueOf(feature.subjectId()), feature.featureName(),
                    String.valueOf(feature.featureValue()), String.valueOf(feature.recordedAt()),
                    feature.unit());
        };
    }
}
