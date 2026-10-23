"""Four-stage deepagent-v1 workflow for course integration."""

from __future__ import annotations

import hashlib
import copy
import json
import math
import re
import time
from datetime import date
from typing import Any, Callable
from .course_fusion import select_fusion, validate_fusion_selection
from .course_graph import default_course_graph, validate_default_course_graph


CONTRACT_VERSION = "deepagent-v1"
WORKFLOW_VERSION = "causalrisk-workflow-v1"
MODEL_VERSION = "deepagent-causal-warning-v1"
STAGES = ("DATA_FUSION", "CAUSAL_GRAPH", "WARNING_MODEL", "EXPLANATION")
RUN_ID_RE = re.compile(r"run-[A-Za-z0-9][A-Za-z0-9-]{0,63}\Z")
SUBJECT_RE = re.compile(r"DEMO-[A-Za-z0-9-]{1,45}\Z")
LIMITATIONS = [
    "合成数据的研究型排序，不是临床诊断或经外部验证的风险概率。",
    "图谱箭头是先验约束下的条件性解释，不证明个体病因或干预效应。",
    "结果需结合资料完整性与人工复核意见使用。",
]
ALLOWED_FIELDS = {
    "contractVersion", "runId", "subjectCode", "dataVersion", "modelVersion",
    "predictionWindowMonths", "visits", "features",
}
FEATURES = {"APOE_E4_COUNT", "MRI_HIPPOCAMPUS_L", "MRI_HIPPOCAMPUS_R"}


class AgentContractError(ValueError):
    def __init__(self, message: str, status: int = 400, code: str = "VALIDATION_400") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def validate_request(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise AgentContractError("请求必须是 JSON 对象")
    extra = set(payload) - ALLOWED_FIELDS
    if extra:
        raise AgentContractError("请求包含未允许字段")
    if payload.get("contractVersion") != CONTRACT_VERSION or payload.get("modelVersion") != MODEL_VERSION:
        raise AgentContractError("契约或模型版本不匹配", 409, "AGENT_CONTRACT_MISMATCH")
    if not isinstance(payload.get("runId"), str) or not RUN_ID_RE.fullmatch(payload["runId"]):
        raise AgentContractError("runId 格式无效")
    if not isinstance(payload.get("subjectCode"), str) or not SUBJECT_RE.fullmatch(payload["subjectCode"]):
        raise AgentContractError("只接受 DEMO-* 合成档案")
    version = payload.get("dataVersion")
    if not isinstance(version, str) or not version.startswith("demo-") or len(version) > 100:
        raise AgentContractError("只接受 demo-* 数据版本")
    _check_utf8(version, "数据版本")
    window = payload.get("predictionWindowMonths")
    if type(window) is not int or not 6 <= window <= 60:
        raise AgentContractError("预测窗口必须是 6 至 60 个月的整数")
    visits, features = payload.get("visits"), payload.get("features")
    if not isinstance(visits, list) or len(visits) > 100 or not isinstance(features, list) or len(features) > 500:
        raise AgentContractError("访视或特征列表无效")
    visit_codes: set[str] = set()
    for item in visits:
        if not isinstance(item, dict) or set(item) - {"visitCode", "visitDate", "mmse", "moca", "cdrSb"}:
            raise AgentContractError("访视字段无效")
        _check_date(item.get("visitDate"), "访视日期")
        if not isinstance(item.get("visitCode"), str) or not item["visitCode"].strip() or len(item["visitCode"]) > 50:
            raise AgentContractError("访视编号无效")
        _check_utf8(item["visitCode"], "访视编号")
        if item["visitCode"] in visit_codes:
            raise AgentContractError("访视编号重复")
        visit_codes.add(item["visitCode"])
        for key, lower, upper in (("mmse", 0, 30), ("moca", 0, 30), ("cdrSb", 0, 18)):
            _check_number(item.get(key), key, lower, upper)
    for item in features:
        if not isinstance(item, dict) or set(item) - {"featureName", "featureValue", "recordedAt", "unit"}:
            raise AgentContractError("特征字段无效")
        _check_date(item.get("recordedAt"), "特征日期")
        name = item.get("featureName")
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise AgentContractError("特征名称无效")
        if name not in FEATURES:
            raise AgentContractError("特征名称不在合成模型白名单内")
        expected_unit = "count" if name == "APOE_E4_COUNT" else "normalized"
        if item.get("unit") != expected_unit:
            raise AgentContractError("特征单位与合成模型不兼容")
        value = item.get("featureValue")
        if name == "APOE_E4_COUNT":
            if value is not None and (type(value) is not int or value not in (0, 1, 2)):
                raise AgentContractError("APOE ε4 计数必须为 0、1、2 或 null")
        elif name in {"MRI_HIPPOCAMPUS_L", "MRI_HIPPOCAMPUS_R"}:
            _check_number(value, name, 0, 1)
        else:
            _check_number(value, name, None, None)


def _check_date(value: Any, label: str) -> None:
    if not isinstance(value, str):
        raise AgentContractError(f"{label}缺失")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise AgentContractError(f"{label}应为 YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise AgentContractError(f"{label}格式无效") from exc
    if parsed > date.today():
        raise AgentContractError(f"{label}不能晚于今天")


def _check_utf8(value: str, label: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise AgentContractError(f"{label}必须是有效 UTF-8 文本") from None


def _check_number(value: Any, label: str, lower: float | None, upper: float | None) -> None:
    if value is None:
        return
    try:
        finite = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise AgentContractError(f"{label}必须是有限数字或 null")
    if lower is not None and value < lower or upper is not None and value > upper:
        raise AgentContractError(f"{label}超出允许范围")


def payload_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def request_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate an owned snapshot before binding a digest or executing stages."""
    try:
        snapshot = copy.deepcopy(payload)
    except (TypeError, ValueError, RecursionError):
        raise AgentContractError("请求结构无效") from None
    validate_request(snapshot)
    return snapshot


def _checked_result(payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    # Lazy import keeps the request contract independent during module loading.
    from .course_protocol import CourseContract, validate_course_result
    try:
        validate_course_result(result, payload, CourseContract())
    except Exception:
        raise AgentContractError("工作流结果未通过一致性检查", 500, "ASSESSMENT_FAILED") from None
    return result


def _checked_stage(tool, arguments, validator):
    """Own stage inputs/output and reject errors before the next tool runs."""
    try:
        owned = copy.deepcopy(arguments)
        before = payload_digest(owned)
        output = copy.deepcopy(tool(*owned))
        if payload_digest(owned) != before:
            raise ValueError('stage changed its input')
        validator(output)
        return output
    except Exception:
        raise AgentContractError('阶段工具执行或证据校验失败', 500, 'ASSESSMENT_FAILED') from None


def _validate_scoring_inputs(inputs, visits, feature_map):
    # The workflow has already checked the fixed graph: every supplied
    # canonical feature has its original ACTIVE route. The public gating
    # helper still supports separate node/edge mask inspection.
    expected = (visits, [feature_map[name] for name in sorted(feature_map)])
    if type(inputs) is not tuple or len(inputs) != 2 or payload_digest(inputs) != payload_digest(expected):
        raise ValueError('gated observations differ from checked sources')


def _checked_tool(payload, score_tool, visits, features):
    """An already-valid request failing inside its score tool is execution 500."""
    try:
        tool_input = copy.deepcopy({
            "contractVersion": "stage4-v1", "subjectCode": payload["subjectCode"],
            "modelVersion": "python-demo-logistic-v1", "dataVersion": payload["dataVersion"],
            "predictionWindowMonths": payload["predictionWindowMonths"], "visits": visits,
            "features": features,
        })
        before = payload_digest(tool_input)
        legacy = copy.deepcopy(score_tool(tool_input))
        if payload_digest(tool_input) != before:
            raise ValueError('score tool changed its input')
        identity = {"status": "ok", "contractVersion": "stage4-v1", "provider": "python-research-contract",
                    "modelVersion": "python-demo-logistic-v1", "dataVersion": payload["dataVersion"]}
        if not isinstance(legacy, dict) or any(legacy.get(key) != value for key, value in identity.items()):
            raise ValueError("score tool identity")
        if not isinstance(legacy["warnings"], list) or not all(isinstance(row, str) for row in legacy["warnings"]):
            raise ValueError("score tool warnings")
        if legacy["qualityStatus"] != ("WARN" if legacy["warnings"] else "PASS"):
            raise ValueError("score tool quality")
        if not isinstance(legacy["explanations"], list) or not all(isinstance(row, dict) for row in legacy["explanations"]):
            raise ValueError("score tool explanations")
        if not {"score", "riskLevel"} <= legacy.keys():
            raise ValueError("score tool fields")
        return legacy
    except Exception:
        raise AgentContractError("评分工具执行或结果校验失败", 500, "ASSESSMENT_FAILED") from None


def graph_scoring_inputs(
    visits: list[dict[str, Any]], feature_map: dict[str, dict[str, Any]],
    graph: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Gate canonical observations through active nodes/edges, without inferring effects.

    The arrows specify input eligibility, not a computed biological mediation.
    MRI side preference remains a property of the existing demonstration scorer.
    """
    active_nodes = {node["id"] for node in graph["nodes"] if node["status"] == "ACTIVE"}
    active_edges = {(edge["from"], edge["to"]) for edge in graph["edges"]
                    if edge["status"] == "ACTIVE"}
    if not {"COGNITION", "WARNING"} <= active_nodes or ("COGNITION", "WARNING") not in active_edges:
        raise AgentContractError("图谱缺少有效评分入口", 500, "ASSESSMENT_FAILED")
    selected = [dict(feature_map[name]) for name in sorted(feature_map)
                if name in FEATURES and name in active_nodes and (name, "COGNITION") in active_edges]
    return [dict(row) for row in visits], selected


def run_workflow(payload: dict[str, Any], score_tool: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    payload = request_snapshot(payload)
    stages: list[dict[str, Any]] = []
    warnings: list[str] = []
    start = time.perf_counter()

    # DATA_FUSION: preserve source dates, select only observations available at
    # the latest visit, and record missing modalities instead of imputing them.
    selected = _checked_stage(select_fusion, (payload,),
                              lambda value: validate_fusion_selection(value, payload))
    visits, latest, cutoff = selected["visits"], selected["latest"], selected["indexDate"]
    excluded_future = selected["excludedPostIndexFeatures"]
    if excluded_future:
        warnings.append("索引访视之后采集的特征已排除，防止时间泄漏")
    feature_map = selected["features"]
    conflicting_feature = selected["conflictingFeatures"]
    missing = selected["missingModalities"]
    if missing:
        warnings.append("部分遗传或 MRI 指标缺失，图谱对应路径标为 MISSING")
    has_cognition = selected["hasCognition"]
    ambiguous_latest = selected["ambiguousIndex"]
    unsupported_window = selected["unsupportedWindow"]
    blocked = selected["blocked"]
    if ambiguous_latest:
        warnings.append("最近访视日期对应多个记录，索引访视无法唯一确定")
    if conflicting_feature:
        warnings.append("同一特征在同一天存在冲突值，需人工核对")
    if unsupported_window:
        warnings.append("当前合成研究规则仅支持 24 个月预警任务")
    stages.append(_stage("DATA_FUSION", "BLOCKED" if blocked else "COMPLETED", start, {
        "visitCount": len(visits), "featureCount": len(feature_map), "excludedPostIndexFeatures": excluded_future,
        "missingModalities": missing, "indexDate": cutoff, "qualityRuleVersion": "synthetic-qa-v1",
    }))
    if blocked:
        if not has_cognition:
            warnings.append("缺少可用的核心认知访视，风险排序已阻断")
        return _checked_result(payload, _result(payload, "BLOCKED", "DATA_FUSION", "BLOCKED", None, "UNAVAILABLE", warnings,
                       {"nodes": [], "edges": [], "paths": []}, [], stages, missing))

    # CAUSAL_GRAPH: a fixed, transparent prior graph with per-subject activation.
    tic = time.perf_counter()
    graph = _checked_stage(default_course_graph, (feature_map,),
                           lambda value: validate_default_course_graph(value, feature_map))
    paths = graph["paths"]
    stages.append(_stage("CAUSAL_GRAPH", "COMPLETED", tic, {"activePaths": sum(p["status"] == "ACTIVE" for p in paths)}))

    # WARNING_MODEL: active graph nodes/edges gate the canonical observations.
    # This does not estimate causal effects or change the demo scoring formula.
    tic = time.perf_counter()
    scoring_visits, scoring_features = _checked_stage(
        graph_scoring_inputs, (visits, feature_map, graph),
        lambda value: _validate_scoring_inputs(value, visits, feature_map))
    legacy = _checked_tool(payload, score_tool, scoring_visits, scoring_features)
    score = legacy["score"]
    warnings.extend(legacy["warnings"])
    stages.append(_stage("WARNING_MODEL", "COMPLETED", tic, {"method": "graph-masked-synthetic-rule-v1"}))

    tic = time.perf_counter()
    explanations = [dict(item, evidenceLevel="PREDICTIVE_DEMO", interpretation="预测贡献，不是因果效应")
                    for item in legacy["explanations"]]
    for item in explanations:
        item["source"] = "graph-masked-synthetic-rule-v1"
    stages.append(_stage("EXPLANATION", "COMPLETED", tic, {"contributionCount": len(explanations)}))
    quality = "WARN" if warnings else "PASS"
    return _checked_result(payload, _result(payload, "COMPLETED", "EXPLANATION", quality, score,
                   legacy["riskLevel"], list(dict.fromkeys(warnings)), graph, explanations, stages, missing))


def _stage(name: str, status: str, started: float, summary: dict[str, Any]) -> dict[str, Any]:
    return {"stage": name, "status": status, "durationMs": round((time.perf_counter() - started) * 1000, 3),
            "summary": summary}


def _result(payload: dict[str, Any], status: str, current_stage: str, quality: str,
            score: float | None, level: str, warnings: list[str], graph: dict[str, Any],
            explanations: list[dict[str, Any]], stages: list[dict[str, Any]], missing: list[str]) -> dict[str, Any]:
    return {
        "status": status, "contractVersion": CONTRACT_VERSION, "runId": payload["runId"],
        "workflowVersion": WORKFLOW_VERSION, "currentStage": current_stage,
        "dataVersion": payload["dataVersion"], "modelVersion": payload["modelVersion"],
        "qualityStatus": quality, "riskScore": score, "riskLevel": level,
        "warnings": warnings, "graph": graph, "explanations": explanations,
        "missingModalities": missing, "limitations": list(LIMITATIONS), "stages": stages,
        "dataSource": "SYNTHETIC_DEMO", "reviewRequired": True,
    }
