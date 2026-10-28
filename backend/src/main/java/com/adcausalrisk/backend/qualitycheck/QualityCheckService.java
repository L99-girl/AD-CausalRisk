package com.adcausalrisk.backend.qualitycheck;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

import com.adcausalrisk.backend.common.BusinessException;
import com.adcausalrisk.backend.common.ErrorCode;
import com.adcausalrisk.backend.security.AppUserPrincipal;
import com.adcausalrisk.backend.subject.SubjectAccessPolicy;
import com.adcausalrisk.backend.subject.SubjectRepository;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

/**
 * {@code POST /api/subjects/{subjectId}/quality-checks}.
 *
 * <p>The contract's summary is "执行并保存质量检查", but there is no {@code quality_check} table
 * (V1 has none). This implementation therefore computes the check from the rows that do exist and
 * returns the contract shape without persisting it; the {@code id} is the subject id, so repeated
 * calls for one subject are stable. See README section 13 for the limitation.
 */
@Service
public class QualityCheckService {

    /** Bump when the rules below change; part of the response so callers can log it. */
    static final String RULE_VERSION = "qc-rules-demo-v1";

    private final JdbcTemplate jdbc;
    private final SubjectRepository subjectRepository;
    private final SubjectAccessPolicy accessPolicy;
    private final java.time.Clock clock;

    public QualityCheckService(
            JdbcTemplate jdbc,
            SubjectRepository subjectRepository,
            SubjectAccessPolicy accessPolicy,
            java.time.Clock clock) {
        this.jdbc = jdbc;
        this.subjectRepository = subjectRepository;
        this.accessPolicy = accessPolicy;
        this.clock = clock;
    }

    /** {@code QualityCheck} in contracts/java-business.target.openapi.json. */
    public record QualityCheckResult(
            long id,
            long subjectId,
            String qualityStatus,
            List<String> issues,
            Instant checkedAt,
            String ruleVersion) {
    }

    public QualityCheckResult check(Long subjectId, AppUserPrincipal principal) {
        if (!accessPolicy.canCreate(principal)) {
            throw new BusinessException(ErrorCode.ACCESS_DENIED, "无权执行质量检查");
        }
        if (!subjectRepository.existsById(subjectId)) {
            throw new BusinessException(ErrorCode.VALIDATION_ERROR, "档案不存在");
        }

        List<String> issues = new ArrayList<>();
        Integer visits = jdbc.queryForObject(
                "SELECT COUNT(*) FROM visit WHERE subject_id = ?", Integer.class, subjectId);
        Integer pending = jdbc.queryForObject(
                "SELECT COUNT(*) FROM qc_audit_record q JOIN visit v ON q.visit_id = v.id"
                        + " WHERE v.subject_id = ? AND q.status = 'PENDING'",
                Integer.class, subjectId);

        String status;
        if (visits == null || visits == 0) {
            status = "BLOCKED";
            issues.add("无访视数据，无法评估风险");
        } else if (pending != null && pending > 0) {
            status = "WARN";
            issues.add("存在 " + pending + " 条待审核的质控记录");
        } else {
            status = "PASS";
        }

        return new QualityCheckResult(
                subjectId, subjectId, status, List.copyOf(issues), Instant.now(clock), RULE_VERSION);
    }
}
