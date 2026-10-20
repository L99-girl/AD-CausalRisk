"""Read-only pinned course-example reports on the maintained demo host."""
import hashlib
from pathlib import Path
from urllib.parse import parse_qs
from .course_protocol import decode_json
from .course_report import build_course_report, render_course_html, CourseReportError
from .demo_report_adapter import ReportRequestError, require
from .research_report import STYLESHEET_PATH

PATH = '/api/system/reports/course-example'
EXAMPLES = Path(__file__).resolve().parents[1]/'contracts/examples'
PINS = {'deepagent-v1.request.example.json': 'c5ca67aff9ed46baeb05b5163fd06135876c15905e91f1e327e58251b5043e85',
        'deepagent-v1.response.example.json': '6f8c6132714fb9342d24020aa7ea7153c75bb69f5a8c6e6fdb3bfad8594e3a53'}


def example_pair():
    values = []
    try:
        for name, digest in PINS.items():
            raw = (EXAMPLES/name).read_bytes()
            require(hashlib.sha256(raw).hexdigest() == digest, 503, 'COURSE_EXAMPLE_CHANGED')
            values.append(decode_json(raw))
    except ReportRequestError:
        raise
    except (OSError, ValueError):
        raise ReportRequestError(503, 'COURSE_EXAMPLE_UNAVAILABLE') from None
    return tuple(values)


def serve_course_report(handler, parsed, *, write=False, trace=''):
    if parsed.path != PATH: return False
    require(not write, 405, 'GET_REQUIRED')
    try: params = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=2)
    except ValueError: raise ReportRequestError(400, 'QUERY') from None
    require(set(params) <= {'audience', 'format'} and all(len(value) == 1 for value in params.values()), 400, 'QUERY')
    audience, media = params.get('audience', ['research'])[0], params.get('format', ['html'])[0]
    require(audience in ('research','teaching') and media in ('html','json'), 400, 'QUERY')
    request, result = example_pair()
    try:
        if media == 'json':
            report = build_course_report(request, result, audience=audience)
            handler.reply({**report, 'reportOrigin': 'PINNED_CONTRACT_EXAMPLE_NOT_LIVE_RUN', 'liveServiceProbed': False})
        else:
            html = render_course_html(request, result, audience=audience, stylesheet_href=STYLESHEET_PATH)
            html = html.replace('<h1>课程合成演示报告</h1>', '<h1>课程合成报告示例</h1><p class="scope">原契约静态构造示例，非当前运行任务；没有连接8091、执行模型或读取真实记录。</p>')
            handler.reply(html.encode('utf-8'), media='text/html; charset=utf-8')
    except CourseReportError:
        raise ReportRequestError(503, 'COURSE_EXAMPLE_INVALID') from None
    return True


def enhance_course_report_asset(name, content):
    if name == 'index.html':
        marker = '<section id="course-csv-preview"'
        require(content.count(marker) == 1, 503, 'COURSE_REPORT_UI_INCOMPATIBLE')
        content = content.replace(marker, HTML + marker)
    return content


HTML = '''<section class="panel" id="course-report-example" aria-labelledby="course-report-title">
<div class="section-head"><div><div class="eyebrow">COURSE REPORT</div><h2 id="course-report-title">课程合成报告示例</h2>
<p>原契约静态构造请求与响应的报告预览，不是当前运行任务。只读取示例，不启动8091、不运行模型或导入数据。教学版不是患者权限视图。</p></div></div>
<div class="task-actions"><a class="button secondary" href="/api/system/reports/course-example?audience=research" target="_blank" rel="noopener">研究版示例与打印</a>
<a class="button secondary" href="/api/system/reports/course-example?audience=teaching" target="_blank" rel="noopener">教学版示例与打印</a>
<a class="button secondary" href="/api/system/reports/course-example?format=json" target="_blank" rel="noopener">查看示例JSON</a></div>
<p class="help">浏览器打印可另存PDF。实际课程结果可用Python离线报告工具处理；业务任务、授权与导出审计仍由Java实现。</p></section>'''
