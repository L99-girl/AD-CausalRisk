package com.adcausalrisk.backend.contract;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

import com.adcausalrisk.backend.subject.SubjectRepository;
import com.adcausalrisk.backend.subject.entity.Subject;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

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
import org.springframework.transaction.annotation.Transactional;

/**
 * The last three contract operations: {@code PATCH /api/subjects/{subjectId}},
 * {@code POST /api/subjects/{subjectId}/features} and
 * {@code POST /api/subjects/{subjectId}/quality-checks}.
 *
 * <p>{@code @Transactional} is correct here (unlike the assessment tests): none of these paths use
 * {@code REQUIRES_NEW}, so every write joins the test transaction and rolls back.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
@Transactional
class RemainingEndpointsApiTest {

    private static final String DEMO_PASSWORD = "DemoPass!2026";
    private static final String PATCH_PATH = "/api/subjects/{subjectId}";
    private static final String FEATURES_PATH = "/api/subjects/{subjectId}/features";
    private static final String QUALITY_PATH = "/api/subjects/{subjectId}/quality-checks";

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private SubjectRepository subjectRepository;

    @Autowired
    private JdbcTemplate jdbc;

    private Subject subject;

    @BeforeEach
    void seedSubject() {
        subject = subjectRepository.save(new Subject(
                "DEMO-CONTRACT-" + UUID.randomUUID().toString().substring(0, 8),
                "原始别名",
                Subject.Status.ACTIVE,
                "demo-contract-api",
                Instant.now()));
    }

    // ------------------------------------------------------------------
    // PATCH /api/subjects/{subjectId}
    // ------------------------------------------------------------------

    @Test
    void patchUpdatesAliasAndStatus() throws Exception {
        JsonNode body = bodyOf(mockMvc.perform(patch("/api/subjects/" + subject.getId())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(patchJson(subject.getSubjectCode(), "  新别名  ", "ARCHIVED"))
                        .session(login("admin")))
                .andExpect(status().isOk())
                .andReturn());

        assertThat(body.get("code").asInt()).isZero();
        assertThat(body.get("data").get("alias").asText()).isEqualTo("新别名");
        assertThat(body.get("data").get("status").asText()).isEqualTo("ARCHIVED");
        assertThat(ContractSchemas.validateResponse(body, PATCH_PATH, "patch", 200)).isEmpty();

        String storedAlias = jdbc.queryForObject(
                "SELECT alias FROM subject WHERE id = ?", String.class, subject.getId());
        assertThat(storedAlias).isEqualTo("新别名");
    }

    @Test
    void patchRejectsSubjectCodeChange() throws Exception {
        JsonNode body = bodyOf(mockMvc.perform(patch("/api/subjects/" + subject.getId())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(patchJson("DEMO-RENAMED", "别名", null))
                        .session(login("admin")))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
        assertThat(body.get("message").asText()).contains("subjectCode 不可修改");
    }

    @Test
    void patchByDoctorWithoutManageIsForbidden() throws Exception {
        JsonNode body = bodyOf(mockMvc.perform(patch("/api/subjects/" + subject.getId())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(patchJson(subject.getSubjectCode(), "医生改名", null))
                        .session(login("doctor")))
                .andExpect(status().isForbidden())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("ACCESS_DENIED");
        assertThat(jdbc.queryForObject(
                "SELECT alias FROM subject WHERE id = ?", String.class, subject.getId()))
                .as("a refused patch must not change the row")
                .isEqualTo("原始别名");
    }

    // ------------------------------------------------------------------
    // POST /api/subjects/{subjectId}/features
    // ------------------------------------------------------------------

    @Test
    void featureIsInsertedAndReturned() throws Exception {
        JsonNode body = bodyOf(mockMvc.perform(post("/api/subjects/" + subject.getId() + "/features")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(featureJson("APOE_E4_COUNT", 1, "count", "2025-01-01"))
                        .session(login("admin")))
                .andExpect(status().isOk())
                .andReturn());

        assertThat(body.get("code").asInt()).isZero();
        assertThat(body.get("data").get("id").asLong()).isPositive();
        assertThat(body.get("data").get("featureName").asText()).isEqualTo("APOE_E4_COUNT");
        assertThat(body.get("data").get("unit").asText()).isEqualTo("count");
        assertThat(ContractSchemas.validateResponse(body, FEATURES_PATH, "post", 200)).isEmpty();

        Integer rows = jdbc.queryForObject(
                "SELECT COUNT(*) FROM subject_feature WHERE subject_id = ? AND feature_name = ?",
                Integer.class, subject.getId(), "APOE_E4_COUNT");
        assertThat(rows).isEqualTo(1);
    }

    @Test
    void featureWithWrongUnitForApoeIsRejected() throws Exception {
        JsonNode body = bodyOf(mockMvc.perform(post("/api/subjects/" + subject.getId() + "/features")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(featureJson("APOE_E4_COUNT", 1, "normalized", "2025-01-01"))
                        .session(login("admin")))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
        assertThat(body.get("message").asText()).contains("unit 必须是 count");
    }

    @Test
    void featureByDoctorIsForbidden() throws Exception {
        JsonNode body = bodyOf(mockMvc.perform(post("/api/subjects/" + subject.getId() + "/features")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(featureJson("MRI_HIPPOCAMPUS_L", 0.35, "normalized", "2025-01-01"))
                        .session(login("doctor")))
                .andExpect(status().isForbidden())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("ACCESS_DENIED");
        assertThat(jdbc.queryForObject(
                "SELECT COUNT(*) FROM subject_feature WHERE subject_id = ?", Integer.class, subject.getId()))
                .isZero();
    }

    // ------------------------------------------------------------------
    // POST /api/subjects/{subjectId}/quality-checks
    // ------------------------------------------------------------------

    @Test
    void qualityCheckReportsBlockedWithoutVisits() throws Exception {
        JsonNode body = bodyOf(mockMvc.perform(post("/api/subjects/" + subject.getId() + "/quality-checks")
                        .session(login("admin")))
                .andExpect(status().isOk())
                .andReturn());

        assertThat(body.get("data").get("subjectId").asLong()).isEqualTo(subject.getId());
        assertThat(body.get("data").get("qualityStatus").asText()).isEqualTo("BLOCKED");
        assertThat(body.get("data").get("issues")).isNotEmpty();
        assertThat(body.get("data").get("ruleVersion").asText()).isNotBlank();
        assertThat(ContractSchemas.validateResponse(body, QUALITY_PATH, "post", 200)).isEmpty();
    }

    @Test
    void qualityCheckByDoctorIsForbidden() throws Exception {
        JsonNode body = bodyOf(mockMvc.perform(post("/api/subjects/" + subject.getId() + "/quality-checks")
                        .session(login("doctor")))
                .andExpect(status().isForbidden())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("ACCESS_DENIED");
    }

    // ------------------------------------------------------------------
    // helpers
    // ------------------------------------------------------------------

    private String patchJson(String subjectCode, String alias, String status) throws Exception {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("subjectCode", subjectCode);
        body.put("alias", alias);
        if (status != null) {
            body.put("status", status);
        }
        return objectMapper.writeValueAsString(body);
    }

    private String featureJson(String name, Object value, String unit, String recordedAt) throws Exception {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("featureName", name);
        if (value != null) {
            body.put("featureValue", value);
        }
        body.put("recordedAt", recordedAt);
        body.put("unit", unit);
        return objectMapper.writeValueAsString(body);
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
