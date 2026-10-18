"""Read-only acceptance metadata and optional existing-demo presentation."""
from datetime import datetime

PATH='/api/system/course-contract-check'
REQUIRED_CHECKS={'all_100_fixture_profiles_request_response_schema_and_semantics',
                 'changed_request_same_run_409_keeps_original_binding_and_result',
                 '32_early_rejections_deliver_full_error_json_without_run_execution',
                 'unexpected_execution_failure_is_safe_500_and_not_cached',
                 'real_request_body_read_timeout_returns_schema_valid_408',
                 'real_run_capacity_503_keeps_previous_results'}


def summarize_acceptance(record,current_sources):
    def check(condition):
        if not condition:raise ValueError('INVALID_COURSE_ACCEPTANCE_RECORD')
    summary={'status':'NOT_RUN','checked_at_utc':None,'checks_passed':None,'fixture_profiles':None,
             'repeated_early_rejections':None,'independent_schema_observations':None,'source_matches':False,
             'course_service_currently_probed':False,'clinical_validity_assessed':False,'java_integration_validated':False}
    if record is None:return summary
    summary['status']='INVALID'
    try:
        when=datetime.fromisoformat(record['checked_at_utc'].replace('Z','+00:00'))
        check(when.utcoffset() is not None)
        check(record['status']=='PASSED' and record['mode']=='COURSE_SYNTHETIC')
        check(record['contract_version']=='deepagent-v1' and record['http_api_version']=='course-agent-http-v1')
        checks=record['checks']
        check(isinstance(checks,list) and len(checks)==len(set(checks))==22 and REQUIRED_CHECKS<=set(checks))
        check(type(record['passed']) is int and record['passed']==len(checks))
        check(type(record['fixture_profiles']) is int and record['fixture_profiles']==100)
        check(type(record['repeated_early_rejections']) is int and record['repeated_early_rejections']==32)
        check(record['owned_server_fault_checks'] is True and record['formal_schema_validated'] is True)
        check(type(record['independent_schema_observations']) is int and record['independent_schema_observations']>0)
        check(record['original_api_paths_and_fields_changed'] is record['scoring_formula_changed'] is False)
        check(record['research_or_private_records_read'] is record['java_integration_validated'] is False)
        check(type(record['new_fits']) is int and record['new_fits']==0)
        check(isinstance(record['source_sha256'],dict) and bool(record['source_sha256']))
        summary['checked_at_utc']=record['checked_at_utc']
        if record['source_sha256']!=current_sources:
            summary['status']='STALE';return summary
        summary.update(status='VERIFIED',checks_passed=record['passed'],fixture_profiles=record['fixture_profiles'],
                       repeated_early_rejections=record['repeated_early_rejections'],
                       independent_schema_observations=record['independent_schema_observations'],source_matches=True)
        return summary
    except (AssertionError,KeyError,TypeError,ValueError,AttributeError):return summary


def enhance_acceptance_asset(name,content):
    if name=='index.html':
        marker='<div id="evidence-cards" class="evidence-grid"></div>'
        if content.count(marker)!=1:raise ValueError('COURSE_CHECK_UI_INCOMPATIBLE')
        content=content.replace(marker,marker+'<div class="note course-contract-note"><div class="sub-head">'
            '<h3>课程接口验收记录</h3><button id="refresh-course-contract" type="button" class="button secondary">重新读取记录</button></div>'
            '<p id="course-contract-status" role="status" aria-live="polite">正在读取接口验收记录…</p>'
            '<p class="help">核对已完成的合成接口验收及当前源码；此处不启动课程服务或重跑测试。课程服务当前是否运行、Java接入和临床精度另行验收。</p></div>')
    elif name=='app.js':
        content+=r"""
async function loadCourseContractRecord(){
  const button=$('refresh-course-contract'),target=$('course-contract-status');button.disabled=true;
  target.textContent='正在核对接口验收记录与当前源码…';target.classList.remove('error');
  try{
    const response=await fetch('/api/system/course-contract-check',{cache:'no-store'});
    if(!response.ok)throw new Error('READ_FAILED');const data=await response.json();
    if(data.status==='VERIFIED'&&data.source_matches===true){target.textContent=`已核验 · ${data.checks_passed} 项接口验收 · ${data.fixture_profiles} 份合成档案 · ${data.repeated_early_rejections} 次提前拒绝 · 记录时间 ${new Date(data.checked_at_utc).toLocaleString('zh-CN')}`;}
    else if(data.status==='STALE')target.textContent='源码已更新，原接口验收记录已过期。需运行课程接口验收后重新读取。';
    else if(data.status==='NOT_RUN')target.textContent='尚无接口验收记录。请先运行课程接口验收，再重新读取。';
    else{target.textContent='接口验收记录未通过核对；请检查验收输出。';target.classList.add('error');}
  }catch{target.textContent='暂时无法读取接口验收记录；可重新读取或检查本机服务。';target.classList.add('error');}
  finally{button.disabled=false;}
}
$('refresh-course-contract').addEventListener('click',loadCourseContractRecord);loadCourseContractRecord();
"""
    elif name=='styles.css':content+='\n.course-contract-note{margin-top:20px}.course-contract-note .sub-head{flex-wrap:wrap;gap:12px}.course-contract-note .button{min-height:44px}\n'
    return content
