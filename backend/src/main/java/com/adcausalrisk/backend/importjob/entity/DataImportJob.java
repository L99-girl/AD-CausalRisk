package com.adcausalrisk.backend.importjob.entity;

import java.time.Instant;

import com.adcausalrisk.backend.importjob.csv.ImportTable;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * A CSV import job: preview first, commit later.
 *
 * <p>The row is also the preview's storage. {@code preview_csv} keeps the uploaded text exactly
 * as received so {@code commit} re-parses the same bytes that were previewed, instead of asking
 * for a second upload and hoping it matches. The text is cleared as soon as the job reaches a
 * terminal state, so raw uploads are not retained.
 *
 * <p>{@code status} is derived from the counts at creation time rather than passed in, which
 * keeps the "nothing to commit means BLOCKED" rule in one place:
 * {@code validRows == 0 -> BLOCKED}, otherwise {@code PREVIEW_READY}.
 */
@Entity
@Table(name = "data_import_job")
public class DataImportJob {

    /** Matches {@code ck_data_import_job_status} and the contract's {@code ImportJob.status}. */
    public enum Status {
        PREVIEW_READY,
        BLOCKED,
        COMMITTED,
        FAILED
    }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id", nullable = false)
    private Long id;

    @Column(name = "created_by", nullable = false)
    private Long createdBy;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 20)
    private Status status;

    @Column(name = "data_version", nullable = false, length = 100)
    private String dataVersion;

    @Column(name = "total_rows", nullable = false)
    private int totalRows;

    @Column(name = "valid_rows", nullable = false)
    private int validRows;

    @Column(name = "invalid_rows", nullable = false)
    private int invalidRows;

    @Column(name = "error_report_json")
    private String errorReportJson;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    /** Which table the upload contained, decided by the exact header row. */
    @Enumerated(EnumType.STRING)
    @Column(name = "import_type", length = 20)
    private ImportTable importType;

    /** The uploaded text, kept until the job reaches a terminal state. */
    @Column(name = "preview_csv")
    private String previewCsv;

    /** SHA-256 of the uploaded bytes, hex; distinguishes "same key, same file" from a new file. */
    @Column(name = "source_digest", length = 64)
    private String sourceDigest;

    /**
     * SHA-256 over the sorted valid rows of the preview, hex. Commit recomputes it to prove it is
     * about to insert exactly the set the caller approved, not merely the same number of rows.
     * {@code null} for jobs created before migration V6, where commit falls back to counting.
     */
    @Column(name = "preview_digest", length = 64)
    private String previewDigest;

    protected DataImportJob() {
        // for JPA
    }

    public DataImportJob(Long createdBy, String dataVersion, Instant createdAt,
                         ImportTable importType, int totalRows, int validRows, int invalidRows,
                         String errorReportJson, String previewCsv, String sourceDigest,
                         String previewDigest) {
        this.createdBy = createdBy;
        this.dataVersion = dataVersion;
        this.createdAt = createdAt;
        this.importType = importType;
        this.totalRows = totalRows;
        this.validRows = validRows;
        this.invalidRows = invalidRows;
        this.errorReportJson = errorReportJson;
        this.sourceDigest = sourceDigest;
        this.previewDigest = previewDigest;
        // A preview with nothing to insert cannot be committed, so it is BLOCKED rather than
        // PREVIEW_READY. Rejected rows alone do not block the job: commit inserts the valid ones.
        this.status = validRows == 0 ? Status.BLOCKED : Status.PREVIEW_READY;
        // A BLOCKED job can never be committed, so retaining its upload would only keep raw
        // clinical text (aliases included) in the database for no purpose.
        this.previewCsv = validRows == 0 ? null : previewCsv;
    }

    /** Terminal state after a successful commit; the retained upload is dropped. */
    public void markCommitted() {
        this.status = Status.COMMITTED;
        this.previewCsv = null;
    }

    public Long getId() {
        return id;
    }

    public Long getCreatedBy() {
        return createdBy;
    }

    public Status getStatus() {
        return status;
    }

    public String getDataVersion() {
        return dataVersion;
    }

    public int getTotalRows() {
        return totalRows;
    }

    public int getValidRows() {
        return validRows;
    }

    public int getInvalidRows() {
        return invalidRows;
    }

    public String getErrorReportJson() {
        return errorReportJson;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public ImportTable getImportType() {
        return importType;
    }

    public String getPreviewCsv() {
        return previewCsv;
    }

    public String getSourceDigest() {
        return sourceDigest;
    }

    public String getPreviewDigest() {
        return previewDigest;
    }
}
