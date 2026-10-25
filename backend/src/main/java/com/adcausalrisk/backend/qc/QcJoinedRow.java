package com.adcausalrisk.backend.qc;

/**
 * Joined row projection for the QC audit list page.
 *
 * <p>Spring Data JPA projects a custom DTO against this interface when the repository's
 * {@code @Query} selects columns from multiple tables ({@code qc_audit_record},
 * {@code subject}, {@code visit}, {@code sys_user}). The interface is package-private
 * because it is only returned by {@link QcAuditRepository#findJoined} — external callers
 * consume {@link com.adcausalrisk.backend.qc.dto.QcListView} instead, which the service
 * builds from these rows.
 */
interface QcJoinedRow {

    Long getId();

    Long getSubjectId();

    Long getVisitId();

    String getSubjectCode();

    String getSubjectAlias();

    String getVisitCode();

    String getTargetType();

    String getSourceType();

    String getStatus();

    String getAbnormalItems();

    String getAuditComment();

    String getAuditorName();

    String getAuditorUsername();

    java.time.Instant getAuditedAt();

    java.time.Instant getCreatedAt();

    java.time.Instant getUpdatedAt();
}