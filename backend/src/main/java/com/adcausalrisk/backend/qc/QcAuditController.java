package com.adcausalrisk.backend.qc;

import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.adcausalrisk.backend.common.Envelope;
import com.adcausalrisk.backend.common.PageResult;
import com.adcausalrisk.backend.qc.dto.QcListQueryRequest;
import com.adcausalrisk.backend.qc.dto.QcListView;
import com.adcausalrisk.backend.qc.dto.QcStatsView;
import com.adcausalrisk.backend.qc.dto.QcSubmitRequest;
import com.adcausalrisk.backend.security.AppUserPrincipal;

import jakarta.validation.Valid;

/**
 * REST endpoints for the QC audit module.
 *
 * <p>Base path {@code /api/qc}. Every endpoint requires authentication
 * (enforced by {@code SecurityConfig.authorizeHttpRequests("/api/**").authenticated()}).
 * Fine-grained role checks live in {@link QcAuditService} — this controller only
 * bridges HTTP to the service and extracts the {@link AppUserPrincipal} from the
 * injected {@link Authentication}.
 *
 * <p>Three endpoints today:
 * <ul>
 *   <li>{@code GET  /api/qc/list}  — paged audit queue (any authenticated user).</li>
 *   <li>{@code GET  /api/qc/stats} — dashboard counts per status (any authenticated user).</li>
 *   <li>{@code POST /api/qc/{id}/audit} — submit APPROVED / REJECTED (ADMIN or RESEARCHER only).</li>
 * </ul>
 */
@RestController
@RequestMapping("/api/qc")
public class QcAuditController {

    private final QcAuditService qcAuditService;

    public QcAuditController(QcAuditService qcAuditService) {
        this.qcAuditService = qcAuditService;
    }

    /**
     * {@code GET /api/qc/list} — paged QC audit queue.
     *
     * <p>All query parameters are optional:
     * <table>
     *   <tr><td>{@code subjectCode}</td><td>LIKE match, nullable</td></tr>
     *   <tr><td>{@code subjectAlias}</td><td>LIKE match, nullable</td></tr>
     *   <tr><td>{@code status}</td><td>PENDING / APPROVED / REJECTED, nullable</td></tr>
     *   <tr><td>{@code page}</td><td>defaults to 1, clamped to [1, 100]</td></tr>
     *   <tr><td>{@code pageSize}</td><td>defaults to 20, clamped to [1, 100]</td></tr>
     * </table>
     *
     * <p>DOCTOR / PATIENT currently see every row — row-level filtering by
     * {@code subject_permission} can be layered on in the service when needed.
     */
    @GetMapping("/list")
    public Envelope<PageResult<QcListView>> list(
            @RequestParam(required = false) String subjectCode,
            @RequestParam(required = false) String subjectAlias,
            @RequestParam(required = false) String status,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int pageSize,
            Authentication authentication) {

        QcListQueryRequest query = new QcListQueryRequest(subjectCode, subjectAlias, status);
        AppUserPrincipal principal = (AppUserPrincipal) authentication.getPrincipal();
        return Envelope.success(qcAuditService.getQcList(query, page, pageSize, principal));
    }

    /**
     * {@code GET /api/qc/stats} — three-bucket dashboard counts.
     *
     * <p>Returns {@code { pendingCount, approvedCount, rejectedCount }}.
     * Any authenticated user may view this high-level aggregate.
     */
    @GetMapping("/stats")
    public Envelope<QcStatsView> stats(Authentication authentication) {
        AppUserPrincipal principal = (AppUserPrincipal) authentication.getPrincipal();
        return Envelope.success(qcAuditService.getQcStats(principal));
    }

    /**
     * {@code POST /api/qc/{id}/audit} — submit a decision on a PENDING row.
     *
     * <p>Request body (all required unless noted):
     * <pre>
     * {
     *   "status":         "APPROVED" | "REJECTED",
     *   "abnormalItems":  ["...", "..."],   // optional JSON array string
     *   "auditComment":   "审核意见"
     * }
     * </pre>
     *
     * <p>Errors:
     * <ul>
     *   <li>400 — DTO validation fails (status not APPROVED/REJECTED, missing auditComment).</li>
     *   <li>400 — record id does not exist, or is not in PENDING state.</li>
     *   <li>403 — caller is DOCTOR / PATIENT (only ADMIN / RESEARCHER may decide).</li>
     * </ul>
     *
     * <p>The auditor's userId is taken from the session principal, not the request body —
     * the client cannot impersonate another auditor.
     */
    @PostMapping("/{id}/audit")
    public Envelope<QcListView> submitAudit(
            @PathVariable Long id,
            @Valid @RequestBody QcSubmitRequest request,
            Authentication authentication) {

        AppUserPrincipal principal = (AppUserPrincipal) authentication.getPrincipal();
        return Envelope.success(qcAuditService.submitAudit(id, request, principal));
    }
}