package com.adcausalrisk.backend.visit;

import java.time.LocalDate;
import java.time.format.DateTimeParseException;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.adcausalrisk.backend.common.BusinessException;
import com.adcausalrisk.backend.common.ErrorCode;
import com.adcausalrisk.backend.security.AppUserPrincipal;
import com.adcausalrisk.backend.subject.SubjectAccessPolicy;
import com.adcausalrisk.backend.subject.SubjectRepository;
import com.adcausalrisk.backend.subject.dto.VisitResultView;
import com.adcausalrisk.backend.visit.dto.VisitCreateRequest;
import com.adcausalrisk.backend.visit.entity.Visit;

import jakarta.persistence.EntityManager;

/**
 * Business logic for the single visit operation of the frozen contract,
 * {@code POST /api/subjects/{subjectId}/visits}.
 *
 * <p>Ordering of the checks matters: permission first, then subject existence, then the
 * duplicate visit code, and only then the insert.
 *
 * <p>There is deliberately no read method here. The contract exposes no visit collection
 * endpoint; visits are read through {@code SubjectDetail.visits}, which the subject module
 * assembles in {@code SubjectService.getSubjectDetail}.
 */
@Service
public class VisitService {

    private static final Logger log = LoggerFactory.getLogger(VisitService.class);

    private final VisitRepository visitRepository;

    private final SubjectRepository subjectRepository;

    private final SubjectAccessPolicy accessPolicy;

    private final EntityManager entityManager;

    private final ApplicationEventPublisher events;

    public VisitService(VisitRepository visitRepository,
                        SubjectRepository subjectRepository,
                        SubjectAccessPolicy accessPolicy,
                        EntityManager entityManager,
                        ApplicationEventPublisher events) {
        this.visitRepository = visitRepository;
        this.subjectRepository = subjectRepository;
        this.accessPolicy = accessPolicy;
        this.entityManager = entityManager;
        this.events = events;
    }

    /**
     * Creates one visit for one subject.
     *
     * <p>{@code ADMIN} and {@code RESEARCHER} may create visits on any subject; a {@code DOCTOR}
     * may create one only on a subject they hold {@code VIEW} or {@code MANAGE} for. This
     * reuses {@link SubjectAccessPolicy#canOperate}, so it never lets a doctor behave like a
     * researcher who can invent brand-new subject rows.
     *
     * <p>No further per-subject check is needed on top of {@code canOperate} today: a doctor is
     * only admitted when the permission lookup above returns VIEW or MANAGE for this subject, and
     * those same lookups decide {@code canView}. If {@code canOperate} is ever narrowed further,
     * a mirroring {@code canView} gate must be added at this point.
     *
     * <p>A missing subject is reported as 400 {@code VALIDATION_ERROR} rather than 404,
     * matching the convention the subject module established (the frozen contract declares no
     * 404 for business resources). Checking it up front also keeps the
     * {@code fk_visit_subject} constraint from turning into a 500.
     */
    @Transactional
    public VisitResultView createVisit(Long subjectId, VisitCreateRequest request,
                                       AppUserPrincipal principal) {
        // Permission first: ADMIN/RESEARCHER may record a visit on any subject; a DOCTOR needs
        // VIEW or MANAGE on this specific subject. PATIENT is always refused.
        if (!accessPolicy.canOperate(principal, subjectId)) {
            throw new BusinessException(ErrorCode.ACCESS_DENIED, "无权创建访视");
        }

        // Parsed before any database work: the DTO carries the raw text so @Pattern can enforce
        // the contract's ^\d{4}-\d{2}-\d{2}$ (see VisitCreateRequest), and an impossible calendar
        // date must fail here as a 400 rather than escaping as a DateTimeParseException (500).
        LocalDate visitDate = parseVisitDate(request.visitDate());

        if (!subjectRepository.existsById(subjectId)) {
            throw new BusinessException(ErrorCode.VALIDATION_ERROR, "档案不存在: " + subjectId);
        }

        if (visitRepository.existsBySubjectIdAndVisitCode(subjectId, request.visitCode())) {
            throw new BusinessException(ErrorCode.VALIDATION_ERROR,
                    "visitCode 已存在: " + request.visitCode());
        }

        try {
            // saveAndFlush keeps the INSERT inside this try block. With an IDENTITY id the insert
            // already happens at save() time, but that is an implementation detail of the id
            // strategy; flushing explicitly means a constraint violation is caught here instead
            // of escaping at commit as a 500.
            Visit saved = visitRepository.saveAndFlush(
                    VisitMapper.toEntity(subjectId, request, visitDate));

            // The response must report what the database actually stored. DECIMAL(5,2) rounds a
            // score that carries more than two decimals, and Hibernate does not copy the stored
            // value back into the entity - a plain findById would hand back the same cached
            // instance and report the unrounded number, so POST and a later GET would disagree.
            // Refreshing re-reads the row that was just written.
            entityManager.refresh(saved);

            // ── QC auto-trigger (decoupled via event) ──────────────────
            // Publishing inside the @Transactional method makes Spring defer delivery
            // until AFTER_COMMIT. The listener runs in its own REQUIRES_NEW transaction —
            // by the time it fires, this Visit row is already durably committed to the DB,
            // so any QC failure (FK, constraint, anything) stays isolated and cannot roll
            // back the visit that the caller just created. The VisitCreatedEvent carries
            // only the PK so the listener can re-load a fresh, attached entity in its own
            // session (we must not pass the here-entity; after commit it will be detached).
            events.publishEvent(new VisitCreatedEvent(saved.getId(), principal.userId()));

            return VisitMapper.toResultView(saved);
        } catch (DataIntegrityViolationException exception) {
            // Any integrity violation can land here, not only a duplicate visit code: the subject
            // may have been deleted between the check above and this insert (fk_visit_subject),
            // and a CHECK constraint could fire too. The message therefore must not claim which
            // constraint failed. The DDL constraint is the source of truth; this only decides
            // that the caller gets 400 rather than 500.
            log.debug("visit insert rejected by a database constraint", exception);
            throw new BusinessException(ErrorCode.VALIDATION_ERROR,
                    "无法保存访视：档案可能已被删除，或 visitCode 已存在");
        }
    }

    /**
     * Parses the strictly-shaped date text. {@code @Pattern} already guarantees the shape, so the
     * only way this fails is a shape-valid but impossible date such as {@code 2025-02-30}.
     */
    private static LocalDate parseVisitDate(String text) {
        try {
            return LocalDate.parse(text);
        } catch (DateTimeParseException exception) {
            throw new BusinessException(ErrorCode.VALIDATION_ERROR, "visitDate 不是有效日期");
        }
    }
}