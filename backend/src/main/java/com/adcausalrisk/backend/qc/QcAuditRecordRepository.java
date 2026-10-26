package com.adcausalrisk.backend.qc;

import java.util.Optional;
import java.util.Set;

import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import com.adcausalrisk.backend.qc.entity.QcAuditRecord;

/**
 * Data access for the {@code qc_audit_record} table.
 *
 * <p>Provides two broad categories of query:
 * <ul>
 *   <li><b>Entity reads</b> ({@link #findFiltered}, duplicate checks) — used by the service
 *       when it needs a full {@link QcAuditRecord} entity to mutate or examine.</li>
 *   <li><b>Presentation reads</b> ({@link #findJoined}) — a single JPQL SELECT that
 *       joins in subject.alias, visit.visit_code and the auditor's username so the
 *       list page does not need N extra queries per row.</li>
 * </ul>
 * The Entity itself deliberately has no {@code @ManyToOne} navigations — every foreign
 * key is stored as a bare {@code Long}, and the DDL enforces referential integrity.
 */
@Repository
public interface QcAuditRecordRepository extends JpaRepository<QcAuditRecord, Long> {

    // ===================================================================
    //  Entity-level reads  (return QcAuditRecord)
    // ===================================================================

    /**
     * Has a visit-level audit already been created? Serves as a duplicate guard for the
     * import-quality and automatic-QC trigger paths — they call this before deciding
     * whether to insert a new PENDING row. SUBJECT-granularity audits (where
     * {@code visit_id IS NULL}) do not count: this check is purely visit-scoped.
     */
    boolean existsByVisitIdAndVisitIdIsNotNull(Long visitId);

    /** The most recent audit for a specific visit, regardless of status. */
    Optional<QcAuditRecord> findTopByVisitIdOrderByCreatedAtDesc(Long visitId);

    /**
     * Paged entity rows filtered by three optional predicates. Returns raw entities;
     * the list page uses {@link #findJoined} instead to avoid follow-up joins.
     */
    Page<QcAuditRecord> findByStatusOrderByCreatedAtDesc(QcAuditRecord.Status status, Pageable pageable);

    // ===================================================================
    //  Joined presentation rows  (return QcJoinedRow projection)
    // ===================================================================

    /**
     * Single page of QC audit rows with subject alias, visit code and auditor username
     * joined in. Filters are optional — a {@code null} or blank parameter skips the
     * corresponding WHERE clause, so the frontend can send any combination it needs.
     *
     * <p>Note the JPQL references the Entity class names ({@code Subject}, {@code Visit},
     * {@code SysUser}), not the SQL table names — Spring Data JPA resolves them at
     * runtime via its entity mappings.
     */
    @Query(value = """
            SELECT q.id            AS id,
                   q.subjectId      AS subjectId,
                   q.visitId        AS visitId,
                   s.subjectCode    AS subjectCode,
                   s.alias          AS subjectAlias,
                   v.visitCode      AS visitCode,
                   q.targetType     AS targetType,
                   q.sourceType     AS sourceType,
                   q.status         AS status,
                   q.abnormalItems  AS abnormalItems,
                   q.auditComment   AS auditComment,
                   u.username       AS auditorName,
                   q.auditedAt      AS auditedAt,
                   q.createdAt      AS createdAt,
                   q.updatedAt      AS updatedAt
              FROM QcAuditRecord q
              JOIN Subject  s ON s.id = q.subjectId
              LEFT JOIN Visit v ON v.id = q.visitId
              JOIN SysUser  u ON u.id = q.auditorId
             WHERE (:#{#subjectCode} IS NULL OR :#{#subjectCode} = ''
                    OR s.subjectCode LIKE CONCAT('%', :#{#subjectCode}, '%'))
               AND (:#{#subjectAlias} IS NULL OR :#{#subjectAlias} = ''
                    OR s.alias LIKE CONCAT('%', :#{#subjectAlias}, '%'))
               AND (:#{#status} IS NULL OR q.status = :#{#status})
             ORDER BY q.createdAt DESC
            """,
            countQuery = """
            SELECT COUNT(q) FROM QcAuditRecord q
            JOIN Subject s ON s.id = q.subjectId
            WHERE (:#{#subjectCode} IS NULL OR :#{#subjectCode} = ''
                   OR s.subjectCode LIKE CONCAT('%', :#{#subjectCode}, '%'))
              AND (:#{#subjectAlias} IS NULL OR :#{#subjectAlias} = ''
                   OR s.alias LIKE CONCAT('%', :#{#subjectAlias}, '%'))
              AND (:#{#status} IS NULL OR q.status = :#{#status})
            """)
    Page<QcJoinedRow> findJoined(@Param("subjectCode") String subjectCode,
                                @Param("subjectAlias") String subjectAlias,
                                @Param("status") QcAuditRecord.Status status,
                                Pageable pageable);

    /**
     * Row-level-visibility variant of {@link #findJoined} — restricts the result set
     * to QC rows whose {@code subjectId} is in the caller's granted set. Used for
     * DOCTOR / PATIENT accounts where {@link SubjectAccessPolicy} returned
     * {@code hasFullVisibility = false}.
     *
     * <p>Callers <b>must</b> guarantee {@code subjectIds} is non-empty — an empty
     * set must be short-circuited to {@link Page#empty} in the service layer before
     * this method is invoked, because JPQL does not accept {@code IN ()}.
     */
    @Query(value = """
            SELECT q.id            AS id,
                   q.subjectId      AS subjectId,
                   q.visitId        AS visitId,
                   s.subjectCode    AS subjectCode,
                   s.alias          AS subjectAlias,
                   v.visitCode      AS visitCode,
                   q.targetType     AS targetType,
                   q.sourceType     AS sourceType,
                   q.status         AS status,
                   q.abnormalItems  AS abnormalItems,
                   q.auditComment   AS auditComment,
                   u.username       AS auditorName,
                   q.auditedAt      AS auditedAt,
                   q.createdAt      AS createdAt,
                   q.updatedAt      AS updatedAt
              FROM QcAuditRecord q
              JOIN Subject  s ON s.id = q.subjectId
              LEFT JOIN Visit v ON v.id = q.visitId
              JOIN SysUser  u ON u.id = q.auditorId
             WHERE q.subjectId IN :subjectIds
               AND (:#{#subjectCode} IS NULL OR :#{#subjectCode} = ''
                    OR s.subjectCode LIKE CONCAT('%', :#{#subjectCode}, '%'))
               AND (:#{#subjectAlias} IS NULL OR :#{#subjectAlias} = ''
                    OR s.alias LIKE CONCAT('%', :#{#subjectAlias}, '%'))
               AND (:#{#status} IS NULL OR q.status = :#{#status})
             ORDER BY q.createdAt DESC
            """,
            countQuery = """
            SELECT COUNT(q) FROM QcAuditRecord q
            JOIN Subject s ON s.id = q.subjectId
            WHERE q.subjectId IN :subjectIds
              AND (:#{#subjectCode} IS NULL OR :#{#subjectCode} = ''
                   OR s.subjectCode LIKE CONCAT('%', :#{#subjectCode}, '%'))
              AND (:#{#subjectAlias} IS NULL OR :#{#subjectAlias} = ''
                   OR s.alias LIKE CONCAT('%', :#{#subjectAlias}, '%'))
              AND (:#{#status} IS NULL OR q.status = :#{#status})
            """)
    Page<QcJoinedRow> findJoinedBySubjectIds(@Param("subjectIds") Set<Long> subjectIds,
                                             @Param("subjectCode") String subjectCode,
                                             @Param("subjectAlias") String subjectAlias,
                                             @Param("status") QcAuditRecord.Status status,
                                             Pageable pageable);

    /**
     * One joined row by primary key. Used after {@link com.adcausalrisk.backend.qc.QcAuditService#submitAudit}
     * to hand the caller back the subject/visit/auditor names it cannot get from the entity alone.
     *
     * <p>Row-level visibility is enforced by the caller: {@link QcAuditService#submitAudit}
     * only allows ADMIN / RESEARCHER (the auditor roles) to reach this point, so no
     * subjectId filter is needed here.
     */
    @Query("""
            SELECT q.id            AS id,
                   q.subjectId      AS subjectId,
                   q.visitId        AS visitId,
                   s.subjectCode    AS subjectCode,
                   s.alias          AS subjectAlias,
                   v.visitCode      AS visitCode,
                   q.targetType     AS targetType,
                   q.sourceType     AS sourceType,
                   q.status         AS status,
                   q.abnormalItems  AS abnormalItems,
                   q.auditComment   AS auditComment,
                   u.username       AS auditorName,
                   q.auditedAt      AS auditedAt,
                   q.createdAt      AS createdAt,
                   q.updatedAt      AS updatedAt
              FROM QcAuditRecord q
              JOIN Subject  s ON s.id = q.subjectId
              LEFT JOIN Visit v ON v.id = q.visitId
              JOIN SysUser  u ON u.id = q.auditorId
             WHERE q.id = :#{#id}
            """)
    Optional<QcJoinedRow> findJoinedById(@Param("id") Long id);

    /**
     * Status-grouped counts for the dashboard widget.
     * Returns a single-row projection {@code PendingApprovedRejected}.
     */
    @Query("""
            SELECT q.status    AS status,
                   COUNT(q.id) AS count
              FROM QcAuditRecord q
             GROUP BY q.status
            """)
    java.util.List<Object[]> groupByStatus();

    /**
     * Row-level-visibility variant of {@link #groupByStatus} for DOCTOR / PATIENT.
     * Counts are scoped to QC rows whose subject is in the caller's granted set.
     */
    @Query("""
            SELECT q.status    AS status,
                   COUNT(q.id) AS count
              FROM QcAuditRecord q
             WHERE q.subjectId IN :subjectIds
             GROUP BY q.status
            """)
    java.util.List<Object[]> groupByStatusBySubjectIds(@Param("subjectIds") Set<Long> subjectIds);

    /**
     * Atomic conditional update for the audit decision. The WHERE clause pins the row to
     * {@code status = 'PENDING'}, so the update silently returns 0 rows when a competing
     * auditor has already transitioned it to APPROVED or REJECTED in the meantime.
     *
     * <p>Spring's {@code @Modifying} + {@code clearAutomatically} ensures the first-level
     * cache is flushed and evicted after the update, so a subsequent {@code findById} sees
     * the fresh committed state rather than the stale entity the caller loaded before.
     */
    @Modifying(clearAutomatically = true)
    @Query("UPDATE QcAuditRecord q SET q.status = :status, q.abnormalItems = :abnormalItems, "
            + "q.auditComment = :auditComment, q.auditorId = :auditorId, q.auditedAt = :now, "
            + "q.updatedAt = :now "
            + "WHERE q.id = :id AND q.status = 'PENDING'")
    int updateDecision(@Param("id") Long id,
                       @Param("status") QcAuditRecord.Status status,
                       @Param("abnormalItems") String abnormalItems,
                       @Param("auditComment") String auditComment,
                       @Param("auditorId") Long auditorId,
                       @Param("now") java.time.Instant now);
}