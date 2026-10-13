package com.adcausalrisk.backend.common;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.matchesPattern;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.adcausalrisk.backend.contract.ContractSchemas;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.http.MediaType;
import org.springframework.security.test.context.support.WithAnonymousUser;
import org.springframework.security.test.context.support.WithMockUser;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;

/**
 * Locks the response contract: every success and failure must be the six-property
 * {@link Envelope} the frozen target contract declares, with {@code code == 0} and
 * {@code errorCode == null} on success, and {@code data} present as JSON {@code null}
 * rather than omitted.
 *
 * <p>Responses are additionally validated against
 * {@code contracts/java-business.target.openapi.json} itself (see
 * {@link ContractSchemas}), not against a hand-written copy of its field list.
 *
 * <p>The stub endpoints live under {@code /api/__test/**} so that the <em>real</em>
 * {@code SecurityFilterChain} applies to them. They return contract-shaped bodies so the
 * strict per-operation success schema can be exercised: {@code /api/__test/me} returns a
 * {@code CurrentUser} payload and is validated against the real {@code GET /api/me} 200
 * schema. The anonymous 401 and the authenticated 403 below are produced by the real
 * {@code RestAuthenticationEntryPoint} and {@code RestAccessDeniedHandler}.
 */
@SpringBootTest(classes = EnvelopeContractTest.StubEndpoints.class)
@AutoConfigureMockMvc
@ActiveProfiles("test")
// Phase 3 removed the temporary security exclusion of phase 2: every request below now runs
// through the real SecurityConfig and SecurityFilterChain. The class is authenticated by
// default and the refusal cases opt out with @WithAnonymousUser.
@WithMockUser(username = "admin", roles = "ADMIN")
class EnvelopeContractTest {

    private static final List<String> ENVELOPE_PROPERTIES =
            List.of("code", "message", "data", "errorCode", "traceId", "timestamp");

    private static final String TRACE_HEADER = "X-Trace-Id";

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Test
    void successResponseHasExactlyTheSixContractProperties() throws Exception {
        JsonNode body = bodyOf(mockMvc.perform(get("/api/__test/me")).andExpect(status().isOk()).andReturn());

        assertThat(fieldNames(body)).containsExactlyElementsOf(ENVELOPE_PROPERTIES);
        assertThat(body.get("code").asInt()).isZero();
        assertThat(body.get("errorCode").isNull()).as("errorCode must be null on success").isTrue();
        assertThat(body.get("message").asText()).isEqualTo("成功");
        assertThat(body.get("data").isObject()).isTrue();
        assertThat(TraceId.isValid(body.get("traceId").asText())).isTrue();
    }

    @Test
    void successResponseMatchesTheContractSchemaDeclaredForGetApiMe() throws Exception {
        JsonNode body = bodyOf(mockMvc.perform(get("/api/__test/me")).andExpect(status().isOk()).andReturn());

        // The real GET /api/me 200 schema: code const 0, errorCode type null, data = CurrentUser,
        // all six required, additionalProperties false.
        assertThat(ContractSchemas.validateResponse(body, "/api/me", "get", 200))
                .as("response must satisfy the frozen contract for GET /api/me 200: %s", body)
                .isEmpty();
    }

    @Test
    void nullDataIsPresentInTheJsonAndNotOmitted() throws Exception {
        MvcResult result = mockMvc.perform(get("/api/__test/null-data")).andExpect(status().isOk()).andReturn();
        String json = result.getResponse().getContentAsString(StandardCharsets.UTF_8);
        JsonNode body = objectMapper.readTree(json);

        assertThat(fieldNames(body)).containsExactlyElementsOf(ENVELOPE_PROPERTIES);
        assertThat(json).as("the data key must be written, not dropped").contains("\"data\":null");
        assertThat(body.has("data")).isTrue();
        assertThat(body.get("data").isNull()).isTrue();
        assertThat(ContractSchemas.validateComponent(body, "Envelope")).isEmpty();
    }

    @Test
    void businessFailureCarriesItsErrorCodeAndTheCorrectHttpStatus() throws Exception {
        MvcResult result = mockMvc.perform(get("/api/__test/denied"))
                .andExpect(status().isForbidden())
                .andReturn();
        JsonNode body = bodyOf(result);

        assertThat(fieldNames(body)).containsExactlyElementsOf(ENVELOPE_PROPERTIES);
        assertThat(body.get("code").asInt()).isEqualTo(403);
        assertThat(body.get("errorCode").asText()).isEqualTo("ACCESS_DENIED");
        assertThat(body.get("message").asText()).isEqualTo(ErrorCode.ACCESS_DENIED.defaultMessage());
        assertThat(body.get("data").isNull()).isTrue();
        assertThat(ContractSchemas.validateComponent(body, "Envelope")).isEmpty();
        assertThat(ContractSchemas.validateResponse(body, "/api/auth/logout", "post", 403)).isEmpty();
    }

    @Test
    void unexpectedFailureDoesNotLeakInternalDetail() throws Exception {
        MvcResult result = mockMvc.perform(get("/api/__test/boom"))
                .andExpect(status().isInternalServerError())
                .andReturn();
        String json = result.getResponse().getContentAsString(StandardCharsets.UTF_8);

        assertThat(json).doesNotContain("internal detail");
        JsonNode body = objectMapper.readTree(json);
        assertThat(body.get("errorCode").asText()).isEqualTo("INTERNAL_ERROR");
        assertThat(body.get("message").asText()).isEqualTo(ErrorCode.INTERNAL_ERROR.defaultMessage());
        assertThat(ContractSchemas.validateComponent(body, "Envelope")).isEmpty();
    }

    @Test
    void blankRequestBodyIsReportedAsAValidationError() throws Exception {
        JsonNode body = bodyOf(mockMvc.perform(post("/api/__test/echo")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("VALIDATION_ERROR");
        assertThat(body.get("message").asText()).contains("name");
        assertThat(ContractSchemas.validateComponent(body, "Envelope")).isEmpty();
    }

    @Test
    void unknownRequestPropertyIsRejectedBecauseTheContractForbidsAdditionalProperties() throws Exception {
        JsonNode body = bodyOf(mockMvc.perform(post("/api/__test/echo")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"ok\",\"unexpected\":true}"))
                .andExpect(status().isBadRequest())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("MALFORMED_JSON");
    }

    @Test
    void unsupportedMediaTypeIsReportedAsAnEnvelope() throws Exception {
        JsonNode body = bodyOf(mockMvc.perform(post("/api/__test/echo")
                        .contentType(MediaType.TEXT_PLAIN)
                        .content("name=ok"))
                .andExpect(status().isUnsupportedMediaType())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("UNSUPPORTED_MEDIA_TYPE");
    }

    @Test
    void unsupportedMethodIsReportedAsAnEnvelope() throws Exception {
        JsonNode body = bodyOf(mockMvc.perform(delete("/api/__test/me"))
                .andExpect(status().isMethodNotAllowed())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("METHOD_NOT_ALLOWED");
    }

    @Test
    void unknownRouteIsReportedAsNotFoundRatherThanServerError() throws Exception {
        JsonNode body = bodyOf(mockMvc.perform(get("/api/__test/no-such-route"))
                .andExpect(status().isNotFound())
                .andReturn());

        assertThat(body.get("errorCode").asText()).isEqualTo("NOT_FOUND");
        assertThat(ContractSchemas.validateComponent(body, "Envelope")).isEmpty();
    }

    @Test
    void suppliedTraceIdIsEchoedInTheHeaderAndInTheEnvelope() throws Exception {
        MvcResult result = mockMvc.perform(get("/api/__test/null-data").header(TRACE_HEADER, "trace-abc-123"))
                .andExpect(status().isOk())
                .andExpect(header().string(TRACE_HEADER, "trace-abc-123"))
                .andReturn();

        assertThat(bodyOf(result).get("traceId").asText()).isEqualTo("trace-abc-123");
    }

    @Test
    void unusableTraceIdIsReplacedByAGeneratedOne() throws Exception {
        MvcResult result = mockMvc.perform(get("/api/__test/null-data").header(TRACE_HEADER, "bad id!"))
                .andExpect(status().isOk())
                .andExpect(header().string(TRACE_HEADER, matchesPattern("[A-Za-z0-9._-]{1,64}")))
                .andReturn();

        String traceId = bodyOf(result).get("traceId").asText();
        assertThat(traceId).isNotEqualTo("bad id!").matches("[A-Za-z0-9._-]{1,64}");
        assertThat(result.getResponse().getHeader(TRACE_HEADER)).isEqualTo(traceId);
    }

    @Test
    void pageResultSerialisesToExactlyTheContractPageSubjectShape() throws Exception {
        PageResult<Map<String, Object>> page = new PageResult<>(
                List.of(Map.of(
                        "id", 1,
                        "subjectCode", "DEMO-001",
                        "alias", "合成档案001",
                        "status", "ACTIVE",
                        "dataVersion", "demo-v1",
                        "createdAt", "2026-01-01T00:00:00Z")),
                1, 20, 1);

        JsonNode body = objectMapper.valueToTree(page);

        assertThat(ContractSchemas.validateComponent(body, "PageSubject"))
                .as("PageResult must match the contract's PageSubject: %s", body)
                .isEmpty();
    }

    @Test
    @WithAnonymousUser
    void anonymousRequestIsRefusedByTheAuthenticationEntryPointWithAnEnvelope() throws Exception {
        MvcResult result = mockMvc.perform(get("/api/__test/me"))
                .andExpect(status().isUnauthorized())
                .andReturn();

        String traceHeader = result.getResponse().getHeader(TRACE_HEADER);
        JsonNode body = bodyOf(result);

        assertThat(fieldNames(body)).containsExactlyElementsOf(ENVELOPE_PROPERTIES);
        assertThat(body.get("errorCode").asText()).isEqualTo("UNAUTHENTICATED");
        assertThat(body.get("data").isNull()).isTrue();
        // TraceIdFilter runs before the security chain, so even a 401 raised inside that chain
        // carries the same trace id in the header and in the body.
        assertThat(traceHeader).isNotNull().isEqualTo(body.get("traceId").asText());
        assertThat(ContractSchemas.validateComponent(body, "Envelope")).isEmpty();
    }

    @Test
    void authenticatedRequestOutsideTheApiIsRefusedByTheAccessDeniedHandler() throws Exception {
        MvcResult result = mockMvc.perform(get("/not-an-api-path"))
                .andExpect(status().isForbidden())
                .andReturn();

        JsonNode body = bodyOf(result);

        assertThat(fieldNames(body)).containsExactlyElementsOf(ENVELOPE_PROPERTIES);
        assertThat(body.get("errorCode").asText()).isEqualTo("ACCESS_DENIED");
        assertThat(result.getResponse().getHeader(TRACE_HEADER)).isEqualTo(body.get("traceId").asText());
        assertThat(ContractSchemas.validateComponent(body, "Envelope")).isEmpty();
    }

    private JsonNode bodyOf(MvcResult result) throws Exception {
        return objectMapper.readTree(result.getResponse().getContentAsString(StandardCharsets.UTF_8));
    }

    private static List<String> fieldNames(JsonNode body) {
        List<String> names = new ArrayList<>();
        body.fieldNames().forEachRemaining(names::add);
        return names;
    }

    @TestConfiguration
    static class StubEndpoints {

        @Bean
        StubController stubController() {
            return new StubController();
        }
    }

    @RestController
    static class StubController {

        /** Shaped like the contract's CurrentUser so the strict GET /api/me schema applies. */
        @GetMapping("/api/__test/me")
        Envelope<Map<String, Object>> me() {
            return Envelope.success(Map.of(
                    "id", 1,
                    "username", "admin",
                    "roles", List.of("ADMIN"),
                    "menus", List.of("subjects")));
        }

        @GetMapping("/api/__test/null-data")
        Envelope<Void> nullData() {
            return Envelope.success(null);
        }

        @GetMapping("/api/__test/denied")
        Envelope<Void> denied() {
            throw new BusinessException(ErrorCode.ACCESS_DENIED);
        }

        @GetMapping("/api/__test/boom")
        Envelope<Void> boom() {
            throw new IllegalStateException("internal detail that must not reach the client");
        }

        @PostMapping("/api/__test/echo")
        Envelope<String> echo(@Valid @RequestBody StubRequest request) {
            return Envelope.success(request.name());
        }
    }

    record StubRequest(@NotBlank String name) {
    }
}
