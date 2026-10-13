package com.adcausalrisk.backend.contract;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SchemaValidatorsConfig;
import com.networknt.schema.SpecVersion;
import com.networknt.schema.ValidationMessage;

/**
 * Validates real responses against the frozen target contract
 * ({@code contracts/java-business.target.openapi.json}) instead of a hand-written copy of
 * its field list.
 *
 * <p>The file is read from the repository, so a contract change is picked up by the tests
 * immediately and a response that drifts from the contract fails the build. The document
 * is OpenAPI 3.1, i.e. JSON Schema 2020-12, and local {@code $ref}s are inlined against
 * the same document.
 *
 * <p>This is a test utility. It deliberately fails loudly (rather than skipping) when the
 * contract file cannot be found, so a broken path can never look like a passing check.
 */
public final class ContractSchemas {

    private static final String CONTRACT_RELATIVE_PATH = "contracts/java-business.target.openapi.json";

    private static final int MAX_PARENT_LOOKUPS = 4;

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static final JsonNode DOCUMENT = loadDocument();

    private static final JsonSchemaFactory FACTORY =
            JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012);

    private ContractSchemas() {
    }

    /** Validates {@code body} against {@code paths[path][method].responses[status]}. */
    public static Set<ValidationMessage> validateResponse(JsonNode body, String path, String method, int status) {
        return validate(body, responseSchema(path, method, status));
    }

    /** Validates {@code body} against {@code #/components/schemas/<name>}. */
    public static Set<ValidationMessage> validateComponent(JsonNode body, String componentName) {
        JsonNode schema = DOCUMENT.path("components").path("schemas").path(componentName);
        if (schema.isMissingNode()) {
            throw new IllegalStateException("the frozen contract declares no component schema named " + componentName);
        }
        return validate(body, schema);
    }

    /** The raw (unresolved) schema node the contract declares for one operation and status. */
    public static JsonNode responseSchema(String path, String method, int status) {
        JsonNode pathItem = DOCUMENT.path("paths").path(path);
        if (pathItem.isMissingNode()) {
            throw new IllegalStateException("the frozen contract declares no path " + path);
        }
        JsonNode operation = pathItem.path(method);
        if (operation.isMissingNode()) {
            throw new IllegalStateException(
                    "the frozen contract declares no " + method.toUpperCase() + " " + path);
        }
        JsonNode schema = operation.path("responses").path(Integer.toString(status))
                .path("content").path("application/json").path("schema");
        if (schema.isMissingNode()) {
            throw new IllegalStateException("the frozen contract declares no application/json schema for "
                    + method.toUpperCase() + " " + path + " -> " + status);
        }
        return schema;
    }

    private static Set<ValidationMessage> validate(JsonNode body, JsonNode schema) {
        JsonSchema jsonSchema = FACTORY.getSchema(resolve(schema), validatorsConfig());
        return jsonSchema.validate(body);
    }

    private static SchemaValidatorsConfig validatorsConfig() {
        return SchemaValidatorsConfig.builder()
                // The contract declares format: date-time / date. Without this the validator
                // would accept any string, which is weaker than what the contract promises.
                .formatAssertionsEnabled(true)
                .build();
    }

    private static JsonNode resolve(JsonNode node) {
        return resolve(node, new HashSet<>());
    }

    private static JsonNode resolve(JsonNode node, Set<String> resolving) {
        if (node.isObject()) {
            JsonNode reference = node.get("$ref");
            if (reference != null && reference.isTextual()) {
                if (node.size() > 1) {
                    throw new IllegalStateException(
                            "$ref with sibling keywords is not supported by this test helper: " + reference.asText());
                }
                String pointer = reference.asText();
                if (!pointer.startsWith("#/")) {
                    throw new IllegalStateException("only local $ref is supported: " + pointer);
                }
                if (!resolving.add(pointer)) {
                    throw new IllegalStateException("cyclic $ref: " + pointer);
                }
                JsonNode target = DOCUMENT.at(pointer.substring(1));
                if (target.isMissingNode()) {
                    throw new IllegalStateException("unresolved $ref: " + pointer);
                }
                JsonNode resolved = resolve(target.deepCopy(), resolving);
                resolving.remove(pointer);
                return resolved;
            }
            ObjectNode copy = MAPPER.createObjectNode();
            node.properties().forEach(entry -> copy.set(entry.getKey(), resolve(entry.getValue(), resolving)));
            return copy;
        }
        if (node.isArray()) {
            ArrayNode copy = MAPPER.createArrayNode();
            node.forEach(element -> copy.add(resolve(element, resolving)));
            return copy;
        }
        return node.deepCopy();
    }

    private static JsonNode loadDocument() {
        Path file = locateContract();
        try {
            return MAPPER.readTree(Files.readString(file, StandardCharsets.UTF_8));
        } catch (IOException exception) {
            throw new UncheckedIOException("cannot read the frozen contract at " + file, exception);
        }
    }

    private static Path locateContract() {
        Path directory = Path.of("").toAbsolutePath();
        for (int depth = 0; depth < MAX_PARENT_LOOKUPS && directory != null; depth++) {
            Path candidate = directory.resolve(CONTRACT_RELATIVE_PATH);
            if (Files.isRegularFile(candidate)) {
                return candidate;
            }
            directory = directory.getParent();
        }
        throw new IllegalStateException("cannot find " + CONTRACT_RELATIVE_PATH + " by walking up from "
                + Path.of("").toAbsolutePath() + "; run the tests from inside the repository");
    }
}
