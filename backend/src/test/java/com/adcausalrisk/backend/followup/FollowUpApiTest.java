package com.adcausalrisk.backend.followup;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

import com.adcausalrisk.backend.subject.SubjectRepository;
import com.adcausalrisk.backend.subject.entity.Subject;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
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

/**
 * Follow-up state machine and its object-level authorization.
 *
 * <p>Deliberately <b>not</b> {@code @Transactional}: {@code FollowUpService} writes in its own
 * {@code REQUIRES_NEW} transaction, so a test transaction could neither see the committed rows nor
 * roll them back. Fixtures are committed up front and removed in {@link #cleanUp()}.
 *
 * <p>Roles come from real {@code POST /api/auth/login} sessions, so {@code SubjectAccessPolicy}
 * runs for real: a doctor without a {@code subject_permission} row gets 403, an administrator
 * (full visibility) gets through.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class FollowUpApiTest {

    private static final String DEMO_PASSWORD = "DemoPass!2026";
    private static final String SUBJECT_CODE = "DEMO-FU-API";

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private SubjectRepository subjectRepository;

    @Autowired
    private JdbcTemplate jdbc;

    private Long subjectId;

    @BeforeEach
    void seedSubject() {
        Subject subject = subjectRepository.save(new Subject(
                SUBJECT_CODE + "-" + UUID.randomUUID().toString().substring(0, 8),
                "随访接口测试档案",
                Subject.Status.ACTIVE,
                "demo-followup-api",
                Instant.now()));
        subjectId = subject.getId();
    }

    @AfterEach
    void cleanUp() {
        if (subjectId != null) {
            jdbc.update("DELETE FROM follow_up_plan WHERE subject_id = ?", subjectId);
            jdbc.update("DELETE FROM subject WHERE id = ?", subjectId);
        }
    }

    /** Scenario 1: a created plan starts in PLANNED, and that is what the database holds. */
    @Test
    void createdFollowUpIsPersistedAsPlanned() throws Exception {
        MockHttpSession admin = login("admin");

        JsonNode body = bodyOf(mockMvc.perform(post("/api/follow-ups")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(createJson("M12 复诊，复查量表与影像"))
                        .session(admin))
                .andExpect(status().isOk())
                .andReturn());

        assertThat(body.get("code").asInt()).isZero();
        assertThat(body.get("data").get("subjectId").asLong()).isEqualTo(subjectId);
        assertThat(body.get("data").get("status").asText()).isEqualTo("PLANNED");
        long followUpId = body.get("data").get("id").asLong();

        assertThat(dbStatus(followUpId)).isEqualTo("PLANNED");
    }

    /** Scenario 2: PLANNED -> COMPLETED is committed, not just returned. */
    @Test
    void patchingToCompletedUpdatesTheRow() throws Exception {
        MockHttpSession admin = login("admin");
        long followUpId = createFollowUp(admin);

        JsonNode body = bodyOf(mockMvc.perform(patch("/api/follow-ups/" + followUpId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(statusJson("COMPLETED"))
                        .session(admin))
                .andExpect(status().isOk())
                .andReturn());

        assertThat(body.get("data").get("status").asText()).isEqualTo("COMPLETED");
        assertThat(dbStatus(followUpId)).isEqualTo("COMPLETED");
    }

    /** Scenario 3: the same row can then be cancelled; the database follows each transition. */
    @Test
    void patchingToCancelledUpdatesTheRow() throws Exception {
        MockHttpSession admin = login("admin");
        long followUpId = createFollowUp(admin);

        mockMvc.perform(patch("/api/follow-ups/" + followUpId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(statusJson("COMPLETED"))
                        .session(admin))
                .andExpect(status().isOk());

        JsonNode body = bodyOf(mockMvc.perform(patch("/api/follow-ups/" + followUpId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(statusJson("CANCELLED"))
                        .session(admin))
                .andExpect(status().isOk())
                .andReturn());

        assertThat(body.get("data").get("status").asText()).isEqualTo("CANCELLED");
        assertThat(dbStatus(followUpId)).isEqualTo("CANCELLED");
    }

    /** A cancelled plan is terminal: it cannot be revived. */
    @Test
    void cancelledFollowUpCannotBeCompleted() throws Exception {
        MockHttpSession admin = login("admin");
        long followUpId = createFollowUp(admin);

        mockMvc.perform(patch("/api/follow-ups/" + followUpId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(statusJson("CANCELLED"))
                        .session(admin))
                .andExpect(status().isOk());

        JsonNode body = bodyOf(mockMvc.perform(patch("/api/follow-ups/" + followUpId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(statusJson("COMPLETED"))
                        .session(admin))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
        assertThat(body.get("message").asText()).contains("已取消的随访不可再变更");
        assertThat(dbStatus(followUpId)).as("a refused transition must not change the row")
                .isEqualTo("CANCELLED");
    }

    /** COMPLETED cannot fall back to PLANNED. */
    @Test
    void completedFollowUpCannotReturnToPlanned() throws Exception {
        MockHttpSession admin = login("admin");
        long followUpId = createFollowUp(admin);

        mockMvc.perform(patch("/api/follow-ups/" + followUpId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(statusJson("COMPLETED"))
                        .session(admin))
                .andExpect(status().isOk());

        JsonNode body = bodyOf(mockMvc.perform(patch("/api/follow-ups/" + followUpId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(statusJson("PLANNED"))
                        .session(admin))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
        assertThat(body.get("message").asText()).contains("不可退回未执行状态");
        assertThat(dbStatus(followUpId)).as("a refused transition must not change the row")
                .isEqualTo("COMPLETED");
    }

    /** Scenario 4: a value outside the CHECK constraint is refused before it reaches the column. */
    @Test
    void patchingWithAnUnknownStatusIsRejected() throws Exception {
        MockHttpSession admin = login("admin");
        long followUpId = createFollowUp(admin);

        JsonNode body = bodyOf(mockMvc.perform(patch("/api/follow-ups/" + followUpId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(statusJson("INVALID"))
                        .session(admin))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
        assertThat(body.get("message").asText()).contains("PLANNED / COMPLETED / CANCELLED");
        assertThat(dbStatus(followUpId)).as("a refused patch must not change the row").isEqualTo("PLANNED");
    }

    /**
     * Scenario 5: an unknown follow-up id is a 400, not a 404.
     *
     * <p>The frozen contract declares only 200/400/401/403 for
     * {@code PATCH /api/follow-ups/{followUpId}} and has no 404 anywhere in this module, so
     * "not found" is reported as a validation failure exactly like the other modules
     * ({@code 导入任务不存在} / {@code 评估任务不存在} are both 400 for the same reason).
     */
    @Test
    void patchingAnUnknownFollowUpIsAValidationError() throws Exception {
        MockHttpSession admin = login("admin");

        JsonNode body = bodyOf(mockMvc.perform(patch("/api/follow-ups/999999999")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(statusJson("COMPLETED"))
                        .session(admin))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
        assertThat(body.get("message").asText()).contains("随访计划不存在");
    }

    /** Scenario 6: without a grant on the subject, every follow-up operation is refused. */
    @Test
    void doctorWithoutSubjectGrantIsRefused() throws Exception {
        MockHttpSession admin = login("admin");
        long followUpId = createFollowUp(admin);
        MockHttpSession doctor = login("doctor");

        JsonNode createRefused = bodyOf(mockMvc.perform(post("/api/follow-ups")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(createJson("医生尝试创建"))
                        .session(doctor))
                .andExpect(status().isForbidden())
                .andReturn());
        assertThat(createRefused.get("errorCode").asText()).isEqualTo("ACCESS_DENIED");

        JsonNode patchRefused = bodyOf(mockMvc.perform(patch("/api/follow-ups/" + followUpId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(statusJson("COMPLETED"))
                        .session(doctor))
                .andExpect(status().isForbidden())
                .andReturn());
        assertThat(patchRefused.get("errorCode").asText()).isEqualTo("ACCESS_DENIED");

        JsonNode listRefused = bodyOf(mockMvc.perform(
                        get("/api/subjects/" + subjectId + "/follow-ups").session(doctor))
                .andExpect(status().isForbidden())
                .andReturn());
        assertThat(listRefused.get("errorCode").asText()).isEqualTo("ACCESS_DENIED");

        assertThat(dbStatus(followUpId)).as("no refused call may touch the row").isEqualTo("PLANNED");
    }

    // ------------------------------------------------------------------
    // helpers
    // ------------------------------------------------------------------

    private long createFollowUp(MockHttpSession session) throws Exception {
        JsonNode body = bodyOf(mockMvc.perform(post("/api/follow-ups")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(createJson("M12 复诊"))
                        .session(session))
                .andExpect(status().isOk())
                .andReturn());
        return body.get("data").get("id").asLong();
    }

    private String dbStatus(long followUpId) {
        return jdbc.queryForObject(
                "SELECT status FROM follow_up_plan WHERE id = ?", String.class, followUpId);
    }

    private String createJson(String purpose) throws Exception {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("subjectId", subjectId);
        body.put("scheduledAt", Instant.now().plus(30, ChronoUnit.DAYS).toString());
        body.put("purpose", purpose);
        return objectMapper.writeValueAsString(body);
    }

    private String statusJson(String status) throws Exception {
        return objectMapper.writeValueAsString(Map.of("status", status));
    }

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

    private JsonNode bodyOf(MvcResult result) throws Exception {
        return objectMapper.readTree(result.getResponse().getContentAsString(StandardCharsets.UTF_8));
    }
}
