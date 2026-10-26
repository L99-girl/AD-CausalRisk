package com.adcausalrisk.backend.qc;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

import com.adcausalrisk.backend.subject.SubjectRepository;
import com.adcausalrisk.backend.subject.entity.Subject;
import com.adcausalrisk.backend.subject.entity.Subject.Status;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.transaction.annotation.Transactional;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
@Transactional
class QcAuditApiTest {

    private static final String DEMO_PASSWORD = "DemoPass!2026";

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private SubjectRepository subjectRepository;

    @Autowired
    private JdbcTemplate jdbc;

    // ===================================================================
    // 1. GET /api/qc/stats
    // ===================================================================

    @Test
    void adminSeesDashboardStats() throws Exception {
        MockHttpSession admin = login("admin");

        JsonNode body = bodyOf(mockMvc.perform(get("/api/qc/stats").session(admin))
                .andExpect(status().isOk())
                .andReturn());

        assertThat(body.get("code").asInt()).isZero();
        JsonNode data = body.get("data");
        assertThat(data.get("pendingCount")).isNotNull();
        assertThat(data.get("approvedCount")).isNotNull();
        assertThat(data.get("rejectedCount")).isNotNull();
        assertThat(data.get("pendingCount").asLong()).isZero();
    }

    @Test
    void doctorSeesDashboardStats() throws Exception {
        MockHttpSession doctor = login("doctor");
        JsonNode body = bodyOf(mockMvc.perform(get("/api/qc/stats").session(doctor))
                .andExpect(status().isOk())
                .andReturn());
        assertThat(body.get("code").asInt()).isZero();
    }

    @Test
    void anonymousIsRefusedForStats() throws Exception {
        JsonNode body = bodyOf(mockMvc.perform(get("/api/qc/stats"))
                .andExpect(status().isUnauthorized())
                .andReturn());
        assertThat(body.get("errorCode").asText()).isEqualTo("UNAUTHENTICATED");
    }

    @Test
    void statsAggregateRowsPerStatus() throws Exception {
        MockHttpSession admin = login("admin");
        Subject subject = seedSubject("QC-STATS");
        Long adminId = userId("admin");
        Instant now = Instant.now();

        jdbc.update(
                "INSERT INTO qc_audit_record (subject_id, target_type, source_type, status, "
                        + "auditor_id, abnormal_items, audit_comment, created_at, updated_at) "
                        + "VALUES (?, 'VISIT', 'MANUAL_REVIEW', 'PENDING', ?, '[\"异常1\"]', NULL, ?, ?)",
                subject.getId(), adminId, now, now);

        jdbc.update(
                "INSERT INTO qc_audit_record (subject_id, target_type, source_type, status, "
                        + "auditor_id, abnormal_items, audit_comment, audited_at, created_at, updated_at) "
                        + "VALUES (?, 'VISIT', 'MANUAL_REVIEW', 'APPROVED', ?, '[\"异常2\"]', '已确认无误', ?, ?, ?)",
                subject.getId(), adminId, now, now, now);

        jdbc.update(
                "INSERT INTO qc_audit_record (subject_id, target_type, source_type, status, "
                        + "auditor_id, abnormal_items, audit_comment, audited_at, created_at, updated_at) "
                        + "VALUES (?, 'VISIT', 'MANUAL_REVIEW', 'REJECTED', ?, '[\"异常3\"]', '数据错误', ?, ?, ?)",
                subject.getId(), adminId, now, now, now);

        JsonNode data = bodyOf(mockMvc.perform(get("/api/qc/stats").session(admin))
                .andExpect(status().isOk())
                .andReturn()).get("data");

        assertThat(data.get("pendingCount").asLong()).isEqualTo(1);
        assertThat(data.get("approvedCount").asLong()).isEqualTo(1);
        assertThat(data.get("rejectedCount").asLong()).isEqualTo(1);
    }

    // ===================================================================
    // 2. GET /api/qc/list
    // ===================================================================

    @Test
    void emptyListReturnsEmptyArrayNotError() throws Exception {
        MockHttpSession admin = login("admin");

        JsonNode data = bodyOf(mockMvc.perform(get("/api/qc/list").session(admin))
                .andExpect(status().isOk())
                .andReturn()).get("data");

        assertThat(data.get("items").isArray()).isTrue();
        assertThat(data.get("items").size()).isZero();
        assertThat(data.get("total").asLong()).isZero();
    }

    @Test
    void listReturnsJoinedSubjectAndAuditorNames() throws Exception {
        MockHttpSession admin = login("admin");
        Subject subject = seedSubject("QC-LIST-JOIN");
        Long adminId = userId("admin");
        Instant now = Instant.now();

        jdbc.update(
                "INSERT INTO qc_audit_record (subject_id, target_type, source_type, status, "
                        + "auditor_id, abnormal_items, created_at, updated_at) "
                        + "VALUES (?, 'VISIT', 'MANUAL_REVIEW', 'PENDING', ?, '[\"MMSE 超出范围\"]', ?, ?)",
                subject.getId(), adminId, now, now);

        JsonNode first = bodyOf(mockMvc.perform(get("/api/qc/list").session(admin))
                .andExpect(status().isOk())
                .andReturn()).get("data").get("items").get(0);

        assertThat(first.get("subjectCode").asText()).isEqualTo("QC-LIST-JOIN");
        assertThat(first.get("subjectAlias").asText()).isEqualTo("种子档案-QC-LIST-JOIN");
        assertThat(first.get("auditorName").asText()).isEqualTo("admin");
        assertThat(first.get("status").asText()).isEqualTo("PENDING");
        assertThat(first.get("abnormalItems").asText()).isEqualTo("[\"MMSE 超出范围\"]");
    }

    @Test
    void listSupportsStatusFilter() throws Exception {
        MockHttpSession admin = login("admin");
        Subject subject = seedSubject("QC-LIST-FILTER");
        Long adminId = userId("admin");
        Instant now = Instant.now();

        jdbc.update(
                "INSERT INTO qc_audit_record (subject_id, target_type, source_type, status, "
                        + "auditor_id, created_at, updated_at) "
                        + "VALUES (?, 'VISIT', 'MANUAL_REVIEW', 'PENDING', ?, ?, ?)",
                subject.getId(), adminId, now, now);
        jdbc.update(
                "INSERT INTO qc_audit_record (subject_id, target_type, source_type, status, "
                        + "auditor_id, audited_at, created_at, updated_at) "
                        + "VALUES (?, 'VISIT', 'MANUAL_REVIEW', 'APPROVED', ?, ?, ?, ?)",
                subject.getId(), adminId, now, now, now);

        JsonNode pending = bodyOf(mockMvc.perform(get("/api/qc/list")
                        .param("status", "PENDING").session(admin))
                .andExpect(status().isOk())
                .andReturn()).get("data");

        assertThat(pending.get("items").size()).isEqualTo(1);
        assertThat(pending.get("items").get(0).get("status").asText()).isEqualTo("PENDING");

        JsonNode approved = bodyOf(mockMvc.perform(get("/api/qc/list")
                        .param("status", "APPROVED").session(admin))
                .andExpect(status().isOk())
                .andReturn()).get("data");

        assertThat(approved.get("items").size()).isEqualTo(1);
        assertThat(approved.get("items").get(0).get("status").asText()).isEqualTo("APPROVED");
    }

    @Test
    void listPaginatesCorrectly() throws Exception {
        MockHttpSession admin = login("admin");
        Subject subject = seedSubject("QC-PAGE");
        Long adminId = userId("admin");
        Instant now = Instant.now();

        for (int i = 0; i < 5; i++) {
            jdbc.update(
                    "INSERT INTO qc_audit_record (subject_id, target_type, source_type, status, "
                            + "auditor_id, created_at, updated_at) "
                            + "VALUES (?, 'VISIT', 'MANUAL_REVIEW', 'PENDING', ?, ?, ?)",
                    subject.getId(), adminId, now.plusMillis(i * 1000L), now.plusMillis(i * 1000L));
        }

        JsonNode page1 = bodyOf(mockMvc.perform(get("/api/qc/list")
                        .param("page", "1").param("pageSize", "2").session(admin))
                .andExpect(status().isOk())
                .andReturn()).get("data");

        assertThat(page1.get("items").size()).isEqualTo(2);
        assertThat(page1.get("total").asLong()).isEqualTo(5);

        JsonNode page2 = bodyOf(mockMvc.perform(get("/api/qc/list")
                        .param("page", "2").param("pageSize", "2").session(admin))
                .andExpect(status().isOk())
                .andReturn()).get("data");

        assertThat(page2.get("items").size()).isEqualTo(2);
    }

    @Test
    void badPaginationParamsAreClampedNotRejected() throws Exception {
        MockHttpSession admin = login("admin");
        JsonNode body = bodyOf(mockMvc.perform(get("/api/qc/list")
                        .param("page", "0").param("pageSize", "0").session(admin))
                .andExpect(status().isOk())
                .andReturn());
        assertThat(body.get("code").asInt()).isZero();
    }

    @Test
    void anonymousIsRefusedForList() throws Exception {
        JsonNode body = bodyOf(mockMvc.perform(get("/api/qc/list"))
                .andExpect(status().isUnauthorized())
                .andReturn());
        assertThat(body.get("errorCode").asText()).isEqualTo("UNAUTHENTICATED");
    }

    @Test
    void doctorListScopedToGrantedSubjectsOnly() throws Exception {
        MockHttpSession admin = login("admin");
        MockHttpSession doctor = login("doctor");
        Long doctorId = userId("doctor");
        Long adminId = userId("admin");
        Instant now = Instant.now();

        Subject subjectA = seedSubject("QC-DOCTOR-A");
        Subject subjectB = seedSubject("QC-DOCTOR-B");

        jdbc.update(
                "INSERT INTO qc_audit_record (subject_id, target_type, source_type, status, "
                        + "auditor_id, created_at, updated_at) "
                        + "VALUES (?, 'VISIT', 'MANUAL_REVIEW', 'PENDING', ?, ?, ?)",
                subjectA.getId(), adminId, now, now);
        jdbc.update(
                "INSERT INTO qc_audit_record (subject_id, target_type, source_type, status, "
                        + "auditor_id, created_at, updated_at) "
                        + "VALUES (?, 'VISIT', 'MANUAL_REVIEW', 'PENDING', ?, ?, ?)",
                subjectB.getId(), adminId, now, now);

        jdbc.update(
                "INSERT INTO subject_permission (subject_id, user_id, permission_type) "
                        + "VALUES (?, ?, 'VIEW')",
                subjectA.getId(), doctorId);

        JsonNode doctorList = bodyOf(mockMvc.perform(get("/api/qc/list").session(doctor))
                .andExpect(status().isOk())
                .andReturn()).get("data");

        assertThat(doctorList.get("items").size()).isEqualTo(1);
        assertThat(doctorList.get("items").get(0).get("subjectCode").asText())
                .isEqualTo("QC-DOCTOR-A");
        assertThat(doctorList.get("total").asLong()).isEqualTo(1);

        JsonNode adminList = bodyOf(mockMvc.perform(get("/api/qc/list").session(admin))
                .andExpect(status().isOk())
                .andReturn()).get("data");
        assertThat(adminList.get("items").size()).isEqualTo(2);
        assertThat(adminList.get("total").asLong()).isEqualTo(2);
    }

    /**
     * P1 privacy: a DOCTOR who <em>is</em> granted on a subject must still not see the
     * clinical details (abnormalItems) or internal audit notes (auditComment) on the rows
     * they are allowed to list. Only ADMIN / RESEARCHER can inspect those fields.
     *
     * <p>Contrasts with {@link #doctorListScopedToGrantedSubjectsOnly} which proves the
     * row-level subject filter — this one adds the field-level filter on top.
     */
    @Test
    void doctorListSensitiveFieldsAreMasked() throws Exception {
        MockHttpSession admin = login("admin");
        MockHttpSession doctor = login("doctor");
        Long doctorId = userId("doctor");
        Long adminId = userId("admin");
        Instant now = Instant.now();

        Subject subject = seedSubject("QC-SENSITIVE-MASK");

        jdbc.update(
                "INSERT INTO qc_audit_record (subject_id, target_type, source_type, status, "
                        + "auditor_id, abnormal_items, audit_comment, created_at, updated_at) "
                        + "VALUES (?, 'VISIT', 'MANUAL_REVIEW', 'PENDING', ?, ?, ?, ?, ?)",
                subject.getId(), adminId,
                "[\"MMSE 得分 99 超出临床范围\"]",
                "需要重新录入，原始值疑似笔误",
                now, now);

        jdbc.update(
                "INSERT INTO subject_permission (subject_id, user_id, permission_type) "
                        + "VALUES (?, ?, 'VIEW')",
                subject.getId(), doctorId);

        JsonNode doctorItems = bodyOf(mockMvc.perform(get("/api/qc/list").session(doctor))
                .andExpect(status().isOk())
                .andReturn()).get("data").get("items");

        assertThat(doctorItems.size()).isEqualTo(1);
        JsonNode masked = doctorItems.get(0);

        assertThat(masked.get("status").asText()).isEqualTo("PENDING");
        assertThat(masked.get("subjectCode").asText()).isEqualTo("QC-SENSITIVE-MASK");
        assertThat(masked.get("targetType").asText()).isEqualTo("VISIT");
        assertThat(masked.get("createdAt")).isNotNull();

        assertThat(masked.get("abnormalItems").isNull())
                .as("DOCTOR must not see abnormalItems (clinical PHI)");
        assertThat(masked.get("auditComment").isNull())
                .as("DOCTOR must not see auditComment (internal notes)");

        JsonNode adminItems = bodyOf(mockMvc.perform(get("/api/qc/list").session(admin))
                .andExpect(status().isOk())
                .andReturn()).get("data").get("items");

        assertThat(adminItems.size()).isEqualTo(1);
        JsonNode full = adminItems.get(0);
        assertThat(full.get("abnormalItems").asText())
                .isEqualTo("[\"MMSE 得分 99 超出临床范围\"]");
        assertThat(full.get("auditComment").asText())
                .isEqualTo("需要重新录入，原始值疑似笔误");
    }

    /**
     * Same masking contract for PATIENT — they also only see the audit progress, not
     * the clinical or internal-comment details. Requires a subject_permission grant first.
     */
    @Test
    void patientListSensitiveFieldsAreMasked() throws Exception {
        MockHttpSession patient = login("patient");
        MockHttpSession admin = login("admin");
        Long patientId = userId("patient");
        Long adminId = userId("admin");
        Instant now = Instant.now();

        Subject subject = seedSubject("QC-PATIENT-MASK");

        jdbc.update(
                "INSERT INTO qc_audit_record (subject_id, target_type, source_type, status, "
                        + "auditor_id, abnormal_items, audit_comment, created_at, updated_at) "
                        + "VALUES (?, 'VISIT', 'MANUAL_REVIEW', 'APPROVED', ?, ?, ?, ?, ?)",
                subject.getId(), adminId,
                "[\"CDR-SB 异常\"]",
                "原始分数已人工复核",
                now, now);

        jdbc.update(
                "INSERT INTO subject_permission (subject_id, user_id, permission_type) "
                        + "VALUES (?, ?, 'VIEW')",
                subject.getId(), patientId);

        JsonNode patientItems = bodyOf(mockMvc.perform(get("/api/qc/list").session(patient))
                .andExpect(status().isOk())
                .andReturn()).get("data").get("items");

        assertThat(patientItems.size()).isEqualTo(1);
        assertThat(patientItems.get(0).get("abnormalItems").isNull())
                .as("PATIENT must not see abnormalItems");
        assertThat(patientItems.get(0).get("auditComment").isNull())
                .as("PATIENT must not see auditComment");

        JsonNode adminItems = bodyOf(mockMvc.perform(get("/api/qc/list").session(admin))
                .andExpect(status().isOk())
                .andReturn()).get("data").get("items");

        assertThat(adminItems.get(0).get("abnormalItems").asText())
                .isEqualTo("[\"CDR-SB 异常\"]");
        assertThat(adminItems.get(0).get("auditComment").asText())
                .isEqualTo("原始分数已人工复核");
    }

    /**
     * P1 multi-role regression: PATIENT takes precedence over every other role.
     * An account that carries BOTH PATIENT and RESEARCHER must NOT see abnormalItems
     * or auditComment — even though RESEARCHER alone would grant full access.
     *
     * <p>This test mirrors the {@link SubjectAccessPolicy#canReadRawScores} contract
     * where the PATIENT branch is checked first and short-circuits to {@code false}.
     * Without the per-subject {@code canReadRawScores} call (i.e. the old all-or-nothing
     * {@code AUDITOR_ROLES} check), this test would fail because RESEARCHER ∈ AUDITOR_ROLES.
     */
    @Test
    void patientPlusResearcherMultiRoleListIsStillMasked() throws Exception {
        Long patientId = userId("patient");
        Long adminId = userId("admin");
        Instant now = Instant.now();

        jdbc.update(
                "INSERT INTO user_role (user_id, role_id) "
                        + "SELECT ?, r.id FROM sys_role r WHERE r.role_code = 'RESEARCHER'",
                patientId);
        try {
            Subject subject = seedSubject("QC-PATIENT-RESEARCHER");

            jdbc.update(
                    "INSERT INTO qc_audit_record (subject_id, target_type, source_type, status, "
                            + "auditor_id, abnormal_items, audit_comment, created_at, updated_at) "
                            + "VALUES (?, 'VISIT', 'MANUAL_REVIEW', 'PENDING', ?, ?, ?, ?, ?)",
                    subject.getId(), adminId,
                    "[\"MMSE 得分 99 超出临床范围\"]",
                    "需要重新录入，原始值疑似笔误",
                    now, now);

            jdbc.update(
                    "INSERT INTO subject_permission (subject_id, user_id, permission_type) "
                            + "VALUES (?, ?, 'VIEW')",
                    subject.getId(), patientId);

            MockHttpSession patientResearcher = login("patient");
            JsonNode items = bodyOf(mockMvc.perform(get("/api/qc/list").session(patientResearcher))
                    .andExpect(status().isOk())
                    .andReturn()).get("data").get("items");

            assertThat(items.size()).isEqualTo(1);
            JsonNode masked = items.get(0);

            assertThat(masked.get("status").asText()).isEqualTo("PENDING");
            assertThat(masked.get("subjectCode").asText()).isEqualTo("QC-PATIENT-RESEARCHER");
            assertThat(masked.get("abnormalItems").isNull())
                    .as("P1 multi-role leak: PATIENT ∩ RESEARCHER must NOT see abnormalItems");
            assertThat(masked.get("auditComment").isNull())
                    .as("P1 multi-role leak: PATIENT ∩ RESEARCHER must NOT see auditComment");

            MockHttpSession admin = login("admin");
            JsonNode adminItems = bodyOf(mockMvc.perform(get("/api/qc/list").session(admin))
                    .andExpect(status().isOk())
                    .andReturn()).get("data").get("items");
            assertThat(adminItems.get(0).get("abnormalItems").asText())
                    .isEqualTo("[\"MMSE 得分 99 超出临床范围\"]");
            assertThat(adminItems.get(0).get("auditComment").asText())
                    .isEqualTo("需要重新录入，原始值疑似笔误");
        } finally {
            jdbc.update(
                    "DELETE FROM user_role WHERE user_id = ? "
                            + "AND role_id = (SELECT id FROM sys_role WHERE role_code = 'RESEARCHER')",
                    patientId);
        }
    }

    @Test
    void doctorListReturnsEmptyWhenNoGrantsAtAll() throws Exception {
        MockHttpSession doctor = login("doctor");
        Long adminId = userId("admin");
        Instant now = Instant.now();

        Subject subject = seedSubject("QC-DOCTOR-NOGRANT");
        jdbc.update(
                "INSERT INTO qc_audit_record (subject_id, target_type, source_type, status, "
                        + "auditor_id, created_at, updated_at) "
                        + "VALUES (?, 'VISIT', 'MANUAL_REVIEW', 'PENDING', ?, ?, ?)",
                subject.getId(), adminId, now, now);

        JsonNode body = bodyOf(mockMvc.perform(get("/api/qc/list").session(doctor))
                .andExpect(status().isOk())
                .andReturn()).get("data");

        assertThat(body.get("items").size()).isZero();
        assertThat(body.get("total").asLong()).isZero();
    }

    // ===================================================================
    // 3. POST /api/qc/{id}/audit
    // ===================================================================

    @Test
    void doctorCannotSubmitAuditDecision() throws Exception {
        MockHttpSession doctor = login("doctor");
        Long rowId = seedPendingAuditRow();

        JsonNode body = bodyOf(mockMvc.perform(post("/api/qc/" + rowId + "/audit")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(auditRequest("APPROVED", "审核通过"))
                        .session(doctor))
                .andExpect(status().isForbidden())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("ACCESS_DENIED");
        assertThat(body.get("message").asText()).contains("无质控审核权限");

        String status = jdbc.queryForObject(
                "SELECT status FROM qc_audit_record WHERE id = ?", String.class, rowId);
        assertThat(status).isEqualTo("PENDING");
    }

    @Test
    void patientCannotSubmitAuditDecision() throws Exception {
        MockHttpSession patient = login("patient");
        Long rowId = seedPendingAuditRow();

        JsonNode body = bodyOf(mockMvc.perform(post("/api/qc/" + rowId + "/audit")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(auditRequest("APPROVED", "OK"))
                        .session(patient))
                .andExpect(status().isForbidden())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("ACCESS_DENIED");
    }

    @Test
    void adminApprovesAuditRow() throws Exception {
        MockHttpSession admin = login("admin");
        Long rowId = seedPendingAuditRow();

        JsonNode body = bodyOf(mockMvc.perform(post("/api/qc/" + rowId + "/audit")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(auditRequest("APPROVED", "数据确认无误"))
                        .session(admin))
                .andExpect(status().isOk())
                .andReturn());

        assertThat(body.get("code").asInt()).isZero();
        assertThat(body.get("data").get("status").asText()).isEqualTo("APPROVED");
        assertThat(body.get("data").get("auditComment").asText()).isEqualTo("数据确认无误");

        var row = jdbc.queryForMap(
                "SELECT status, audit_comment, audited_at, auditor_id FROM qc_audit_record WHERE id = ?",
                rowId);
        assertThat(row.get("STATUS")).isEqualTo("APPROVED");
        assertThat(row.get("AUDIT_COMMENT")).isEqualTo("数据确认无误");
        assertThat(row.get("AUDITED_AT")).isNotNull();
        assertThat(row.get("AUDITOR_ID")).isEqualTo(userId("admin"));
    }

    @Test
    void researcherRejectsAuditRow() throws Exception {
        MockHttpSession researcher = login("researcher");
        Long rowId = seedPendingAuditRow();

        JsonNode body = bodyOf(mockMvc.perform(post("/api/qc/" + rowId + "/audit")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(auditRequest("REJECTED", "MMSE 录入错误，需复核"))
                        .session(researcher))
                .andExpect(status().isOk())
                .andReturn());

        assertThat(body.get("data").get("status").asText()).isEqualTo("REJECTED");

        var row = jdbc.queryForMap(
                "SELECT status, auditor_id, audited_at FROM qc_audit_record WHERE id = ?", rowId);
        assertThat(row.get("STATUS")).isEqualTo("REJECTED");
        assertThat(row.get("AUDITED_AT")).isNotNull();
        assertThat(row.get("AUDITOR_ID"))
                .as("审核人必须是提交决策的 researcher，而非 PENDING 行创建时的 admin")
                .isEqualTo(userId("researcher"));
    }

    @Test
    void cannotTwiceSubmitSameRow() throws Exception {
        MockHttpSession admin = login("admin");
        Long rowId = seedPendingAuditRow();

        mockMvc.perform(post("/api/qc/" + rowId + "/audit")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(auditRequest("APPROVED", "第一次"))
                        .session(admin))
                .andExpect(status().isOk());

        JsonNode body = bodyOf(mockMvc.perform(post("/api/qc/" + rowId + "/audit")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(auditRequest("REJECTED", "想反悔"))
                        .session(admin))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
        assertThat(body.get("message").asText()).contains("已完成审核");

        String status = jdbc.queryForObject(
                "SELECT status FROM qc_audit_record WHERE id = ?", String.class, rowId);
        assertThat(status).isEqualTo("APPROVED");
    }

    @Test
    void submitOnNonExistentRowIsValidationError() throws Exception {
        MockHttpSession admin = login("admin");

        JsonNode body = bodyOf(mockMvc.perform(post("/api/qc/999999/audit")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(auditRequest("APPROVED", "不存在"))
                        .session(admin))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
        assertThat(body.get("message").asText()).contains("质控记录不存在");
    }

    @Test
    void submitWithInvalidStatusStringIsRejected() throws Exception {
        MockHttpSession admin = login("admin");
        Long rowId = seedPendingAuditRow();

        JsonNode body = bodyOf(mockMvc.perform(post("/api/qc/" + rowId + "/audit")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(auditRequest("PENDING", "想改回待审核"))
                        .session(admin))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
    }

    @Test
    void submitMissingAuditCommentIsRejected() throws Exception {
        MockHttpSession admin = login("admin");
        Long rowId = seedPendingAuditRow();

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("status", "APPROVED");

        JsonNode body = bodyOf(mockMvc.perform(post("/api/qc/" + rowId + "/audit")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(payload))
                        .session(admin))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
    }

    @Test
    void anonymousIsRefusedForSubmit() throws Exception {
        Long rowId = seedPendingAuditRow();

        JsonNode body = bodyOf(mockMvc.perform(post("/api/qc/" + rowId + "/audit")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(auditRequest("APPROVED", "匿名")))
                .andExpect(status().isUnauthorized())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("UNAUTHENTICATED");
    }

    // ===================================================================
    // Helpers
    // ===================================================================

    private MockHttpSession login(String username) throws Exception {
        MvcResult result = mockMvc.perform(post("/api/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(
                                Map.of("username", username, "password", DEMO_PASSWORD))))
                .andExpect(status().isOk())
                .andReturn();
        MockHttpSession session = (MockHttpSession) result.getRequest().getSession(false);
        assertThat(session).as("login %s must establish a session", username).isNotNull();
        return session;
    }

    private Subject seedSubject(String subjectCode) {
        return subjectRepository.save(new Subject(subjectCode, "种子档案-" + subjectCode,
                Status.ACTIVE, "demo-qc-" + subjectCode, Instant.now()));
    }

    private Long userId(String username) {
        return jdbc.queryForObject(
                "SELECT id FROM sys_user WHERE username = ?", Long.class, username);
    }

    private Long seedPendingAuditRow() {
        Subject subject = seedSubject("QC-SEED");
        Long adminId = userId("admin");
        Instant now = Instant.now();

        jdbc.update(
                "INSERT INTO qc_audit_record (subject_id, target_type, source_type, status, "
                        + "auditor_id, abnormal_items, created_at, updated_at) "
                        + "VALUES (?, 'VISIT', 'MANUAL_REVIEW', 'PENDING', ?, '[\"MMSE 超出范围\"]', ?, ?)",
                subject.getId(), adminId, now, now);

        return jdbc.queryForObject(
                "SELECT id FROM qc_audit_record ORDER BY id DESC LIMIT 1", Long.class);
    }

    private String auditRequest(String status, String comment) throws Exception {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", status);
        body.put("auditComment", comment);
        return objectMapper.writeValueAsString(body);
    }

    private JsonNode bodyOf(MvcResult result) throws Exception {
        return objectMapper.readTree(
                result.getResponse().getContentAsString(StandardCharsets.UTF_8));
    }
}