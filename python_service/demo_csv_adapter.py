"""Optional course CSV preview on the maintained demo; no app or model starts."""
from .course_csv import preview_csv, CsvPreviewError

PATH = '/api/system/course-csv-preview'


def serve_course_csv(handler, parsed, *, write=False, trace=''):
    if parsed.path != PATH:
        return False
    from_origin = f'http://127.0.0.1:{handler.server.server_port}'
    if not write:
        raise CsvPreviewError('POST_REQUIRED')
    if parsed.query:
        raise CsvPreviewError('QUERY')
    if handler.headers.get_all('Origin') != [from_origin]:
        raise CsvPreviewError('ORIGIN_REQUIRED')
    # Existing maintained public JSON parser supplies the fixed 32768-byte cap,
    # unique framing/JSON keys and nonfinite rejection before this pure module.
    payload = handler.read_course_csv_json()
    handler.reply(preview_csv(payload))
    return True


def enhance_csv_asset(name, content):
    if name == 'index.html':
        anchor = '<section id="import-preview"'
        if content.count(anchor) != 1:
            raise ValueError('CSV_UI_INCOMPATIBLE')
        end = content.index('</section>', content.index(anchor)) + len('</section>')
        content = content[:end] + HTML + content[end:]
    elif name == 'app.js':
        content += JS
    elif name == 'styles.css':
        content += '\n.course-csv-form{display:grid;gap:16px}.course-csv-actions{display:flex;flex-wrap:wrap;gap:10px}.course-csv-form textarea{width:100%;max-width:100%;box-sizing:border-box;min-height:130px}.course-csv-form label{display:block;margin-bottom:6px}.course-csv-form input,.course-csv-form select,.course-csv-actions button{min-height:44px}#course-csv-result{overflow-wrap:anywhere}#course-csv-summary:focus{outline:3px solid var(--blue);outline-offset:4px}.course-csv-form [aria-invalid="true"]{border:2px solid #a72a36}\n'
    return content


HTML = '''
<section id="course-csv-preview" class="panel" aria-labelledby="course-csv-title">
<div class="section-head"><div><div class="eyebrow">COURSE CSV PREFLIGHT</div><h2 id="course-csv-title">课程三表关联预检</h2>
<p>按课程档案、访视、特征三张CSV核对字段与关联，再检查每份档案的质量门槛。这里只预检，不确认入库、不运行模型。</p></div></div>
<details><summary>展开三表输入与质量检查</summary><form id="course-csv-form" class="course-csv-form">
<p class="help">仅粘贴明确构造的DEMO编号数据。空数值单元格表示缺失；日期、单位和字段顺序按各表表头，不自动猜测。此处不能接收真实病例。</p>
<div><label for="course-csv-version">合成数据版本</label><input id="course-csv-version" value="demo-csv-check" maxlength="100" required></div>
<div><label for="course-csv-window">预警窗口</label><select id="course-csv-window"><option value="24">24个月（当前规则支持）</option><option value="12">12个月（应质量阻断）</option></select></div>
<div><label for="course-csv-subjects">档案表 subjects</label><textarea id="course-csv-subjects" rows="4" maxlength="30000" spellcheck="false" aria-describedby="course-csv-subjects-error" required></textarea><p id="course-csv-subjects-error" class="help"></p></div>
<div><label for="course-csv-visits">访视表 visits</label><textarea id="course-csv-visits" rows="4" maxlength="30000" spellcheck="false" aria-describedby="course-csv-visits-error" required></textarea><p id="course-csv-visits-error" class="help"></p></div>
<div><label for="course-csv-features">特征表 features</label><textarea id="course-csv-features" rows="5" maxlength="30000" spellcheck="false" aria-describedby="course-csv-features-error" required></textarea><p id="course-csv-features-error" class="help"></p></div>
<div class="course-csv-actions"><button id="course-csv-valid" class="button secondary" type="button">填入正常合成三表</button><button id="course-csv-invalid" class="button secondary" type="button">填入错误行示例</button><button id="course-csv-submit" class="button" type="submit">运行三表预检</button></div></form></details>
<div id="course-csv-summary" role="status" aria-live="polite" tabindex="-1">尚未预检。展开输入后运行检查。</div><div id="course-csv-result"></div>
</section>
'''

JS = r'''
const courseCsvTables=['subjects','visits','features'];let courseCsvRequest=0;
const courseCsvExample={subjects:'subjectCode,alias,status\nDEMO-CSV,构造档案,ACTIVE\n',visits:'subjectCode,visitCode,visitDate,mmse,moca,cdrSb\nDEMO-CSV,BL,2025-01-01,28,25,0.5\nDEMO-CSV,M12,2026-01-01,25,22,1.5\n',features:'subjectCode,featureName,featureValue,recordedAt,unit\nDEMO-CSV,APOE_E4_COUNT,1,2025-01-01,count\nDEMO-CSV,MRI_HIPPOCAMPUS_L,0.35,2025-01-01,normalized\nDEMO-CSV,MRI_HIPPOCAMPUS_R,0.36,2025-01-01,normalized\n'};
function clearCourseCsv(){courseCsvRequest++;$('course-csv-result').replaceChildren();$('course-csv-summary').textContent='输入已更新，尚未预检。';for(const table of courseCsvTables){$('course-csv-'+table).removeAttribute('aria-invalid');$('course-csv-'+table+'-error').textContent='';}}
function fillCourseCsv(invalid=false){for(const table of courseCsvTables)$('course-csv-'+table).value=courseCsvExample[table];if(invalid)$('course-csv-features').value=courseCsvExample.features.replace('DEMO-CSV,APOE','DEMO-ORPHAN,APOE').replace(',normalized',',mm3');clearCourseCsv();}
for(const id of ['version','window',...courseCsvTables])$('course-csv-'+id).addEventListener('input',clearCourseCsv);
$('course-csv-valid').addEventListener('click',()=>fillCourseCsv());$('course-csv-invalid').addEventListener('click',()=>fillCourseCsv(true));fillCourseCsv();
$('course-csv-form').addEventListener('submit',async event=>{
  event.preventDefault();clearCourseCsv();const request=courseCsvRequest,button=$('course-csv-submit');button.disabled=true;$('course-csv-summary').textContent='正在核对三表字段、关联与质量门槛…';
  const payload={input_mode:'SYNTHETIC_TEST',dataVersion:$('course-csv-version').value,predictionWindowMonths:Number($('course-csv-window').value),tables:Object.fromEntries(courseCsvTables.map(table=>[table,$('course-csv-'+table).value]))};
  try{
    const response=await fetch('/api/system/course-csv-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    if(!response.ok)throw new Error('PREVIEW_REJECTED');const body=await response.json();if(request!==courseCsvRequest)return;
    if(body.scope!=='COURSE_SYNTHETIC_PREVIEW'||body.persisted!==false||body.modelExecuted!==false||body.predictionProduced!==false||body.commitSupported!==false)throw new Error('PREVIEW_SCOPE');
    const invalid=body.status==='INVALID',counts=body.qualityCounts;
    $('course-csv-summary').textContent=invalid?`预检未通过：${body.errorCount} 项字段或关联错误。没有导入或生成预测。`:`三表预检完成：${body.rows.subjects} 份档案 / ${body.rows.visits} 次访视 / ${body.rows.features} 条特征；质量 PASS ${counts.PASS} / WARN ${counts.WARN} / BLOCKED ${counts.BLOCKED}。没有导入或生成预测。`;
    for(const table of courseCsvTables){const errors=body.issues.filter(item=>item.table===table&&item.severity==='ERROR');if(errors.length){$('course-csv-'+table).setAttribute('aria-invalid','true');$('course-csv-'+table+'-error').textContent=errors.map(item=>`第${item.row}行 ${item.field}：${item.code}`).join('；');}}
    const issues=body.issues.map(item=>`<tr><td><a href="#course-csv-${escapeHtml(item.table)}">${escapeHtml(item.table)} 第${item.row}行</a></td><td>${escapeHtml(item.field)}</td><td>${escapeHtml(item.severity)} · ${escapeHtml(item.code)}</td></tr>`).join('');
    const subjects=body.subjects.map(item=>`<tr><td>${escapeHtml(item.subjectCode)}</td><td>${escapeHtml(item.qualityStatus)}</td><td>${escapeHtml(item.indexDate??'未知')}</td><td>${escapeHtml([...item.blockingReasons,...item.warningCodes].join('；')||'字段齐全，仍不代表临床有效')}</td></tr>`).join('');
    $('course-csv-result').innerHTML=(issues?`<div class="table-scroll" tabindex="0" role="region" aria-label="三表错误行与告警"><table><thead><tr><th>表与CSV物理行</th><th>字段</th><th>问题代码</th></tr></thead><tbody>${issues}</tbody></table></div>`:'')+(body.issuesTruncated?'<p>问题较多，仅显示前200项；完整错误总数见上方。请修正后重新预检。</p>':'')+(subjects?`<div class="table-scroll" tabindex="0" role="region" aria-label="档案质量门槛"><table><thead><tr><th>合成档案</th><th>质量状态</th><th>索引访视日</th><th>原因/缺失</th></tr></thead><tbody>${subjects}</tbody></table></div>`:'')+`<p class="help">预检规则 ${escapeHtml(body.previewRuleVersion)} / 质量规则 ${escapeHtml(body.qualityRuleVersion)}。BLOCKED没有可用预测；PASS只表示当前规则未阻断。来源时间仅按CSV声明检查，未认证历史可获得性。</p>`;
    if(invalid)$('course-csv-summary').focus();
  }catch{if(request===courseCsvRequest){$('course-csv-summary').textContent='预检请求未通过或服务暂不可用。请检查合成声明、版本、三表总计不超过30000 UTF-8字节；修改后重试。没有导入或生成预测。';$('course-csv-summary').focus();}}
  finally{button.disabled=false;}
});
'''
