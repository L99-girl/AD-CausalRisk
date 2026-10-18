"""Deterministic synthetic research reports, shared by local demo and callers.

This module never renders real-retrospective records or loads an estimator.
"""
from datetime import datetime
from html import escape
import math
import re

REPORT_VERSION = 'adcr-synthetic-report-v1'
STYLESHEET_PATH = '/api/system/reports/report.css'
REPORT_STYLE = '''*{box-sizing:border-box}body{margin:0;background:#f3f5f9;color:#17263d;font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1066px;margin:32px auto;padding:32px;background:white;border:1px solid #d7deeb;border-radius:16px}h1{font-size:30px;line-height:1.35}h2{font-size:21px;margin-top:30px}a{color:#2348a5}.scope{color:#855713;background:#fff7e7;border-left:5px solid #a56c15;padding:16px}.values{display:flex;gap:16px;flex-wrap:wrap}.values article{flex:1;min-width:200px;background:#eef3ff;padding:16px;border-radius:10px}.value{font-size:28px;font-weight:700;display:block}table{border-collapse:collapse;width:100%;text-align:left}th,td{padding:10px;border-bottom:1px solid #d7deeb}caption{text-align:left;padding:8px 0}.table-scroll{overflow-x:auto}dl{display:grid;grid-template-columns:170px 1fr;gap:8px}dd{margin:0;overflow-wrap:anywhere}li{margin-bottom:6px}.print-help{color:#334965}:focus-visible{outline:3px solid #2348a5;outline-offset:3px}@media(max-width:600px){main{margin:0;padding:20px;border-radius:0}h1{font-size:26px}dl{display:block}dd{margin-bottom:12px}}@page{size:A4;margin:16mm}@media print{body{background:white;font-size:10pt}main{padding:0;margin:0;max-width:none;border:0}h1{font-size:20pt}h2{break-after:avoid}thead{display:table-header-group}tr,.values article{break-inside:avoid}.print-help,.back{display:none}.table-scroll{overflow:visible}.values article{background:white;border:1px solid #d7deeb}dd{font-size:8pt}}'''
MODEL = 'adni-v8-final-materialized-2026-10-11'
VARIANTS = {'latest', 'history', 'prior_availability', 'trajectory_graph', 'random_availability', 'random_graph'}
LABELS = {'age_years': '年龄', 'education_years': '教育年限', 'mmse': '简易精神状态检查（MMSE）',
          'cdr_sb': '临床痴呆评定量表分项总分（CDR-SB）', 'cdr_global': '临床痴呆评定量表总体评分（CDR Global）'}
STAGES = ('SOURCE_INTEGRATION', 'PARTICIPANT_GRAPH', 'RISK_PREDICTION', 'PREDICTION_EXPLANATION')
STAGE_LABELS = ('来源整合', '个体来源图', '固定模型计算', '来源撤除解释')
BOUNDARIES = [
    '本报告只对应明确声明的合成案例，不属于公开浏览对象或真实患者。',
    '模型输出和来源贡献未被认证为个人临床风险、病因或治疗效果。',
    '来源标签和合成声明不构成来源真实性、MCI资格或历史可获得性的独立认证。',
    '空来源基线不是健康人群患病率；来源撤除贡献不是改变指标的干预收益。',
    '竞争痴呆分支的原研究事件很少，可靠性能尚未建立。',
    '输入检查通过不等于临床可用；重放或生成报告不构成新拟合、独立验证或新增患者。',
]


class ReportError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def ensure(condition, code='REPORT_INPUT_INVALID'):
    if not condition:
        raise ReportError(code)


def finite(value):
    return type(value) in (float, int) and math.isfinite(value)


def text(value, limit=200):
    ensure(isinstance(value, str) and 0 < len(value) <= limit)
    return value


def build_report(task, *, audience='research'):
    """Map only allowlisted fields from a completed synthetic task; no fitting."""
    ensure(isinstance(audience, str) and audience in {'research', 'teaching'}, 'REPORT_AUDIENCE_INVALID')
    try:
        ensure(isinstance(task, dict) and task['input_mode'] == 'SYNTHETIC_TEST', 'REPORT_SCOPE_NOT_ALLOWED')
        ensure(task['status'] == 'COMPLETED' and task['result'] is not None, 'REPORT_TASK_NOT_COMPLETED')
        ensure(re.fullmatch(r'wb2-[a-f0-9]{32}', task['id']) is not None)
        ensure(task['variant'] in VARIANTS)
        datetime.fromisoformat(text(task['created_at_utc'], 60))
        upstream = task['result']['upstream']
        ensure(upstream['inputMode'] == 'SYNTHETIC_TEST', 'REPORT_SCOPE_NOT_ALLOWED')
        core = upstream['result']
        ensure(core['contractVersion'] == 'adni-v8-research-v1' and core['modelVersion'] == MODEL)
        ensure(core['variant'] == task['variant'] and core['status'] == 'RESEARCH_COMPUTATION_COMPLETE')
        ensure(core['scope'] == 'LOCAL_RESEARCH_ONLY' and core['clinicalUseEstablished'] is False, 'REPORT_SCOPE_NOT_ALLOWED')
        ensure(re.fullmatch(r'LOCAL-SYNTHETIC-[A-Za-z0-9-]{1,48}', core['caseCode']) is not None, 'REPORT_SCOPE_NOT_ALLOWED')
        ensure(type(core['predictionWindowMonths']) is int and core['predictionWindowMonths'] == 24)
        ensure(core['qualityStatus'] in {'PASS', 'WARN'})
        ad, other = core['adCumulativeIncidence'], core['otherDementiaCumulativeIncidence']
        ensure(finite(ad) and finite(other) and 0 <= ad <= 1 and 0 <= other <= 1 and ad + other <= 1 + 1e-12)
        explanation = core['explanation']
        ensure(explanation['reference'] == 'source_withdrawal_with_derived_features_and_masks_recomputed')
        ensure(explanation['causalEffectIdentified'] is False, 'REPORT_SCOPE_NOT_ALLOWED')
        rows = explanation['contributions']
        ensure(isinstance(rows, list) and len(rows) == 5 and {row['sourceFamily'] for row in rows} == set(LABELS))
        ensure(all(finite(row['contribution']) for row in rows))
        ensure(finite(explanation['baseline']) and 0 <= explanation['baseline'] <= 1)
        ensure(finite(explanation['reconstructionResidual']) and abs(explanation['reconstructionResidual']) <= 1e-12)
        ensure(abs(explanation['baseline'] + sum(row['contribution'] for row in rows) - ad) <= 1e-12, 'REPORT_RECONSTRUCTION_FAILED')
        ensure(isinstance(core['graph']['nodes'], list) and 0 < len(core['graph']['nodes']) <= 1000)
        sources = []
        for node in core['graph']['nodes']:
            ensure(text(node['source_visit']).startswith('DEMO-'), 'REPORT_SCOPE_NOT_ALLOWED')
            ensure(finite(node['value']) or node['value'] is None)
            sources.append({'feature': text(node['feature']), 'value': node['value'], 'unit': text(node['unit']),
                            'measurement_date': text(node['measurement_date'], 10)})
        ensure([stage['stage'] for stage in core['stages']] == list(STAGES))
        for digest in (core['modelArtifactSha256'], task['result']['fixture_sha256']):
            ensure(isinstance(digest, str) and re.fullmatch(r'[a-f0-9]{64}', digest) is not None)
        missing = core['missingInputs']
        ensure(isinstance(missing, list) and len(missing) <= 100)
        missing = [text(value) for value in missing]
        return {'report_version': REPORT_VERSION, 'scope': 'SYNTHETIC_TEST', 'audience': audience,
                'title': '合成验证研究报告' if audience == 'research' else '合成案例教学演示报告',
                'task_id': task['id'], 'created_at_utc': task['created_at_utc'], 'variant': core['variant'],
                'model_version': MODEL, 'model_artifact_sha256': core['modelArtifactSha256'],
                'fixture_sha256': task['result']['fixture_sha256'], 'quality_status': core['qualityStatus'],
                'prediction_window_months': 24, 'predictions': {'ad': ad, 'other_dementia': other},
                'explanation': {'reference': explanation['reference'], 'baseline': explanation['baseline'],
                                'contributions': [{'source': row['sourceFamily'], 'label': LABELS[row['sourceFamily']],
                                                   'value': row['contribution']} for row in rows],
                                'reconstruction_residual': explanation['reconstructionResidual']},
                'sources': sources if audience == 'research' else [], 'missing_inputs': missing,
                'stages': list(STAGE_LABELS), 'stage_durations_available': False,
                'clinical_use_established': False, 'causal_effect_identified': False,
                'independent_eligibility_verified': False, 'warnings': list(BOUNDARIES)}
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as error:
        if isinstance(error, ReportError):
            raise
        raise ReportError('REPORT_INPUT_INVALID') from None


def render_html(task, *, audience='research', stylesheet_href=None):
    """Standalone, script-free HTML. Browser printing can save a PDF locally."""
    report = build_report(task, audience=audience)
    ensure(stylesheet_href is None or stylesheet_href == STYLESHEET_PATH, 'REPORT_STYLESHEET_INVALID')
    style_element = '<style>' + REPORT_STYLE + '</style>' if stylesheet_href is None else '<link rel="stylesheet" href="' + STYLESHEET_PATH + '">'
    e = lambda value: escape(str(value), quote=True)
    p = report['predictions']
    contribution_rows = ''.join(f'<tr><th scope="row">{e(row["label"])}</th><td>{row["value"] * 100:+.5f} 个百分点</td></tr>'
                                for row in report['explanation']['contributions'])
    source_table = ''
    if audience == 'research':
        source_rows = ''.join(f'<tr><td>{e(row["feature"])}</td><td>{e(row["value"] if row["value"] is not None else "缺失")}</td>'
                              f'<td>{e(row["unit"])}</td><td>{e(row["measurement_date"])}</td></tr>' for row in report['sources'])
        source_table = f'<section><h2>合成输入来源</h2><div class="table-scroll" tabindex="0"><table><caption>合成测量值与日期；不属于真实患者</caption><thead><tr><th>项目</th><th>数值</th><th>单位</th><th>测量日期</th></tr></thead><tbody>{source_rows}</tbody></table></div></section>'
    warnings = ''.join(f'<li>{e(value)}</li>' for value in report['warnings'])
    stages = ''.join(f'<li>{e(value)}</li>' for value in report['stages'])
    missing = '、'.join(report['missing_inputs']) or '本次模型输入未报告缺失；不代表完整多模态或临床资格已认证。'
    details = f'<dt>模型产物 SHA-256</dt><dd>{e(report["model_artifact_sha256"])}</dd><dt>合成案例 SHA-256</dt><dd>{e(report["fixture_sha256"])}</dd>' if audience == 'research' else ''
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(report['title'])} · AD-CausalRisk</title>
{style_element}</head>
<body><main><a class="back" href="/public/#task={e(report['task_id'])}">返回同一系统的合成任务</a><p>AD-CausalRisk · 合成验证</p><h1>{e(report['title'])}</h1><p class="print-help">使用浏览器菜单“打印”或按 Ctrl+P，可选择“另存为 PDF”。这是浏览器排版导出。</p>
<div class="scope"><strong>仅合成案例 · 非诊疗报告</strong><p>{e(BOUNDARIES[0])}</p></div>
<section><h2>24个月固定模型输出</h2><div class="values"><article>AD记录诊断累计发生率<span class="value">{p['ad'] * 100:.3f}%</span>合成输入对应的模型数值</article><article>其他痴呆累计发生率<span class="value">{p['other_dementia'] * 100:.3f}%</span>分支可靠性尚未建立</article></div><p>模型与输入检查：{e(report['quality_status'])}。{e(missing)}</p></section>
<section><h2>来源撤除解释</h2><p>32组合重新计算派生量与缺失掩码；下表相对空来源基线，不是治疗收益。</p><div class="table-scroll" tabindex="0"><table><caption>来源贡献，正负号表示模型输出方向</caption><thead><tr><th>来源</th><th>相对贡献</th></tr></thead><tbody>{contribution_rows}</tbody></table></div><p>空来源基线 {report['explanation']['baseline']:.8f}；原重构残差 {report['explanation']['reconstruction_residual']:.3g}。数值重构通过不证明因果或临床有效性。</p></section>
{source_table}<section><h2>实际计算环节</h2><ol>{stages}</ol><p>来自已完成任务；未记录逐阶段耗时，不补造时间。</p></section>
<section><h2>版本和来源</h2><dl><dt>任务</dt><dd>{e(report['task_id'])}</dd><dt>原任务创建时间</dt><dd>{e(report['created_at_utc'])}</dd><dt>模型</dt><dd>{e(report['model_version'])} / {e(report['variant'])}</dd><dt>报告格式</dt><dd>{e(REPORT_VERSION)}</dd>{details}</dl></section>
<section><h2>适用范围与限制</h2><ul>{warnings}</ul></section></main></body></html>'''
