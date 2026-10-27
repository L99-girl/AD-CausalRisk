package com.adcausalrisk.backend.agent;

import com.adcausalrisk.backend.common.BusinessException;
import com.adcausalrisk.backend.common.ErrorCode;

import java.math.BigDecimal;
import java.util.List;
import java.util.Objects;

/**
 * Runtime guard for the four rules the contract states but a JSON parser cannot enforce:
 *
 * <ol>
 *   <li>every required property is present;</li>
 *   <li>{@code BLOCKED} means qualityStatus=BLOCKED, riskScore=null, riskLevel=UNAVAILABLE, and
 *       {@code COMPLETED} means a numeric riskScore in [0,1] plus a graphVersion;</li>
 *   <li>the three version constants, dataSource and reviewRequired are the expected values;</li>
 *   <li>the runId/dataVersion echoed back are the ones that were sent.</li>
 * </ol>
 *
 * <p>Failures are reported as {@code AGENT_CONTRACT_MISMATCH}: a result that does not match the
 * contract must never be persisted as a successful assessment.
 */
public final class AgentResultValidator {

    public static final String CODE = "AGENT_CONTRACT_MISMATCH";

    private AgentResultValidator() {
    }

    /** Validates a result whose request is not available (for example a later GET). */
    public static void validate(AgentResult result) {
        validate(null, result);
    }

    /** Validates structure, constants and - when {@code request} is present - the echoed identity. */
    public static void validate(AgentRequest request, AgentResult result) {
        if (result == null) {
            throw mismatch("响应体为空");
        }
        requireText(result.runId(), "runId");
        requireText(result.currentStage(), "currentStage");
        requireText(result.dataVersion(), "dataVersion");
        requireText(result.contractVersion(), "contractVersion");
        requireText(result.workflowVersion(), "workflowVersion");
        requireText(result.modelVersion(), "modelVersion");
        requireText(result.dataSource(), "dataSource");
        requireNonNull(result.status(), "status");
        requireNonNull(result.qualityStatus(), "qualityStatus");
        requireNonNull(result.riskLevel(), "riskLevel");
        requireNonNull(result.graph(), "graph");
        requireList(result.warnings(), "warnings");
        requireList(result.explanations(), "explanations");
        requireList(result.missingModalities(), "missingModalities");
        requireList(result.limitations(), "limitations");
        requireList(result.stages(), "stages");

        if (!AgentResult.CONTRACT_VERSION.equals(result.contractVersion())) {
            throw mismatch("contractVersion=" + result.contractVersion());
        }
        if (!AgentResult.WORKFLOW_VERSION.equals(result.workflowVersion())) {
            throw mismatch("workflowVersion=" + result.workflowVersion());
        }
        if (!AgentResult.MODEL_VERSION.equals(result.modelVersion())) {
            throw mismatch("modelVersion=" + result.modelVersion());
        }
        if (!AgentResult.DATA_SOURCE.equals(result.dataSource())) {
            throw mismatch("dataSource=" + result.dataSource());
        }
        if (!result.reviewRequired()) {
            throw mismatch("reviewRequired 必须为 true");
        }
        if (request != null) {
            if (!request.runId().equals(result.runId())) {
                throw mismatch("runId 回显不一致: " + result.runId());
            }
            if (!request.dataVersion().equals(result.dataVersion())) {
                throw mismatch("dataVersion 回显不一致: " + result.dataVersion());
            }
        }

        if (result.status() == AgentResult.Status.BLOCKED) {
            if (result.qualityStatus() != AgentResult.QualityStatus.BLOCKED) {
                throw mismatch("BLOCKED 时 qualityStatus 必须为 BLOCKED");
            }
            if (result.riskScore() != null) {
                throw mismatch("BLOCKED 时 riskScore 必须为 null");
            }
            if (result.riskLevel() != AgentResult.RiskLevel.UNAVAILABLE) {
                throw mismatch("BLOCKED 时 riskLevel 必须为 UNAVAILABLE");
            }
        } else {
            if (result.qualityStatus() == AgentResult.QualityStatus.BLOCKED) {
                throw mismatch("COMPLETED 时 qualityStatus 不能是 BLOCKED");
            }
            BigDecimal score = result.riskScore();
            if (score == null) {
                throw mismatch("COMPLETED 时 riskScore 不能为 null");
            }
            if (score.compareTo(BigDecimal.ZERO) < 0 || score.compareTo(BigDecimal.ONE) > 0) {
                throw mismatch("riskScore 超出 [0,1]: " + score);
            }
            if (result.riskLevel() == AgentResult.RiskLevel.UNAVAILABLE) {
                throw mismatch("COMPLETED 时 riskLevel 不能是 UNAVAILABLE");
            }
            String version = result.graph().graphVersion();
            if (version == null || version.isBlank()) {
                throw mismatch("COMPLETED 时 graph.graphVersion 必填");
            }
        }

        validateGraph(result.graph());
        validateExplanations(result.explanations());
        validateStages(result.stages());
    }

    private static void validateGraph(AgentResult.Graph graph) {
        requireList(graph.nodes(), "graph.nodes");
        requireList(graph.edges(), "graph.edges");
        requireList(graph.paths(), "graph.paths");

        for (AgentResult.Node node : graph.nodes()) {
            if (node == null) {
                throw mismatch("graph.nodes 含 null");
            }
            requireText(node.id(), "graph.nodes[].id");
            requireText(node.label(), "graph.nodes[].label");
            requireNonNull(node.status(), "graph.nodes[].status");
            requireText(node.evidenceLevel(), "graph.nodes[].evidenceLevel");
        }
        for (AgentResult.Edge edge : graph.edges()) {
            if (edge == null) {
                throw mismatch("graph.edges 含 null");
            }
            requireText(edge.from(), "graph.edges[].from");
            requireText(edge.to(), "graph.edges[].to");
            requireNonNull(edge.status(), "graph.edges[].status");
            if (!AgentResult.EVIDENCE_PRIOR.equals(edge.evidenceLevel())) {
                throw mismatch("graph.edges[].evidenceLevel 必须为 PRIOR");
            }
            if (!AgentResult.EDGE_DIRECTION.equals(edge.direction())) {
                throw mismatch("graph.edges[].direction 必须为 CONDITIONAL");
            }
        }
        for (AgentResult.Route path : graph.paths()) {
            if (path == null) {
                throw mismatch("graph.paths 含 null");
            }
            requireList(path.nodes(), "graph.paths[].nodes");
            requireNonNull(path.status(), "graph.paths[].status");
            if (!AgentResult.EVIDENCE_PRIOR.equals(path.evidenceLevel())) {
                throw mismatch("graph.paths[].evidenceLevel 必须为 PRIOR");
            }
        }
    }

    private static void validateExplanations(List<AgentResult.Explanation> explanations) {
        for (AgentResult.Explanation explanation : explanations) {
            if (explanation == null) {
                throw mismatch("explanations 含 null");
            }
            requireText(explanation.feature(), "explanations[].feature");
            requireText(explanation.label(), "explanations[].label");
            requireText(explanation.message(), "explanations[].message");
            requireText(explanation.source(), "explanations[].source");
            requireText(explanation.interpretation(), "explanations[].interpretation");
            requireNonNull(explanation.direction(), "explanations[].direction");
            requireNonNull(explanation.contribution(), "explanations[].contribution");
            if (!AgentResult.EVIDENCE_PREDICTIVE_DEMO.equals(explanation.evidenceLevel())) {
                throw mismatch("explanations[].evidenceLevel 必须为 PREDICTIVE_DEMO");
            }
        }
    }

    private static void validateStages(List<AgentResult.Stage> stages) {
        if (stages.isEmpty()) {
            throw mismatch("stages 不能为空");
        }
        for (AgentResult.Stage stage : stages) {
            if (stage == null) {
                throw mismatch("stages 含 null");
            }
            requireNonNull(stage.stage(), "stages[].stage");
            requireNonNull(stage.status(), "stages[].status");
            if (stage.durationMs() < 0) {
                throw mismatch("stages[].durationMs 不能为负");
            }
        }
    }

    private static void requireText(String value, String name) {
        if (value == null || value.isBlank()) {
            throw mismatch(name + " 为空");
        }
    }

    private static void requireNonNull(Object value, String name) {
        if (value == null) {
            throw mismatch(name + " 缺失");
        }
    }

    private static void requireList(List<?> value, String name) {
        if (value == null) {
            throw mismatch(name + " 缺失");
        }
    }

    private static BusinessException mismatch(String detail) {
        return new BusinessException(ErrorCode.INTERNAL_ERROR, CODE + ": " + Objects.requireNonNullElse(detail, ""));
    }
}