package com.adcausalrisk.backend.visit.entity;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * A single visit from the {@code visit} table.
 *
 * <p><b>Each score is stored twice, with different authority.</b> {@code raw_*} (VARCHAR, added
 * by migration {@code V4}) holds the value exactly as submitted and is the source of truth: the
 * API returns it and the scoring workflow must read it. {@code mmse}/{@code moca}/{@code cdr_sb}
 * are <i>derived</i> columns holding {@code round(raw, 2)}, kept for charts, list views and SQL
 * that needs a real number. They are never authoritative: {@code DECIMAL(5,2)} cannot represent
 * 27.555.
 *
 * <p>Both forms are derived together in the constructor from the submitted {@link BigDecimal},
 * so a row can never be written with only one of them. The {@link BigDecimal} fields keep their
 * {@code precision}/{@code scale} in step with the DDL, otherwise {@code ddl-auto: validate}
 * aborts startup.
 *
 * <p>There is no {@code @ManyToOne} to {@code Subject}. A visit row never needs to navigate
 * to the subject, and the subject module models its own foreign keys the same way
 * ({@code SubjectPermission} holds a bare {@code Long subjectId}). The database still
 * enforces {@code fk_visit_subject}, and the service checks the subject exists before
 * inserting.
 *
 * <p>A score that was not recorded stays {@code null} in both forms: missing values are
 * preserved, never replaced by 0 (the DDL CHECKs are written as {@code mmse IS NULL OR (...)}
 * for this reason).
 */
@Entity
@Table(name = "visit")
public class Visit {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id", nullable = false)
    private Long id;

    @Column(name = "subject_id", nullable = false)
    private Long subjectId;

    @Column(name = "visit_code", nullable = false, length = 50)
    private String visitCode;

    @Column(name = "visit_date", nullable = false)
    private LocalDate visitDate;

    /**
     * {@code precision}/{@code scale} mirror the DDL so this entity documents the schema.
     * {@code DECIMAL(5,2)} comes from migration {@code V3}; V1 declared {@code (4,1)}, which
     * rounded away the second decimal.
     */
    @Column(name = "mmse", precision = 5, scale = 2)
    private BigDecimal mmse;

    @Column(name = "moca", precision = 5, scale = 2)
    private BigDecimal moca;

    @Column(name = "cdr_sb", precision = 5, scale = 2)
    private BigDecimal cdrSb;

    /**
     * The submitted score as {@link BigDecimal#toString()} renders it - the authoritative form.
     *
     * <p>This preserves the <i>numeric value</i> exactly (that is why V4 exists), but it is the
     * canonical text, not the literal cell the client typed: {@code 07.50} becomes {@code 7.50},
     * {@code 1e1} becomes {@code 1E+1}, {@code +1} becomes {@code 1} and {@code -0.0} becomes
     * {@code 0.0}. {@code null} for rows written before V4 that could not be backfilled; readers
     * then fall back to the derived column.
     */
    @Column(name = "raw_mmse", length = 64)
    private String rawMmse;

    @Column(name = "raw_moca", length = 64)
    private String rawMoca;

    @Column(name = "raw_cdr_sb", length = 64)
    private String rawCdrSb;

    protected Visit() {
        // for JPA
    }

    public Visit(Long subjectId, String visitCode, LocalDate visitDate,
                 BigDecimal mmse, BigDecimal moca, BigDecimal cdrSb) {
        this.subjectId = subjectId;
        this.visitCode = visitCode;
        this.visitDate = visitDate;
        // Derived together on purpose: the raw text and the rounded DECIMAL column can never
        // drift apart, because no caller can set one without the other.
        this.rawMmse = rawOf(mmse);
        this.rawMoca = rawOf(moca);
        this.rawCdrSb = rawOf(cdrSb);
        this.mmse = storageScale(mmse);
        this.moca = storageScale(moca);
        this.cdrSb = storageScale(cdrSb);
    }

    /** The exact submitted value as text; {@code null} stays {@code null}. */
    private static String rawOf(BigDecimal value) {
        return value == null ? null : value.toString();
    }

    /** The derived/display form: rounded to the two decimals {@code DECIMAL(5,2)} can hold. */
    private static BigDecimal storageScale(BigDecimal value) {
        return value == null ? null : value.setScale(2, RoundingMode.HALF_UP);
    }

    public Long getId() {
        return id;
    }

    public Long getSubjectId() {
        return subjectId;
    }

    public String getVisitCode() {
        return visitCode;
    }

    public LocalDate getVisitDate() {
        return visitDate;
    }

    public BigDecimal getMmse() {
        return mmse;
    }

    public BigDecimal getMoca() {
        return moca;
    }

    public BigDecimal getCdrSb() {
        return cdrSb;
    }

    public String getRawMmse() {
        return rawMmse;
    }

    public String getRawMoca() {
        return rawMoca;
    }

    public String getRawCdrSb() {
        return rawCdrSb;
    }
}
