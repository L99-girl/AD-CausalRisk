"""Optional same-host timeline route/asset adapter; never starts an application."""
import re
from urllib.parse import parse_qs
from .visit_timeline import build_timeline, TimelineError, METRICS

PREFIX = '/api/system/public-timelines/'


class TimelineRequestError(ValueError):
    def __init__(self, status, code):
        self.status, self.code = status, code
        self.message = '公开实测访视请求未通过检查；没有生成预测或补值'
        super().__init__(code)


def require(condition, status, code):
    if not condition:raise TimelineRequestError(status, code)


def serve_timeline(handler, parsed, *, write=False, trace=''):
    if write or not parsed.path.startswith(PREFIX):return False
    require(handler.server.public_components is not None, 503, 'PUBLIC_SERVICE_UNAVAILABLE')
    identifier = parsed.path.removeprefix(PREFIX)
    require(re.fullmatch(r'OAS2_[0-9]{4}', identifier) is not None, 404, 'NOT_FOUND')
    try:params = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=1)
    except ValueError:raise TimelineRequestError(400, 'QUERY') from None
    require(set(params) <= {'metric'} and all(len(value) == 1 for value in params.values()), 400, 'QUERY')
    require(params.get('metric', ['mmse'])[0] in METRICS, 400, 'METRIC')
    handler.server.binding.verify()
    store = handler.server.store
    store.source_blobs()  # Original public-derived hashes, not a clinical raw-table scan.
    try:report = store.report(identifier, trace)
    except KeyError:raise TimelineRequestError(404, 'NOT_FOUND') from None
    try:series = build_timeline(report['subject']['visits'], params.get('metric', ['mmse'])[0])
    except TimelineError as error:raise TimelineRequestError(400, str(error)) from None
    handler.reply({'scope': 'PUBLIC_OASIS_DERIVED_OBSERVATIONS', 'subject_id': identifier,
                   'data_version': report['data_version'], 'prediction_available': False, 'series': series})
    return True


def replace_one(content, old, new):
    if content.count(old) != 1:raise ValueError('TIMELINE_UI_INCOMPATIBLE')
    return content.replace(old, new)


def enhance_timeline_asset(name, content):
    if name == 'index.html':
        content = replace_one(content, '<div id="timeline"></div>',
            '<div class="timeline-controls"><label>实测指标 <select id="timeline-metric">'
            '<option value="mmse">MMSE / 分</option><option value="cdr">Global CDR / 分</option>'
            '<option value="nwbv">nWBV / 比例</option></select></label>'
            '<label class="timeline-connect"><input id="timeline-connect" type="checkbox">显示访视间辅助连线</label></div>'
            '<p id="timeline-summary" role="status" aria-live="polite"></p><div id="timeline-stats" class="timeline-stats"></div>'
            '<div id="timeline"></div><p id="timeline-note" class="help">圆点是实测值。辅助虚线不代表期间每天的数值；缺失不补零、不插值，不跨缺失访视连线。</p>'
            '<p id="timeline-point" class="note" aria-live="polite">可点击或用键盘聚焦圆点查看访视数值；完整原始值见下表。</p>')
        content = content.replace('<h3>实测 MMSE 与访视记录</h3>', '<h3>实测指标与访视记录</h3>')
    elif name == 'app.js':
        content = replace_one(content, 'fmt(visit.nwbv, 4)', 'fmt(visit.nwbv, 6)')
        start, end = content.index('function renderTimeline(visits) {'), content.index('function renderGraph() {')
        content = content[:start] + TIMELINE_JS + '\n' + content[end:]
        content += "\n$('timeline-metric').addEventListener('change',()=>renderTimeline());$('timeline-connect').addEventListener('change',()=>{if(timelineSeries)drawObservedTimeline(timelineSeries);});\n"
    elif name == 'styles.css':
        content += ('\n.timeline-controls{display:flex;flex-wrap:wrap;gap:20px;align-items:center;margin:16px 0}'
                    '.timeline-controls label{display:flex;align-items:center;gap:8px;min-height:44px}'
                    '.timeline-controls input{width:20px;height:20px}.timeline-stats{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}'
                    '.timeline-stats>div{padding:12px 16px;background:var(--blue-soft);border-radius:8px;flex:1;min-width:120px}'
                    '.timeline-stats span{display:block;font-size:12px;color:var(--muted)}.timeline-stats strong{font-size:20px}'
                    '#timeline-point{overflow-wrap:anywhere}#timeline circle:focus{stroke:var(--amber);stroke-width:3}'
                    '#timeline svg{width:100%;height:auto;display:block}.timeline-controls select{min-height:44px}\n')
    return content


TIMELINE_JS = r"""
let timelineRequest=0,timelineSeries=null;
async function renderTimeline(){
  const request=++timelineRequest,detailRequest=state.detailRequest,subject=state.report?.subject?.id,metric=$('timeline-metric').value;
  timelineSeries=null;$('timeline').replaceChildren();$('timeline-stats').replaceChildren();$('timeline-summary').textContent='正在核验实测访视…';$('timeline-point').textContent='完整实测值见下方访视表。';
  if(!subject)return;
  try{
    const response=await fetch('/api/system/public-timelines/'+encodeURIComponent(subject)+'?metric='+encodeURIComponent(metric),{cache:'no-store'});
    if(!response.ok)throw new Error('TIMELINE_UNAVAILABLE');const body=await response.json();
    if(request!==timelineRequest||detailRequest!==state.detailRequest||state.report?.subject?.id!==subject)return;
    if(body.subject_id!==subject||body.scope!=='PUBLIC_OASIS_DERIVED_OBSERVATIONS'||body.prediction_available!==false||body.series.metric!==metric)throw new Error('TIMELINE_SCOPE');
    timelineSeries=body.series;drawObservedTimeline(timelineSeries);
  }catch(error){if(request===timelineRequest&&detailRequest===state.detailRequest)$('timeline-summary').textContent='实测图暂不可用；请核对服务和来源，下方原始访视表保留。';}
}
function drawObservedTimeline(series){
  const points=series.points,format=value=>value==null?'未提供':Number(value).toLocaleString('zh-CN',{maximumFractionDigits:series.digits});
  const interval=series.span_days==null?'时间未知':`跨 ${series.span_days} 天`;
  $('timeline-summary').textContent=`${series.total_visits} 次访视 · ${points.length} 个有效实测点 · ${series.missing_count} 次缺失 · ${series.invalid_count} 次异常 · ${interval}。${points.length<4?'观测较少，无法显示连续变化过程。':''}${series.repeated_days.length?'存在同日重复记录，辅助线已避开这些日期。':''}`;
  const values=[['首次有效实测',points[0]?.value],['最后有效实测',points.at(-1)?.value],['首末实测差值',series.net_observed_change]];
  $('timeline-stats').innerHTML=values.map(([label,value])=>`<div><span>${escapeHtml(label)} / ${escapeHtml(series.unit)}</span><strong>${escapeHtml(format(value))}</strong></div>`).join('');
  if(!points.length){$('timeline').innerHTML='<p class="empty">此指标没有可绘制的有效实测值；未补零或生成预测。</p>';return;}
  const width=Math.max(240,$('timeline').clientWidth-24),height=240,left=42,right=30,top=40,bottom=40;
  const minimumDay=series.start_day??0,maximumDay=series.end_day??minimumDay,span=Math.max(1,maximumDay-minimumDay);
  const x=day=>minimumDay===maximumDay?width/2:left+(day-minimumDay)/span*(width-left-right);
  const y=value=>height-bottom-(value-series.minimum)/(series.maximum-series.minimum)*(height-top-bottom);
  const ticks=[0,1,2,3].map(i=>{const value=series.minimum+(series.maximum-series.minimum)*i/3;return `<line x1="${left}" x2="${width-right}" y1="${y(value)}" y2="${y(value)}" stroke="#d9e0eb"/><text x="${left-8}" y="${y(value)+4}" text-anchor="end" class="chart-label">${Number(value.toFixed(2))}</text>`;}).join('');
  const byVisit=new Map(points.map(point=>[point.visit,point]));
  const lines=$('timeline-connect').checked?series.connectors.map(pair=>{const a=byVisit.get(pair.from_visit),b=byVisit.get(pair.to_visit);return `<line class="observation-guide" x1="${x(a.day)}" y1="${y(a.value)}" x2="${x(b.day)}" y2="${y(b.value)}" stroke="#7183a7" stroke-dasharray="5 5"><title>相邻实测点辅助连线；期间未测量，不代表插值或预测</title></line>`;}).join(''):'';
  const dots=points.map((point,index)=>{const text=`V${point.visit} · 第${point.day}天 · ${series.label} ${format(point.value)} ${series.unit}`,label=points.length<=6||index===0||index===points.length-1,first=index===0,last=index===points.length-1;return `<circle data-visit="${point.visit}" cx="${x(point.day)}" cy="${y(point.value)}" r="6" fill="#2348a5" tabindex="0" role="img" aria-label="${escapeHtml(text)}"><title>${escapeHtml(text)}</title></circle>${label?`<text x="${x(point.day)+(first?10:last?-10:0)}" y="${y(point.value)-13}" text-anchor="${first?'start':last?'end':'middle'}" class="chart-label">${escapeHtml(format(point.value))}</text>`:''}`;}).join('');
  const endpoints=minimumDay===maximumDay?`<text x="${width/2}" y="${height-12}" text-anchor="middle" class="chart-label">第 ${minimumDay} 天</text>`:`<text x="${left}" y="${height-12}" class="chart-label">${minimumDay} 天</text><text x="${width-right}" y="${height-12}" text-anchor="end" class="chart-label">${maximumDay} 天</text>`;
  $('timeline').innerHTML=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(series.label)}实测访视图；${points.length}个有效观测；辅助线不是连续测量或预测"><title>${escapeHtml(series.label)}实测值，未补值或预测</title>${ticks}${lines}${dots}${endpoints}</svg>`;
  $('timeline-point').textContent='点击或用键盘聚焦圆点查看实测日期与数值；完整值见下方访视表。';
  for(const dot of $('timeline').querySelectorAll('circle'))for(const event of ['focus','click'])dot.addEventListener(event,()=>{$('timeline-point').textContent=dot.getAttribute('aria-label');});
}
"""
