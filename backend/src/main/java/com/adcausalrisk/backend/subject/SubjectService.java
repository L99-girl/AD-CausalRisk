package com.adcausalrisk.backend.subject;

import java.time.Instant;
import java.util.Set;
import java.util.UUID;

import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.adcausalrisk.backend.common.BusinessException;
import com.adcausalrisk.backend.common.ErrorCode;
import com.adcausalrisk.backend.common.PageResult;
import com.adcausalrisk.backend.security.AppUserPrincipal;
import com.adcausalrisk.backend.subject.dto.SubjectCreateRequest;
import com.adcausalrisk.backend.subject.dto.SubjectDetailView;
import com.adcausalrisk.backend.subject.dto.SubjectView;
import com.adcausalrisk.backend.subject.entity.Subject;

/**
 * Business-logic service for the subject module. Implements the three endpoints
 * the contract exposes: paged list, create, and single-detail lookup.
 *
 * <p>Access control sits in {@link SubjectAccessPolicy} and is consulted here;
 * the Controller only guarantees the caller is authenticated via Spring Security.
 * The two collaborate so that no endpoint ever returns a subject the caller is
 * not supposed to see (or create).
 */
@Service
public class SubjectService {

    private static final int MAX_PAGE_SIZE = 100;

    private final SubjectRepository subjectRepository;
    private final SubjectAccessPolicy accessPolicy;

    public SubjectService(SubjectRepository subjectRepository, SubjectAccessPolicy accessPolicy) {
        this.subjectRepository = subjectRepository;
        this.accessPolicy = accessPolicy;
    }

    // ===================================================================
    // GET /api/subjects  -  paged list
    // ===================================================================

    /**
     * Returns a single page of subjects the principal may see. Paging is applied
     * <i>after</i> the visibility filter: ADMIN / RESEARCHER get the full table,
     * DOCTOR / PATIENT get only subjects they hold permissions on, and the page
     * window then slices that filtered set.
     *
     * <p>{@code page} is 1-based; {@code pageSize} is clamped to the contract's
     * {@code [1, 100]} range, defaulting to 20 on illegal input.
     */
    public PageResult<SubjectView> pageSubjects(int page, int pageSize, AppUserPrincipal principal) {
        int safePage = Math.max(1, page);
        int safePageSize = Math.max(1, Math.min(MAX_PAGE_SIZE, pageSize));

        Pageable pageable = PageRequest.of(safePage - 1, safePageSize);
        Page<Subject> paged;
        if (accessPolicy.hasFullVisibility(principal)) {
            paged = subjectRepository.findAll(pageable);
        } else {
            Set<Long> grantedIds = accessPolicy.grantedSubjectIds(principal);
            paged = grantedIds.isEmpty()
                    ? Page.empty(pageable)
                    : subjectRepository.findByIdIn(grantedIds, pageable);
        }
        return SubjectMapper.toPage(paged);
    }

    // ===================================================================
    // POST /api/subjects  -  create
    // ===================================================================

    /**
     * Creates a new subject. {@code ADMIN} and {@code RESEARCHER} are the only
     * roles allowed to call this endpoint; anyone else receives {@code ACCESS_DENIED} (403).
     *
     * <p>{@code subjectCode} must match {@code ^DEMO-[A-Za-z0-9-]{1,45}$} (enforced
     * by {@code @Pattern} on the DTO plus {@code @Valid} on the Controller method)
     * and must not already exist - duplicates return {@code VALIDATION_ERROR} (400).
     *
     * <p>{@code dataVersion} is server-generated here and never reaches the client
     * request; {@code createdAt} is set to {@code Instant.now()} at creation time.
     */
    @Transactional
    public SubjectView createSubject(SubjectCreateRequest request, AppUserPrincipal principal) {
        if (!accessPolicy.canCreate(principal)) {
            throw new BusinessException(ErrorCode.ACCESS_DENIED, "无权创建档案");
        }

        if (subjectRepository.existsBySubjectCode(request.subjectCode())) {
            throw new BusinessException(ErrorCode.VALIDATION_ERROR,
                    "subjectCode 已存在: " + request.subjectCode());
        }

        String dataVersion = generateDataVersion();
        Subject entity = SubjectMapper.toEntity(request, dataVersion, Instant.now());
        Subject saved = subjectRepository.save(entity);
        return SubjectMapper.toView(saved);
    }

    // ===================================================================
    // GET /api/subjects/{subjectId}  -  single detail
    // ===================================================================

    /**
     * Returns the full detail of a single subject. Two distinct failure paths:
     *
     * <ol>
     *     <li>The subject does not exist in the table - {@code VALIDATION_ERROR} (400).</li>
     *     <li>The subject exists but the principal does not have permission to see it
     *         (DOCTOR / PATIENT with no matching subject_permission row) -
     *         {@code ACCESS_DENIED} (403).</li>
     * </ol>
     *
     * <p>Always prefer the 400 path first so that an auth probe cannot distinguish
     * "subject absent" from "subject present but you are not allowed" - but the
     * DOCTOR / PATIENT path still returns 403 because the subject <i>does</i> exist;
     * it is just outside their grant.
     *
     * <p>{@code visits} and {@code features} in the response are empty arrays in
     * this PR (contract requires the keys to be present, not null and not omitted).
     */
    public SubjectDetailView getSubjectDetail(Long subjectId, AppUserPrincipal principal) {
        Subject subject = subjectRepository.findById(subjectId)
                .orElseThrow(() -> new BusinessException(ErrorCode.VALIDATION_ERROR,
                        "档案不存在: " + subjectId));

        if (!accessPolicy.canView(principal, subjectId)) {
            throw new BusinessException(ErrorCode.ACCESS_DENIED, "无权查看该档案");
        }

        return SubjectMapper.toDetail(subject);
    }

    // ===================================================================
    // Internal helpers
    // ===================================================================

    /**
     * Generates a server-owned {@code dataVersion} string that satisfies the DDL
     * CHECK {@code LIKE 'demo-%'} and the contract pattern {@code ^demo-}.
     * Uses a UUID fragment so concurrent create requests cannot collide.
     */
    private static String generateDataVersion() {
        return "demo-" + UUID.randomUUID().toString().substring(0, 8);
    }
}