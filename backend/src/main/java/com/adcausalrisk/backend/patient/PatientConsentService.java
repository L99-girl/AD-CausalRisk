package com.adcausalrisk.backend.patient;

import com.adcausalrisk.backend.audit.AuditService;
import com.adcausalrisk.backend.common.BusinessException;
import com.adcausalrisk.backend.common.ErrorCode;
import com.adcausalrisk.backend.security.AppUserPrincipal;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;

/**
 * 患者授权中心：记录「是否允许科研使用」「是否允许随访联系」，以及患者随时撤回的决定。
 *
 * <p>授权表是只追加的：每次变更插入一行，当前状态取最新一行。撤回不需要 UPDATE 覆盖历史，
 * 「谁在什么时候把授权改成了什么」这条线索不会被后来的写入抹掉。
 *
 * <p>本服务只负责记录与展示，不改变研究侧、随访侧的既有读取逻辑。
 */
@Service
public class PatientConsentService {

    private final JdbcTemplate jdbc;
    private final PatientSummaryService summary;
    private final AuditService audit;

    public PatientConsentService(JdbcTemplate jdbc, PatientSummaryService summary, AuditService audit) {
        this.jdbc = jdbc;
        this.summary = summary;
        this.audit = audit;
    }

    /** 一条授权记录；列表按时间倒序，第一条就是当前生效的授权。 */
    public record ConsentRecord(boolean researchUse, boolean followUpContact, Instant recordedAt) {}

    /**
     * {@code decided=false} 表示患者从未表态，此时 {@code researchUse}/{@code followUpContact}
     * 只是占位值，前端应显示「未设置」而不是「不允许」。
     */
    public record ConsentView(
            boolean bound,
            Long subjectId,
            String subjectCode,
            String alias,
            boolean decided,
            boolean researchUse,
            boolean followUpContact,
            Instant updatedAt,
            List<ConsentRecord> history) {}

    private static void requirePatient(AppUserPrincipal principal) {
        if (!principal.roleCodes().contains("PATIENT")) {
            throw new BusinessException(ErrorCode.ACCESS_DENIED, "仅患者本人可管理授权");
        }
    }

    @Transactional(readOnly = true)
    public ConsentView currentConsent(AppUserPrincipal principal) {
        requirePatient(principal);
        Long subjectId = summary.subjectForPatient(principal);
        if (subjectId == null) {
            return new ConsentView(false, null, null, null, false, false, false, null, List.of());
        }
        return view(subjectId, principal);
    }

    /**
     * 记录一次授权变更。撤回与授予走同一条路径：前端把开关的最终状态提交上来，这里追加一行，
     * 因此「撤回」也是一条可追溯的记录，而不是把旧行删掉。
     */
    @Transactional
    public ConsentView saveConsent(AppUserPrincipal principal, boolean researchUse, boolean followUpContact) {
        requirePatient(principal);
        Long subjectId = summary.subjectForPatient(principal);
        if (subjectId == null) {
            throw new BusinessException(ErrorCode.VALIDATION_ERROR, "账号还没有绑定健康档案，暂时无法设置授权");
        }
        jdbc.update(
                "INSERT INTO patient_consent_record"
                        + " (subject_id, user_id, research_use, follow_up_contact, recorded_at)"
                        + " VALUES (?, ?, ?, ?, ?)",
                subjectId,
                principal.userId(),
                researchUse,
                followUpContact,
                Timestamp.from(Instant.now()));
        audit.recordQuietly(
                principal.userId(),
                "PATIENT_CONSENT",
                "患者更新授权 subjectId=" + subjectId
                        + " 科研使用=" + (researchUse ? "允许" : "不允许")
                        + " 随访联系=" + (followUpContact ? "允许" : "不允许"));
        return view(subjectId, principal);
    }

    private ConsentView view(Long subjectId, AppUserPrincipal principal) {
        String[] subject = jdbc.query(
                "SELECT subject_code, alias FROM subject WHERE id = ?",
                rs -> rs.next() ? new String[] {rs.getString(1), rs.getString(2)} : null,
                subjectId);
        List<ConsentRecord> history = jdbc.query(
                "SELECT research_use, follow_up_contact, recorded_at FROM patient_consent_record"
                        + " WHERE subject_id = ? AND user_id = ? ORDER BY recorded_at DESC, id DESC",
                (rs, rowNum) -> new ConsentRecord(
                        rs.getBoolean(1),
                        rs.getBoolean(2),
                        rs.getTimestamp(3).toInstant()),
                subjectId,
                principal.userId());
        ConsentRecord latest = history.isEmpty() ? null : history.get(0);
        return new ConsentView(
                true,
                subjectId,
                subject == null ? null : subject[0],
                subject == null ? null : subject[1],
                latest != null,
                latest != null && latest.researchUse(),
                latest != null && latest.followUpContact(),
                latest == null ? null : latest.recordedAt(),
                history);
    }
}
