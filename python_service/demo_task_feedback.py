"""Presentation of existing synthetic task failures; never changes scoring or DTOs."""
import json
import re

VARIANTS = {
    'trajectory_graph': '轨迹与先验图方案', 'latest': '最近值方案',
    'history': '历史特征方案', 'prior_availability': '可获得性对照',
    'random_availability': '随机可获得性对照', 'random_graph': '随机图对照',
}
SCENARIOS = {
    'valid': {'label': '正常示例 · 生成合成预测',
              'help': '使用已绑定的合法合成输入，计算模型结果、来源图及解释。'},
    'invalid_mmse': {'label': '校验测试 · MMSE 非整数', 'code': 'MMSE_TOTAL_NOT_INTEGER', 'http': 400,
                     'help': '此案例故意传入 MMSE 总分 27.25；规则要求 0—30 的整数，预期拒绝且不生成预测。'},
    'future_availability': {'label': '校验测试 · 来源在预测后可获得', 'code': 'GRAPH_NOT_AVAILABLE_AT_INDEX', 'http': 400,
                            'help': '此案例故意使用预测时点之后才可获得的来源，预期拒绝且不生成预测。'},
    'missing_availability': {'label': '校验测试 · 缺少来源可获得日期', 'code': 'MISSING_GRAPH_AVAILABILITY', 'http': 400,
                             'help': '此案例故意省略来源可获得日期，预期拒绝且不生成预测。'},
    'real_mode': {'label': '校验测试 · 合成入口收到真实模式', 'code': 'SYNTHETIC_ONLY', 'http': 403,
                  'help': '此案例故意向合成入口声明真实模式，预期拒绝。真实记录使用本系统的受控入口。'},
}


def expected_rejection(task):
    """Match detail evidence, not just a failed state or negative-test name."""
    rule = SCENARIOS.get(task.get('scenario'), {})
    error = task.get('error')
    return (task.get('input_mode') == 'SYNTHETIC_TEST'
            and task.get('variant') in VARIANTS and task.get('status') == 'FAILED'
            and task.get('result') is None and isinstance(error, dict)
            and 'code' in rule and error.get('code') == rule['code']
            and type(error.get('upstream_http_status')) is int
            and error['upstream_http_status'] == rule['http'])


def training_summary(manifest):
    """Summarize verified reproduction metadata, without loading a model or records.

    The host must verify its bound manifest and artifacts before serving the UI.
    This validates the declared evidence shape, not clinical validity or disk bytes.
    """
    try:
        verification = manifest['verification']
        counts = [manifest['training_subjects'], manifest['training_person_months'],
                  verification['metric_comparisons'], verification['paired_comparisons']]
        valid = (manifest['status'] == 'verified_fixed_specification_reproduction'
                 and set(manifest['models']) == set(VARIANTS)
                 and manifest['new_fixed_specification_fits'] == len(VARIANTS)
                 and all(type(value) is int and value > 0 for value in counts)
                 and all(type(verification[key]) in (int, float) and verification[key] == 0
                         for key in ('maximum_metric_difference', 'maximum_paired_difference',
                                     'maximum_serialization_prediction_difference'))
                 and verification['solver_iterations_match_original'] is True
                 and manifest['clinical_use_established'] is False
                 and manifest['individual_causal_effect_identified'] is False)
    except (KeyError, TypeError):
        valid = False
    if not valid:
        return '训练复现记录未通过摘要检查，请查看系统检查结果。当前无法确认训练状态。'
    return (f'当前研究模型已训练并保存：{counts[0]} 名受试者、{counts[1]} 个人月，'
            f'{len(VARIANTS)} 种固定输入方案；{counts[2]} 项指标和 {counts[3]} 项配对比较复现一致。'
            '首次计算时才将保存模型加载到进程；未加载不等于未训练。临床准确性与个体因果效应尚未确立。')


def _replace(content, old, new):
    if content.count(old) != 1:
        raise ValueError('TASK_FEEDBACK_UI_INCOMPATIBLE')
    return content.replace(old, new)


def enhance_feedback_asset(name, content, *, model_summary=None):
    """Adapt the host's existing assets in memory; keep old sources and API stable."""
    if name == 'index.html':
        from html import escape
        summary = escape(model_summary or '此环境未提供训练复现记录，请查看维护方的模型说明。')
        content = _replace(content, '<div id="synthetic-status"',
            '<p id="scenario-help" class="help" aria-live="polite"></p>'
            '<details class="model-help"><summary>模型训练与版本说明</summary>'
            f'<p id="training-summary">{summary}</p>'
            '<p>六种方案比较输入和图结构，不表示六代系统。页面只维护这一套系统；'
            '接口、模型及数据的兼容标识保留用于调用和结果追溯，编号不代表准确率高低。</p>'
            '<p>本页合成案例调用已保存研究模型。课程默认合成接口使用加性演示规则，两者范围不同。</p>'
            '</details><div id="synthetic-status"')
        content = _replace(content, '<button id="cancel-task"',
            '<button id="run-valid-example" type="button" class="button" hidden>运行正常示例</button><button id="cancel-task"')
        content = content.replace('固定模型变体', '输入方案').replace('已绑定情景', '运行目的')
        for key, label in VARIANTS.items():
            # Option values remain original contract identifiers.
            content = re.sub(r'(<option value="' + key + r'">)[^<]*(</option>)',
                             lambda match: match[1] + label + match[2], content)
        content = _replace(content, '<p id="model-binding"', '<details><summary>模型与来源技术标识</summary><p id="model-binding"')
        # Close only the known binding paragraph, not arbitrary markup.
        content = _replace(content, 'id="model-binding" class="mono"></p>', 'id="model-binding" class="mono"></p></details>')
    elif name == 'app.js':
        config = json.dumps({'variants': VARIANTS, 'scenarios': SCENARIOS}, ensure_ascii=False)
        script = FEEDBACK_JS.replace('__CONFIG__', config)
        content = _replace(content, '$(id).textContent = message;',
                           "$(id).classList.remove('validation-expected');$(id).textContent = message;")
        original_options = "$('scenario').innerHTML=Object.entries(catalog.scenarios).map(([key,label])=>`<option value=\"${escapeHtml(key)}\">${escapeHtml(label)}</option>`).join('');"
        content = _replace(content, original_options, "setScenarioOptions(catalog.scenarios);")
        content = _replace(content, "$('synthetic-result-title').textContent=taskLabels[task.status]||task.status;",
                           "const expected=expectedTaskRejection(task);$('synthetic-result-title').textContent=expected?'校验通过：已按规则拒绝':taskLabels[task.status]||task.status;")
        begin = "  $('task-state').innerHTML="
        line = next((line for line in content.splitlines() if line.startswith(begin)), '')
        if not line:
            raise ValueError('TASK_FEEDBACK_UI_INCOMPATIBLE')
        content = _replace(content, line, "  renderTaskFeedback(task,expected);")
        old = "if(task.status!=='COMPLETED'||!task.result){status('synthetic-status',task.status==='FAILED'?'原接口拒绝或任务失败，没有可用预测。':taskLabels[task.status],task.status==='FAILED');return;}"
        content = _replace(content, old, "if(task.status!=='COMPLETED'||!task.result){showTaskFeedback(task,expected);return;}")
        content = content.replace("${escapeHtml(task.variant)}", "${escapeHtml(taskFeedbackConfig.variants[task.variant]||task.variant)}")
        content = content.replace("${escapeHtml(task.scenario)}", "${escapeHtml(taskFeedbackConfig.scenarios[task.scenario]?.label||task.scenario)}")
        content = content.replace("FAILED:'拒绝或执行失败'", "FAILED:'拒绝或失败 · 查看原因'")
        # Adapt original anchors before inserting helper code containing similar DOM operations.
        content = _replace(content, 'const taskLabels =', script + '\nconst taskLabels =')
        content = _replace(content, 'initV2();', "$('scenario').addEventListener('change',updateScenarioHelp);\n$('run-valid-example').addEventListener('click',()=>{if($('run-synthetic').disabled)return;$('scenario').value='valid';updateScenarioHelp();submitTask();});\ninitV2();")
    elif name == 'styles.css':
        content += ('\n.validation-expected{background:var(--amber-soft);color:#684414;padding:16px;border-radius:8px}'
                    '.model-help{margin:16px 0}.model-help p{font-size:14px}'
                    '#run-valid-example{min-height:44px}#scenario-help{min-height:24px}\n')
    return content


FEEDBACK_JS = r"""
const taskFeedbackConfig=__CONFIG__;
function expectedTaskRejection(task){
  const rule=taskFeedbackConfig.scenarios[task.scenario],error=task.error;
  return task.input_mode==='SYNTHETIC_TEST'&&Object.hasOwn(taskFeedbackConfig.variants,task.variant)&&task.status==='FAILED'&&task.result===null&&!!error&&!!rule?.code&&error.code===rule.code&&Number.isInteger(error.upstream_http_status)&&error.upstream_http_status===rule.http;
}
function updateScenarioHelp(){
  $('scenario-help').textContent=taskFeedbackConfig.scenarios[$('scenario').value]?.help||'请选择维护方已绑定的案例。';
}
function setScenarioOptions(available){
  const option=key=>`<option value="${escapeHtml(key)}">${escapeHtml(taskFeedbackConfig.scenarios[key]?.label||available[key])}</option>`;
  $('scenario').innerHTML='<optgroup label="正常计算">'+(Object.hasOwn(available,'valid')?option('valid'):'')+'</optgroup><optgroup label="校验测试 · 预期无预测">'+Object.keys(available).filter(key=>key!=='valid').map(option).join('')+'</optgroup>';
  updateScenarioHelp();
}
function renderTaskFeedback(task,expected){
  const rule=taskFeedbackConfig.scenarios[task.scenario];
  $('run-valid-example').hidden=!['FAILED','CANCELLED'].includes(task.status);
  const reason=expected?rule.help:task.error?'任务未得到有效预测。请保留错误代码检查服务或输入；不要将失败解释为零风险。':'';
  $('task-state').innerHTML=`<p class="task-state-label">${escapeHtml(taskFeedbackConfig.variants[task.variant]||task.variant)} · ${escapeHtml(rule?.label||task.scenario)}</p>${reason?`<p class="${expected?'validation-expected':'error'}">${escapeHtml(reason)}</p>`:''}<details><summary>任务与错误技术信息</summary><p class="mono">${escapeHtml(task.id)}</p><p>创建 ${escapeHtml(task.created_at_utc)} · 更新 ${escapeHtml(task.updated_at_utc)}</p><p>存储状态 ${escapeHtml(task.status)}${task.error?' · '+escapeHtml(task.error.code)+' · HTTP '+escapeHtml(task.error.upstream_http_status??'未返回'):''}</p></details>`;
}
function showTaskFeedback(task,expected){
  status('synthetic-status',expected?'校验测试符合预期：错误输入已被拦截，没有生成预测。可点击“运行正常示例”查看模型计算。':task.status==='FAILED'?'任务拒绝或执行失败，没有可用预测。请查看错误代码后处理。':taskLabels[task.status]||task.status,task.status==='FAILED'&&!expected);
  $('synthetic-status').classList.toggle('validation-expected',expected);
}
"""
