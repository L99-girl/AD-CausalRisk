package com.adcausalrisk.backend.importjob;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Map;

import com.adcausalrisk.backend.contract.ContractSchemas;
import com.adcausalrisk.backend.importjob.entity.DataImportJob;
import com.adcausalrisk.backend.subject.SubjectRepository;
import com.adcausalrisk.backend.subject.entity.Subject;
import com.adcausalrisk.backend.visit.VisitRepository;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.security.test.context.support.WithAnonymousUser;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.request.MockMultipartHttpServletRequestBuilder;
import org.springframework.transaction.annotation.Transactional;

/**
 * End-to-end tests for the three import endpoints.
 *
 * <p>Runs against the real Spring context, the real security filter chain and H2 in MySQL mode,
 * with authentication established exactly the way the browser does it ({@code POST
 * /api/auth/login} then reuse the session). Every response is validated against the frozen
 * contract.
 *
 * <p>Covers the parts of the multipart endpoint that are easy to get wrong: the required
 * {@code Idempotency-Key} header, the required {@code file} part, the pinned content type, an
 * oversized upload, and the preview/commit state machine including a replayed idempotency key.
 *
 * <p>Not covered here: the {@code spring.servlet.multipart.max-file-size} limit itself. MockMvc
 * builds the multipart request itself, so the servlet container's size check never runs; the
 * 30000-byte importer cap is asserted instead.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
@Transactional
class ImportJobApiTest {

    private static final String DEMO_PASSWORD = "DemoPass!2026";

    private static final String IMPORT_PATH = "/api/import-jobs";

    private static final String JOB_PATH = "/api/import-jobs/{jobId}";

    private static final String COMMIT_PATH = "/api/import-jobs/{jobId}/commit";

    private static final String SUBJECT_HEADER = "subjectCode,alias,status\n";

    private static final String VISIT_HEADER = "subjectCode,visitCode,visitDate,mmse,moca,cdrSb\n";

    private static final String FEATURE_HEADER =
            "subjectCode,featureName,featureValue,recordedAt,unit\n";

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private SubjectRepository subjectRepository;

    @Autowired
    private VisitRepository visitRepository;

    @Autowired
    private DataImportJobRepository importJobRepository;

    @Autowired
    private JdbcTemplate jdbc;

    // ===================================================================
    // 1. Preview
    // ===================================================================

    @Test
    void adminPreviewsSubjectsCsv() throws Exception {
        MockHttpSession admin = login("admin");

        JsonNode body = bodyOf(mockMvc.perform(
                        previewRequest("key-subjects", SUBJECT_HEADER
                                + "DEMO-700,合成甲,ACTIVE\n"
                                + "DEMO-701,合成乙,ACTIVE\n").session(admin))
                .andExpect(status().isOk())
                .andReturn());

        assertThat(body.get("code").asInt()).isZero();
        JsonNode data = body.get("data");
        assertThat(data.get("jobId").asLong()).isPositive();
        assertThat(data.get("status").asText()).isEqualTo("PREVIEW_READY");
        assertThat(data.get("dataVersion").asText()).startsWith("demo-");
        assertThat(data.get("totalRows").asInt()).isEqualTo(2);
        assertThat(data.get("validRows").asInt()).isEqualTo(2);
        assertThat(data.get("invalidRows").asInt()).isZero();
        assertThat(data.get("errors").isArray()).isTrue();
        assertThat(data.get("errors").size()).isZero();
        assertThat(ContractSchemas.validateResponse(body, IMPORT_PATH, "post", 200)).isEmpty();
    }

    @Test
    void previewWithoutIdempotencyKeyIsRejectedAsValidationError() throws Exception {
        MockHttpSession admin = login("admin");
        MockMultipartHttpServletRequestBuilder request = multipart(IMPORT_PATH);
        request.file(csvFile(SUBJECT_HEADER + "DEMO-702,甲,ACTIVE\n"));

        JsonNode body = bodyOf(mockMvc.perform(request.session(admin))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
        assertThat(body.get("message").asText()).contains("Idempotency-Key");
    }

    @Test
    void previewWithoutFilePartIsRejectedAsValidationError() throws Exception {
        MockHttpSession admin = login("admin");
        MockMultipartHttpServletRequestBuilder request = multipart(IMPORT_PATH);
        request.header("Idempotency-Key", "key-no-file");

        JsonNode body = bodyOf(mockMvc.perform(request.session(admin))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
        assertThat(body.get("message").asText()).contains("file");
    }

    @Test
    void previewWithJsonContentTypeIsRejectedAsUnsupportedMediaType() throws Exception {
        MockHttpSession admin = login("admin");

        mockMvc.perform(post(IMPORT_PATH)
                        .header("Idempotency-Key", "key-json")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}")
                        .session(admin))
                .andExpect(status().isUnsupportedMediaType());
    }

    @Test
    void oversizedUploadIsRejectedAsValidationError() throws Exception {
        MockHttpSession admin = login("admin");
        String oversized = SUBJECT_HEADER + "DEMO-703," + "a".repeat(30_000) + ",ACTIVE\n";

        JsonNode body = bodyOf(mockMvc.perform(
                        previewRequest("key-big", oversized).session(admin))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
    }

    @Test
    void unrecognisedHeaderIsRejectedAsValidationError() throws Exception {
        MockHttpSession admin = login("admin");

        JsonNode body = bodyOf(mockMvc.perform(
                        previewRequest("key-bad-header", "alias,subjectCode,status\n甲,DEMO-704,ACTIVE\n")
                                .session(admin))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
    }

    @Test
    void headerWithoutDataRowsIsRejected() throws Exception {
        MockHttpSession admin = login("admin");

        JsonNode body = bodyOf(mockMvc.perform(
                        previewRequest("key-header-only", SUBJECT_HEADER).session(admin))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
        assertThat(body.get("message").asText()).contains("只有表头");
        assertThat(importJobRepository.count()).isZero();
    }

    @Test
    void idempotencyKeyLongerThanTheContractLimitIsRejected() throws Exception {
        MockHttpSession admin = login("admin");

        JsonNode body = bodyOf(mockMvc.perform(
                        previewRequest("k".repeat(101), SUBJECT_HEADER + "DEMO-708,甲,ACTIVE\n")
                                .session(admin))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
        assertThat(body.get("message").asText()).contains("Idempotency-Key");
        assertThat(importJobRepository.count()).isZero();
    }

    @Test
    void blankIdempotencyKeyIsRejected() throws Exception {
        MockHttpSession admin = login("admin");

        JsonNode body = bodyOf(mockMvc.perform(
                        previewRequest("", SUBJECT_HEADER + "DEMO-709,甲,ACTIVE\n").session(admin))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
        assertThat(importJobRepository.count()).isZero();
    }

    // ===================================================================
    // 2. Idempotency
    // ===================================================================

    @Test
    void sameKeyAndSameFileReplaysTheSameJob() throws Exception {
        MockHttpSession admin = login("admin");
        String csv = SUBJECT_HEADER + "DEMO-705,甲,ACTIVE\n";

        JsonNode first = bodyOf(mockMvc.perform(previewRequest("key-replay", csv).session(admin))
                .andExpect(status().isOk())
                .andReturn());
        JsonNode second = bodyOf(mockMvc.perform(previewRequest("key-replay", csv).session(admin))
                .andExpect(status().isOk())
                .andReturn());

        assertThat(second.get("data").get("jobId").asLong())
                .isEqualTo(first.get("data").get("jobId").asLong());
        assertThat(importJobRepository.count()).isEqualTo(1);
    }

    @Test
    void sameKeyWithDifferentFileIsRejected() throws Exception {
        MockHttpSession admin = login("admin");

        mockMvc.perform(previewRequest("key-conflict",
                        SUBJECT_HEADER + "DEMO-706,甲,ACTIVE\n").session(admin))
                .andExpect(status().isOk());

        JsonNode body = bodyOf(mockMvc.perform(previewRequest("key-conflict",
                        SUBJECT_HEADER + "DEMO-707,乙,ACTIVE\n").session(admin))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
        assertThat(importJobRepository.count()).isEqualTo(1);
    }

    // ===================================================================
    // 3. Commit
    // ===================================================================

    @Test
    void commitInsertsSubjectsAndClearsTheRetainedUpload() throws Exception {
        MockHttpSession admin = login("admin");
        JsonNode preview = bodyOf(mockMvc.perform(previewRequest("key-commit-subjects",
                        SUBJECT_HEADER + "DEMO-710,甲,ACTIVE\n" + "DEMO-711,乙,ARCHIVED\n")
                        .session(admin))
                .andExpect(status().isOk())
                .andReturn());
        long jobId = preview.get("data").get("jobId").asLong();

        JsonNode committed = bodyOf(mockMvc.perform(
                        post(COMMIT_PATH, jobId).session(admin))
                .andExpect(status().isOk())
                .andReturn());

        assertThat(committed.get("data").get("status").asText()).isEqualTo("COMMITTED");
        assertThat(committed.get("data").get("validRows").asInt()).isEqualTo(2);
        assertThat(ContractSchemas.validateResponse(committed, COMMIT_PATH, "post", 200)).isEmpty();

        assertThat(subjectRepository.findBySubjectCode("DEMO-710")).isPresent();
        assertThat(subjectRepository.findBySubjectCode("DEMO-711").orElseThrow().getStatus())
                .isEqualTo(Subject.Status.ARCHIVED);

        // The uploaded text is not retained once the job is terminal.
        assertThat(importJobRepository.findById(jobId).orElseThrow().getPreviewCsv()).isNull();
    }

    @Test
    void commitInsertsVisits() throws Exception {
        MockHttpSession admin = login("admin");
        Subject subject = seedSubject("DEMO-720");
        JsonNode preview = bodyOf(mockMvc.perform(previewRequest("key-commit-visits",
                        VISIT_HEADER
                                + "DEMO-720,BL,2025-01-01,28,25,0.5\n"
                                + "DEMO-720,M6,2025-07-01,27.5,,1\n")
                        .session(admin))
                .andExpect(status().isOk())
                .andReturn());

        mockMvc.perform(post(COMMIT_PATH, preview.get("data").get("jobId").asLong()).session(admin))
                .andExpect(status().isOk());

        assertThat(visitRepository.findBySubjectIdOrderByVisitDateAscIdAsc(subject.getId()))
                .hasSize(2)
                .allSatisfy(visit -> {
                    assertThat(visit.getMmse()).isNotNull();
                    assertThat(visit.getRawMmse()).isNotNull();
                });
    }

    @Test
    void commitInsertsFeatures() throws Exception {
        MockHttpSession admin = login("admin");
        Subject subject = seedSubject("DEMO-721");
        JsonNode preview = bodyOf(mockMvc.perform(previewRequest("key-commit-features",
                        FEATURE_HEADER
                                + "DEMO-721,APOE_E4_COUNT,1,2025-01-01,count\n"
                                + "DEMO-721,MRI_HIPPOCAMPUS_L,0.5,2025-01-01,normalized\n")
                        .session(admin))
                .andExpect(status().isOk())
                .andReturn());

        mockMvc.perform(post(COMMIT_PATH, preview.get("data").get("jobId").asLong()).session(admin))
                .andExpect(status().isOk());

        Integer stored = jdbc.queryForObject(
                "SELECT COUNT(*) FROM subject_feature WHERE subject_id = ?", Integer.class,
                subject.getId());
        assertThat(stored).isEqualTo(2);
    }

    /**
     * A missing feature value must reach the database as SQL NULL. Empty cells are valid input,
     * and the JDBC batch insert has to bind a null parameter rather than fail on it.
     */
    @Test
    void commitInsertsFeatureWithMissingValueAsNull() throws Exception {
        MockHttpSession admin = login("admin");
        Subject subject = seedSubject("DEMO-722");
        JsonNode preview = bodyOf(mockMvc.perform(previewRequest("key-feature-null",
                        FEATURE_HEADER
                                + "DEMO-722,APOE_E4_COUNT,,2025-01-01,count\n"
                                + "DEMO-722,MRI_HIPPOCAMPUS_L,0.5,2025-01-01,normalized\n")
                        .session(admin))
                .andExpect(status().isOk())
                .andReturn());
        assertThat(preview.get("data").get("validRows").asInt()).isEqualTo(2);
        assertThat(preview.get("data").get("invalidRows").asInt()).isZero();

        mockMvc.perform(post(COMMIT_PATH, preview.get("data").get("jobId").asLong()).session(admin))
                .andExpect(status().isOk());

        Integer missing = jdbc.queryForObject(
                "SELECT COUNT(*) FROM subject_feature WHERE subject_id = ? AND feature_value IS NULL",
                Integer.class, subject.getId());
        assertThat(missing).as("the empty featureValue is stored as NULL, not 0").isEqualTo(1);
    }

    @Test
    void invalidRowsAreCountedReportedAndNeverInserted() throws Exception {
        MockHttpSession admin = login("admin");
        JsonNode preview = bodyOf(mockMvc.perform(previewRequest("key-partial",
                        SUBJECT_HEADER
                                + "DEMO-730,甲,ACTIVE\n"
                                + "DEMO-731,乙,DELETED\n")
                        .session(admin))
                .andExpect(status().isOk())
                .andReturn());

        assertThat(preview.get("data").get("validRows").asInt()).isEqualTo(1);
        assertThat(preview.get("data").get("invalidRows").asInt()).isEqualTo(1);
        assertThat(preview.get("data").get("errors").size()).isEqualTo(1);

        mockMvc.perform(post(COMMIT_PATH, preview.get("data").get("jobId").asLong()).session(admin))
                .andExpect(status().isOk());

        assertThat(subjectRepository.findBySubjectCode("DEMO-730")).isPresent();
        assertThat(subjectRepository.findBySubjectCode("DEMO-731")).isEmpty();
    }

    @Test
    void commitTwiceIsRejected() throws Exception {
        MockHttpSession admin = login("admin");
        JsonNode preview = bodyOf(mockMvc.perform(previewRequest("key-twice",
                        SUBJECT_HEADER + "DEMO-740,甲,ACTIVE\n").session(admin))
                .andExpect(status().isOk())
                .andReturn());
        long jobId = preview.get("data").get("jobId").asLong();

        mockMvc.perform(post(COMMIT_PATH, jobId).session(admin)).andExpect(status().isOk());

        JsonNode second = bodyOf(mockMvc.perform(post(COMMIT_PATH, jobId).session(admin))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(second.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
        assertThat(subjectRepository.findBySubjectCode("DEMO-740")).isPresent();
    }

    @Test
    void commitOnBlockedJobIsRejected() throws Exception {
        MockHttpSession admin = login("admin");
        JsonNode preview = bodyOf(mockMvc.perform(previewRequest("key-blocked",
                        SUBJECT_HEADER + "DEMO-750,甲,DELETED\n").session(admin))
                .andExpect(status().isOk())
                .andReturn());

        assertThat(preview.get("data").get("status").asText()).isEqualTo("BLOCKED");
        assertThat(preview.get("data").get("validRows").asInt()).isZero();

        // A job that can never be committed must not retain the uploaded text.
        assertThat(importJobRepository.findById(preview.get("data").get("jobId").asLong())
                .orElseThrow().getPreviewCsv()).isNull();

        mockMvc.perform(post(COMMIT_PATH, preview.get("data").get("jobId").asLong()).session(admin))
                .andExpect(status().isBadRequest());
    }

    @Test
    void commitRefusesWhenTheDataChangedAfterPreview() throws Exception {
        MockHttpSession admin = login("admin");
        JsonNode preview = bodyOf(mockMvc.perform(previewRequest("key-changed",
                        SUBJECT_HEADER + "DEMO-760,甲,ACTIVE\n" + "DEMO-761,乙,ACTIVE\n")
                        .session(admin))
                .andExpect(status().isOk())
                .andReturn());
        assertThat(preview.get("data").get("validRows").asInt()).isEqualTo(2);

        // One of the codes appears between preview and commit, so the re-parse accepts fewer rows.
        seedSubject("DEMO-760");

        JsonNode body = bodyOf(mockMvc.perform(
                        post(COMMIT_PATH, preview.get("data").get("jobId").asLong()).session(admin))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
        assertThat(subjectRepository.findBySubjectCode("DEMO-761")).isEmpty();
    }

    /**
     * The case a row count cannot see: one valid row leaves the set while a rejected one joins
     * it, so {@code validRows} stays 1 but the row to insert is a different one. Without the
     * digest this commit would insert DEMO-762, which the caller never saw as valid.
     */
    @Test
    void commitRefusesWhenOneValidRowWasReplacedByAnother() throws Exception {
        MockHttpSession admin = login("admin");
        Subject existing = seedSubject("DEMO-762");

        // DEMO-762 already exists (invalid), DEMO-763 is new (valid) -> validRows = 1.
        JsonNode preview = bodyOf(mockMvc.perform(previewRequest("key-swapped",
                        SUBJECT_HEADER + "DEMO-762,旧,ACTIVE\n" + "DEMO-763,新,ACTIVE\n")
                        .session(admin))
                .andExpect(status().isOk())
                .andReturn());
        assertThat(preview.get("data").get("validRows").asInt()).isEqualTo(1);

        // Swap the roles of the two rows behind the preview's back: the count still matches.
        subjectRepository.delete(existing);
        seedSubject("DEMO-763");

        JsonNode body = bodyOf(mockMvc.perform(
                        post(COMMIT_PATH, preview.get("data").get("jobId").asLong()).session(admin))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
        assertThat(body.get("message").asText()).contains("已变化");
        assertThat(subjectRepository.findBySubjectCode("DEMO-762"))
                .as("the row the caller never approved must not be inserted")
                .isEmpty();
    }

    /** Jobs created before V6 carry no digest; the count check still guards them. */
    @Test
    void commitFallsBackToTheCountCheckWhenTheJobHasNoDigest() throws Exception {
        MockHttpSession admin = login("admin");
        JsonNode preview = bodyOf(mockMvc.perform(previewRequest("key-legacy",
                        SUBJECT_HEADER + "DEMO-764,甲,ACTIVE\n").session(admin))
                .andExpect(status().isOk())
                .andReturn());
        long jobId = preview.get("data").get("jobId").asLong();
        jdbc.update("UPDATE data_import_job SET preview_digest = NULL WHERE id = ?", jobId);

        mockMvc.perform(post(COMMIT_PATH, jobId).session(admin)).andExpect(status().isOk());

        assertThat(subjectRepository.findBySubjectCode("DEMO-764")).isPresent();
    }

    @Test
    void errorsAreCappedWhileTheCountsStayExact() throws Exception {
        MockHttpSession admin = login("admin");
        StringBuilder csv = new StringBuilder(VISIT_HEADER);
        for (int i = 0; i < 250; i++) {
            // Every row points at a subject that does not exist, so all 250 are invalid.
            csv.append("DEMO-999,V").append(i).append(",2025-01-01,28,25,0.5\n");
        }

        JsonNode preview = bodyOf(mockMvc.perform(previewRequest("key-many-errors", csv.toString())
                        .session(admin))
                .andExpect(status().isOk())
                .andReturn());

        assertThat(preview.get("data").get("invalidRows").asInt()).isEqualTo(250);
        assertThat(preview.get("data").get("validRows").asInt()).isZero();
        assertThat(preview.get("data").get("errors").size()).isEqualTo(200);
        assertThat(ContractSchemas.validateResponse(preview, IMPORT_PATH, "post", 200)).isEmpty();
    }

    // ===================================================================
    // 4. Reading a job
    // ===================================================================

    @Test
    void creatorCanReadTheJob() throws Exception {
        MockHttpSession admin = login("admin");
        JsonNode preview = bodyOf(mockMvc.perform(previewRequest("key-read",
                        SUBJECT_HEADER + "DEMO-770,甲,ACTIVE\n").session(admin))
                .andExpect(status().isOk())
                .andReturn());
        long jobId = preview.get("data").get("jobId").asLong();

        JsonNode read = bodyOf(mockMvc.perform(get(JOB_PATH, jobId).session(admin))
                .andExpect(status().isOk())
                .andReturn());

        assertThat(read.get("data").get("jobId").asLong()).isEqualTo(jobId);
        assertThat(ContractSchemas.validateResponse(read, JOB_PATH, "get", 200)).isEmpty();
    }

    @Test
    void anotherNonAdminUserCannotReadSomeonesJob() throws Exception {
        MockHttpSession admin = login("admin");
        MockHttpSession researcher = login("researcher");
        JsonNode preview = bodyOf(mockMvc.perform(previewRequest("key-private",
                        SUBJECT_HEADER + "DEMO-780,甲,ACTIVE\n").session(admin))
                .andExpect(status().isOk())
                .andReturn());
        long jobId = preview.get("data").get("jobId").asLong();

        JsonNode body = bodyOf(mockMvc.perform(get(JOB_PATH, jobId).session(researcher))
                .andExpect(status().isForbidden())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("ACCESS_DENIED");
    }

    @Test
    void unknownJobIdIsReportedAsValidationError() throws Exception {
        MockHttpSession admin = login("admin");

        JsonNode body = bodyOf(mockMvc.perform(get(JOB_PATH, 999_999L).session(admin))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
    }

    // ===================================================================
    // 5. Access control
    // ===================================================================

    @Test
    void doctorCannotPreview() throws Exception {
        MockHttpSession doctor = login("doctor");

        JsonNode body = bodyOf(mockMvc.perform(previewRequest("key-doctor",
                        SUBJECT_HEADER + "DEMO-790,甲,ACTIVE\n").session(doctor))
                .andExpect(status().isForbidden())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("ACCESS_DENIED");
    }

    @Test
    void patientCannotPreview() throws Exception {
        MockHttpSession patient = login("patient");

        mockMvc.perform(previewRequest("key-patient",
                        SUBJECT_HEADER + "DEMO-791,甲,ACTIVE\n").session(patient))
                .andExpect(status().isForbidden());
    }

    @Test
    @WithAnonymousUser
    void anonymousIsRefused() throws Exception {
        JsonNode body = bodyOf(mockMvc.perform(previewRequest("key-anon",
                        SUBJECT_HEADER + "DEMO-792,甲,ACTIVE\n"))
                .andExpect(status().isUnauthorized())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("UNAUTHENTICATED");
    }

    // ===================================================================
    // Helpers
    // ===================================================================

    private MockMultipartHttpServletRequestBuilder previewRequest(String idempotencyKey, String csv) {
        MockMultipartHttpServletRequestBuilder request = multipart(IMPORT_PATH);
        request.file(csvFile(csv));
        request.header("Idempotency-Key", idempotencyKey);
        return request;
    }

    private static MockMultipartFile csvFile(String csv) {
        return new MockMultipartFile("file", "upload.csv", "text/csv",
                csv.getBytes(StandardCharsets.UTF_8));
    }

    private Subject seedSubject(String subjectCode) {
        return subjectRepository.save(new Subject(subjectCode, "种子档案-" + subjectCode,
                Subject.Status.ACTIVE, "demo-seed-" + subjectCode, Instant.now()));
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
