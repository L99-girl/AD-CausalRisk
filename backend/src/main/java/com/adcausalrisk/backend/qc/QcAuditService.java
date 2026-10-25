package com.adcausalrisk.backend.qc;

import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.adcausalrisk.backend.common.BusinessException;
import com.adcausalrisk.backend.common.ErrorCode;
import com.adcausalrisk.backend.common.PageResult;
import com.adcausalrisk.backend.qc.dto.QcListQueryRequest;
import com.adcausalrisk.backend.qc.dto.QcListView;
import com.adcausalrisk.backend.qc.dto.QcStatsView;
import com.adcausalrisk.backend.qc.dto.QcSubmitRequest;
import com.adcausalrisk.backend.qc.entity.QcAuditRecord;
import com.adcausalrisk.backend.qc.entity.QcAuditRecord.SourceType;
import com.adcausalrisk.backend.qc.entity.QcAuditRecord.Status;
import com.adcausalrisk.backend.qc.entity.QcAuditRecord.TargetType;
import com.adcausalrisk.backend.security.AppUserPrincipal;
import com.adcausalrisk.backend.subject.SubjectRepository;
import com.adcausalrisk.backend.visit.VisitRepository;
import com.adcausalrisk.backend.visit.entity.Visit;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Business-logic service for the QC audit module.
 *
 * <p>Four entry points map to the four UI actions the frozen contract exposes:
 * <ol>
 *   <li>{@link #generateQcRecord} — called automatically after a visit or subject is saved;
 *       creates a PENDING row when simple validation rules fire.</li>
 *   <li>{@link #getQcList} — paged list with optional subject/aliases/status filters.</li>
 *   <li>{@link #submitAudit} — the auditor's APPROVED / REJECTED decision.</li>
 *   <li>{@link #getQcStats} — dashboard counts per status bucket.</li>
 * </ol>
 *
 * <p><b>Deliberate design choices</b> worth flagging up front:
 * <ul>
 *   <li>No {@code @ManyToOne} navigations — {@link QcAuditRecord} only holds bare foreign-key
 *       {@code Long}s. The list joins names via {@link QcAuditRecordRepository#findJoined}.</li>
 *   <li>No setter methods on the Entity — mutation goes through {@link QcAuditRecord#submitDecision}
 *       and {@link QcAuditRecord#updateComment}, which are atomically-tested business transitions.</li>
 *   <li>REJECTED does not flip a flag on the Visit/Subject row — neither table has a QC status
 *       column today. Instead, a REJECTED audit row <em>is</em> the flag: the application's write
 *       paths (visit create, import commit, assessment submit) are expected to check
 *       {@code findTopByVisitIdOrderByCreatedAtDesc} and refuse to mutate until the REJECTED
 *       row is resolved. This avoids a schema migration just to store a flag we already store.</li>
 * </ul>
 */
@Service
public class QcAuditService {

    private static final Logger log = LoggerFactory.getLogger(QcAuditService.class);

    /** MMSE valid range per clinical convention. */
    private static final double MMSE_MAX = 30.0;

    /** MoCA valid range. */
    private static final double MOCA_MAX = 30.0;

    /** CDR-SB valid range. */
    private static final double CDR_SB_MAX = 18.0;

    /** Pages beyond 100 rows are capped at 100 by {@link SubjectService} too. */
    private static final int MAX_PAGE_SIZE = 100;

    /** Roles allowed to submit audit decisions (APPROVED / REJECTED). */
    private static final Set<String> AUDITOR_ROLES = Set.of("ADMIN", "RESEARCHER");

    private final QcAuditRecordRepository qcAuditRecordRepository;
    private final VisitRepository visitRepository;
    private final SubjectRepository subjectRepository;
    private final ObjectMapper objectMapper;

    public QcAuditService(QcAuditRecordRepository qcAuditRecordRepository,
                          VisitRepository visitRepository,
                          SubjectRepository subjectRepository,
                          ObjectMapper objectMapper) {
        this.qcAuditRecordRepository = qcAuditRecordRepository;
        this.visitRepository = visitRepository;
        this.subjectRepository = subjectRepository;
        this.objectMapper = objectMapper;
    }

    // ===================================================================
    //  1. Generate QC records  (called from VisitService / import pipeline)
    // ===================================================================

    /**
     * Runs the simple built-in QC rules against a freshly-saved visit, and inserts a
     * PENDING row when any of them fire. Called by {@link VisitService} after a successful
     * visit insert, and by the import pipeline after committing a batch of visits.
     *
     * <p>The rules are intentionally simple — this is not the Python rule engine. It catches
     * obvious data-entry mistakes before a human ever opens the review queue. The {@code auditorId}
     * passed in is the person whose action triggered the check (e.g. the import operator),
     * not the person who will eventually review it.
     *
     * <p>Rules that currently fire:
     * <ul>
     *   <li>{@code mmse} is present but exceeds 30 (or negative)</li>
     *   <li>{@code moca} is present but exceeds 30 (or negative)</li>
     *   <li>{@code cdr_sb} is present but exceeds 18 (or negative)</li>
     *   <li>{@code mmse} <b>and</b> {@code moca} are both null — every AD visit should record
     *       at least one cognitive score</li>
     *   <li>{@code visitDate} is after today — future dates are suspicious</li>
     * </ul>
     *
     * <p>Idempotent: if a PENDING row already exists for this visit, we skip insertion.
     * The caller does not care whether a row was created.
     */
    @Transactional
    public void generateQcRecord(Visit visit, Long operatorId, Long qualityCheckId) {
        log.info("QC check triggered for visit id={} visitCode={} subjectId={} mmse={} moca={} cdrSb={} visitDate={}",
                visit.getId(), visit.getVisitCode(), visit.getSubjectId(),
                visit.getMmse(), visit.getMoca(), visit.getCdrSb(), visit.getVisitDate());

        List<String> anomalies = new ArrayList<>();

        if (visit.getMmse() != null && (visit.getMmse().doubleValue() < 0 || visit.getMmse().doubleValue() > MMSE_MAX)) {
            anomalies.add("MMSE 得分 " + visit.getMmse() + " 超出有效范围 0-" + MMSE_MAX);
        }
        if (visit.getMoca() != null && (visit.getMoca().doubleValue() < 0 || visit.getMoca().doubleValue() > MOCA_MAX)) {
            anomalies.add("MoCA 得分 " + visit.getMoca() + " 超出有效范围 0-" + MOCA_MAX);
        }
        if (visit.getCdrSb() != null && (visit.getCdrSb().doubleValue() < 0 || visit.getCdrSb().doubleValue() > CDR_SB_MAX)) {
            anomalies.add("CDR-SB 得分 " + visit.getCdrSb() + " 超出有效范围 0-" + CDR_SB_MAX);
        }
        if (visit.getMmse() == null && visit.getMoca() == null) {
            anomalies.add("MMSE 和 MoCA 得分均缺失，至少应记录一项认知评估");
        }
        if (visit.getVisitDate() != null && visit.getVisitDate().isAfter(LocalDate.now())) {
            anomalies.add("访视日期 " + visit.getVisitDate() + " 晚于今日，请核对录入是否正确");
        }

        if (anomalies.isEmpty()) {
            log.info("QC passed clean for visit id={} — no rules fired", visit.getId());
            return;
        }

        log.info("QC flagged {} anomaly(ies) for visit id={}: {}",
                anomalies.size(), visit.getId(), anomalies);

        // Idempotency guard — a PENDING row for this visit already covers it.
        if (qcAuditRecordRepository.existsByVisitIdAndVisitIdIsNotNull(visit.getId())) {
            log.debug("QC rule fired for visit {} but a PENDING row already exists, skipping", visit.getId());
            return;
        }

        Instant now = Instant.now();
        QcAuditRecord record = new QcAuditRecord(
                visit.getSubjectId(),
                visit.getId(),
                TargetType.VISIT,
                qualityCheckId != null ? SourceType.AUTO_QC_TRIGGER : SourceType.MANUAL_REVIEW,
                operatorId,
                qualityCheckId,
                toJson(anomalies),
                now);

        qcAuditRecordRepository.save(record);
        log.info("Created QC audit record id={} for visit id={}, {} anomaly(ies)",
                record.getId(), visit.getId(), anomalies.size());
    }

    // ===================================================================
    //  2. Paged list  (used by the QC dashboard / queue)
    // ===================================================================

    /**
     * One page of joined QC audit rows. Filters from {@link QcListQueryRequest} are optional;
     * {@code page} and {@code pageSize} are passed as raw ints from the controller because
     * the service owns the clamp-to-[1,100] business rule.
     *
     * <p>All authenticated users may view the QC queue. Fine-grained row-level visibility
     * (e.g. DOCTOR only sees rows for their own subjects) can be added later by joining
     * {@code subject_permission} — that policy belongs here, not in the repository.
     */
    @Transactional(readOnly = true)
    public PageResult<QcListView> getQcList(QcListQueryRequest request,
                                            int page,
                                            int pageSize,
                                            AppUserPrincipal principal) {
        int safePage = Math.max(1, page);
        int safePageSize = Math.max(1, Math.min(MAX_PAGE_SIZE, pageSize));

        Pageable pageable = PageRequest.of(safePage - 1, safePageSize);
        Status statusFilter = null;
        if (request.status() != null && !request.status().isBlank()) {
            try {
                statusFilter = Status.valueOf(request.status());
            } catch (IllegalArgumentException ignored) {
                statusFilter = null;
            }
        }
        Page<QcJoinedRow> paged = qcAuditRecordRepository.findJoined(
                request.subjectCode(), request.subjectAlias(), statusFilter, pageable);

        List<QcListView> items = paged.getContent().stream().map(this::toView).toList();
        return new PageResult<>(items, safePage, safePageSize, paged.getTotalElements());
    }

    // ===================================================================
    //  3. Submit audit decision  (APPROVED / REJECTED)
    // ===================================================================

    /**
     * The auditor submits a decision on a PENDING row.
     *
     * <p>Flow:
     * <ol>
     *   <li>Role check — only {@code ADMIN} and {@code RESEARCHER} may submit audit decisions.
     *       {@code DOCTOR} / {@code PATIENT} receive ACCESS_DENIED (403).</li>
     *   <li>Load the row — 400 if missing (business resource, not 404).</li>
     *   <li>Status must be PENDING; APPROVED/REJECTED rows cannot be re-decided.</li>
     *   <li>Call {@link QcAuditRecord#submitDecision} which atomically sets the five
     *       mutating fields and throws if the preconditions are somehow violated again.</li>
     *   <li>Persist and return the joined view.</li>
     * </ol>
     *
     * <p><b>REJECTED & the "needs re-entry" flag</b> — as noted in the class javadoc, neither
     * {@code Visit} nor {@code Subject} carries a QC status column today. The REJECTED row itself
     * <em>is</em> the flag: callers that write clinical data (visit create, import commit,
     * assessment submit) must consult {@link VisitRepository} + this repository to refuse
     * mutations when the target visit has an unresolved REJECTED audit. Adding a dedicated
     * {@code needs_reentry} flag to {@code visit} is a separate schema migration — the flag
     * would duplicate what we already store.
     */
    @Transactional
    public QcListView submitAudit(Long id, QcSubmitRequest request, AppUserPrincipal principal) {
        if (principal.roleCodes().stream().noneMatch(AUDITOR_ROLES::contains)) {
            throw new BusinessException(ErrorCode.ACCESS_DENIED,
                    "无质控审核权限，仅 ADMIN / RESEARCHER 可以提交审核结果");
        }

        QcAuditRecord record = qcAuditRecordRepository.findById(id).orElseThrow(() ->
                new BusinessException(ErrorCode.VALIDATION_ERROR, "质控记录不存在: " + id));

        if (record.getStatus() != Status.PENDING) {
            throw new BusinessException(ErrorCode.VALIDATION_ERROR,
                    "质控记录 " + id + " 已完成审核（" + record.getStatus() + "），不可重复提交");
        }

        Instant now = Instant.now();

        record.submitDecision(
                Status.valueOf(request.status()),
                request.abnormalItems(),
                request.auditComment(),
                now);

        qcAuditRecordRepository.save(record);
        log.info("QC audit id={} submitted as {} by userId={} role={}",
                id, request.status(), principal.userId(), principal.roleCodes());

        return qcAuditRecordRepository.findJoinedById(id)
                .map(this::toView)
                .orElseThrow(() -> new IllegalStateException(
                        "Joined row disappeared after save for id=" + id));
    }

    // ===================================================================
    //  4. Dashboard stats
    // ===================================================================

    /**
     * Aggregates row counts per status bucket. Always returns all three buckets —
     * buckets with zero rows default to 0 instead of being omitted, so the frontend
     * never sees a missing key.
     *
     * <p>All authenticated users may view the dashboard — this is a high-level summary
     * and does not leak per-subject data.
     */
    @Transactional(readOnly = true)
    public QcStatsView getQcStats(AppUserPrincipal principal) {
        List<Object[]> rows = qcAuditRecordRepository.groupByStatus();
        Map<String, Long> counts = rows.stream()
                .collect(Collectors.toMap(
                        arr -> ((Status) arr[0]).name(),
                        arr -> (Long) arr[1],
                        (a, b) -> a));

        return new QcStatsView(
                counts.getOrDefault(Status.PENDING.name(), 0L),
                counts.getOrDefault(Status.APPROVED.name(), 0L),
                counts.getOrDefault(Status.REJECTED.name(), 0L));
    }

    // ===================================================================
    //  Internal helpers
    // ===================================================================

    private QcListView toView(QcJoinedRow row) {
        return new QcListView(
                row.getId(),
                row.getSubjectId(),
                row.getVisitId(),
                row.getSubjectCode(),
                row.getSubjectAlias(),
                row.getVisitCode(),
                row.getTargetType(),
                row.getSourceType(),
                row.getStatus(),
                row.getAbnormalItems(),
                row.getAuditComment(),
                row.getAuditorName(),
                row.getAuditedAt(),
                row.getCreatedAt());
    }

    /**
     * Converts a list of anomaly strings to a JSON array for the TEXT column.
     * Returns {@code null} (not "[]") when the list is empty, so downstream code
     * can distinguish "no anomalies" from "has anomalies".
     */
    private String toJson(List<String> anomalies) {
        if (anomalies == null || anomalies.isEmpty()) {
            return null;
        }
        try {
            return objectMapper.writeValueAsString(anomalies);
        } catch (JsonProcessingException e) {
            // Should never happen with simple strings; log and fall back to comma-joined text
            // so at least the anomaly survives.
            log.warn("Failed to serialize anomalies to JSON, falling back to comma-joined text", e);
            return String.join(", ", anomalies);
        }
    }
}