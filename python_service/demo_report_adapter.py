"""Thin optional integration for the existing Python demonstration application.

The application provides its current task store, binding checks and HTTP reply.
This module never starts a server or implements Java business report APIs.
"""
import re
from urllib.parse import parse_qs
from .research_report import build_report, render_html, ReportError, REPORT_STYLE, STYLESHEET_PATH

PREFIX = '/api/system/reports/synthetic/'


class ReportRequestError(ValueError):
    def __init__(self, status, code):
        self.status, self.code = status, code
        self.message = '合成报告请求未通过检查；仅支持已完成的合成任务'
        super().__init__(code)


def require(condition, status, code):
    if not condition:
        raise ReportRequestError(status, code)


def serve_report(handler, parsed, *, write=False, trace=''):
    """Run after the application's original loopback Host/Origin authorization."""
    if not write and parsed.path == STYLESHEET_PATH:
        require(not parsed.query, 400, 'QUERY')
        handler.reply(REPORT_STYLE.encode('utf-8'), media='text/css; charset=utf-8')
        return True
    if write or not parsed.path.startswith(PREFIX):
        return False
    require(handler.server.public_components is not None, 503, 'PUBLIC_SERVICE_UNAVAILABLE')
    identifier = parsed.path.removeprefix(PREFIX)
    require(re.fullmatch(r'wb2-[a-f0-9]{32}', identifier) is not None, 404, 'NOT_FOUND')
    try:
        params = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=2)
    except ValueError:
        raise ReportRequestError(400, 'QUERY') from None
    require(set(params) <= {'audience', 'format'} and all(len(value) == 1 for value in params.values()), 400, 'QUERY')
    audience = params.get('audience', ['research'])[0]
    media = params.get('format', ['html'])[0]
    require(audience in {'research', 'teaching'} and media in {'html', 'json'}, 400, 'QUERY')
    handler.server.binding.verify()
    task = handler.server.tasks.get(identifier)
    try:
        result = render_html(task, audience=audience, stylesheet_href=STYLESHEET_PATH) if media == 'html' else build_report(task, audience=audience)
    except ReportError as error:
        raise ReportRequestError(422, error.code) from None
    handler.server.audit('SYNTHETIC_REPORT_RENDERED', trace)
    if media == 'html':
        handler.reply(result.encode('utf-8'), media='text/html; charset=utf-8')
    else:
        handler.reply(result)
    return True


def enhance_asset(name, content):
    """Extend current public task controls without rewriting its protected source."""
    if name == 'index.html':
        marker = '<a id="download-task"'
        require(content.count(marker) == 1, 503, 'REPORT_UI_INCOMPATIBLE')
        content = content.replace(marker, '<a id="preview-report" class="button secondary" target="_blank" rel="noopener" hidden>研究版预览与打印</a><a id="teaching-report" class="button secondary" target="_blank" rel="noopener" hidden>教学版报告</a>' + marker)
    elif name == 'app.js':
        marker = "$('download-task').href=V2+'tasks/'+task.id+'/report';"
        require(content.count(marker) == 1, 503, 'REPORT_UI_INCOMPATIBLE')
        content = content.replace("$('cancel-task').hidden=true;$('download-task').hidden=true;", "$('cancel-task').hidden=true;$('download-task').hidden=true;$('preview-report').hidden=true;$('teaching-report').hidden=true;")
        content = content.replace(marker, marker + "\n  for(const [id,audience] of [['preview-report','research'],['teaching-report','teaching']]){const link=$(id);link.hidden=task.status!=='COMPLETED'||!task.result;link.href='/api/system/reports/synthetic/'+encodeURIComponent(task.id)+'?audience='+audience+'&format=html';}")
    elif name == 'styles.css':
        content += '\n.task-actions{flex-wrap:wrap;gap:8px}.task-actions .button{min-height:44px}\n'
    return content
