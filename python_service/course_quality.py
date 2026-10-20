"""Explain declared synthetic CSV quality, without exposing measurements or scoring.

The original preview stays available unchanged. This optional review adds counts,
physical source locators and a dictionary, not clinical availability or provenance.
"""
import csv
from datetime import date
import io
from .course_csv import prepare_csv, TABLES, located_rows
from .course_protocol import CourseContract

REPORT_VERSION = 'course-quality-review-v1'
COGNITION = ('mmse', 'moca', 'cdrSb')
FEATURE_NAMES = ('APOE_E4_COUNT', 'MRI_HIPPOCAMPUS_L', 'MRI_HIPPOCAMPUS_R')
ISSUE_GUIDANCE = {
    'NUL_CHARACTER': '表中含有空字节，不能作为正常CSV文本处理。',
    'HEADER_EXACT_REQUIRED': '表头字段或顺序不符；按字段字典核对，不自动猜列。',
    'ROW_LIMIT': '该表记录数超过预检上限，请缩小批次。',
    'COLUMN_COUNT': '该记录列数不符；检查逗号、引号和换行。',
    'SYNTHETIC_ALIAS_REQUIRED': '档案编号必须符合DEMO格式；不能提交真实病例编号。',
    'ALIAS_REQUIRED_MAX_100': '构造别名不能为空，且最多100字符。',
    'SUBJECT_STATUS': '档案状态只接受ACTIVE或ARCHIVED。',
    'DATE_INVALID_OR_FUTURE': '日期须为有效YYYY-MM-DD且不晚于今天；不要自动猜测或改写来源日。',
    'VISIT_CODE': '访视编号不能为空，且最多50字符。',
    'FEATURE_NOT_ALLOWED': '该特征不在原课程三特征白名单中；新增字段需要先协调契约。',
    'UNIT_MISMATCH': '单位与特征不符；APOE用count，MRI比例用normalized，不能直接改标签代替换算。',
    'NUMBER_INVALID_OR_RANGE': '数值格式或范围不符；空单元格才表示缺失，0不是缺失。',
    'CSV_SYNTAX': 'CSV引号或记录结构不完整，请核对原始文本。',
    'SUBJECTS_REQUIRED': '档案表须包含至少一份合法构造档案。',
    'DUPLICATE_SUBJECT': '同批档案编号重复，不能静默覆盖。',
    'SUBJECT_NOT_IN_BATCH': '访视或特征关联的档案不在本批档案表中。',
    'DUPLICATE_SUBJECT_VISIT': '同档案的访视编号重复，不能任选一条。',
    'REPEATED_SAME_VALUE': '相同特征同日同值重复；是预检告警，不增加独立观测。',
    'SUBJECT_RECORD_LIMIT': '单档案超过100次访视或500条特征。',
}
RULES = {
    'CORE_COGNITION_MISSING': ('BLOCKED', '最近访视没有可用认知值；不由更早访视补齐。'),
    'AMBIGUOUS_INDEX_VISIT': ('BLOCKED', '最近日期存在多次访视，不能任意选一次。'),
    'CONFLICTING_FEATURE_VALUES': ('BLOCKED', '索引日及以前同特征同日值冲突，不能任选一个。'),
    'UNSUPPORTED_WINDOW': ('BLOCKED', '声明窗口有效，但当前演示规则只支持24个月。'),
    'POST_INDEX_FEATURES_EXCLUDED': ('WARN', '未满足索引日及以前条件的特征被排除；没有索引日时无法进行时序判断。'),
    'MISSING_MODALITIES': ('WARN', '至少一种特征没有索引日及以前的非空观测。'),
    'PARTIAL_COGNITION': ('WARN', '最近访视的部分认知项缺失，不补零。'),
    'REPEATED_SAME_VALUE': ('INFO', '相同特征同日同值重复，按原规则归并；不增加独立观测。'),
}


def field_dictionary():
    """Use the byte-pinned wire schema for Agent fields and explicit CSV rules."""
    contract = CourseContract()
    properties = contract.schemas['AgentRequest']['properties']
    visit = properties['visits']['items']['properties']
    feature = properties['features']['items']['properties']
    labels = {'subjectCode': '合成档案编号', 'alias': '构造别名', 'status': '档案业务状态',
              'visitCode': '访视编号', 'visitDate': '声明访视日', 'mmse': 'MMSE', 'moca': 'MoCA',
              'cdrSb': 'CDR-SB（量表总和，非Global CDR）', 'featureName': '特征名称',
              'featureValue': '特征观测值', 'recordedAt': '声明采集日', 'unit': '特征单位'}
    fields = []
    for table, columns in TABLES.items():
        for name in columns:
            schema = properties['subjectCode'] if name == 'subjectCode' else visit.get(name, {}) if table == 'visits' else feature.get(name, {}) if table == 'features' else {}
            numeric = name in COGNITION or name == 'featureValue'
            rule = ('空单元格表示缺失；0是已观测值。' if numeric else '字段必填，保留原值，不自动修正。')
            if name == 'subjectCode': rule = '必须是DEMO编号，并且关联本批档案；不是来源真实性证明。'
            if name == 'alias': rule = '非空，最多100字符；报告不返回输入别名。'
            if name == 'status': rule = 'ACTIVE或ARCHIVED；不代替Java是否允许评估的业务授权。'
            if name in ('visitDate', 'recordedAt'): rule = 'YYYY-MM-DD且不晚于今天；采集日不认证历史可获得日。'
            if name in COGNITION: rule += '课程范围允许小数，不套用独立研究接口的整数或离散门槛。'
            if name == 'featureValue': rule += 'APOE只接受0/1/2；MRI比例在[0,1]，不作为mm³。'
            if name == 'featureName': rule = '只接受APOE_E4_COUNT、MRI_HIPPOCAMPUS_L、MRI_HIPPOCAMPUS_R。'
            if name == 'unit': rule = 'APOE为count；左右海马均为normalized，不能自动换单位。'
            fields.append({'table': table, 'field': name, 'label': labels[name], 'numeric': numeric,
                           'nullable': numeric, 'minimum': schema.get('minimum'), 'maximum': schema.get('maximum'),
                           'unit': '分' if name in COGNITION else None, 'rule': rule})
    return {'contractSha256': contract.sha256, 'fields': fields,
            'rules': [{'code': code, 'severity': severity, 'message': message} for code, (severity, message) in RULES.items()]}


def _locations(payload):
    """Only called after the original parser accepts the entire batch."""
    rows = {name: [] for name in TABLES}
    for table in TABLES:
        reader = csv.reader(io.StringIO(payload['tables'][table].removeprefix('\ufeff'), newline=''), strict=True)
        next(reader)
        rows[table] = [(line, dict(zip(TABLES[table], cells))) for line, cells in located_rows(reader)]
    return rows


def _ref(table, line, field):
    return {'table': table, 'row': line, 'field': field}


def _subject(request, summary, rows):
    sid = request['subjectCode']
    visits = [(line, row) for line, row in rows['visits'] if row['subjectCode'] == sid]
    features = [(line, row) for line, row in rows['features'] if row['subjectCode'] == sid]
    cutoff = summary['indexDate']
    latest = [(line, row) for line, row in visits if row['visitDate'] == cutoff]
    dates = sorted({row['visitDate'] for _, row in visits})
    ambiguous_days = {day for day in dates if sum(row['visitDate'] == day for _, row in visits) > 1}
    cognition = []
    for field in COGNITION:
        missing = sum(row[field] == '' for _, row in visits)
        cognition.append({'field': field, 'observedCount': len(visits) - missing, 'missingCount': missing,
                          'zeroCount': sum(row[field] != '' and float(row[field]) == 0 for _, row in visits),
                          'indexState': 'NO_VISIT' if not latest else 'AMBIGUOUS' if len(latest) != 1 else 'MISSING' if latest[0][1][field] == '' else 'OBSERVED',
                          'missingSources': [_ref('visits', line, field) for line, row in visits if row[field] == '']})
    coverage = []
    decision_refs = {code: [] for code in RULES}
    for field in FEATURE_NAMES:
        all_rows = [(line, row) for line, row in features if row['featureName'] == field]
        eligible = [(line, row) for line, row in all_rows if cutoff and row['recordedAt'] <= cutoff]
        groups = {}
        for line, row in eligible:
            groups.setdefault(row['recordedAt'], []).append((line, row))
        conflicting = {day for day, group in groups.items() if len({None if r['featureValue'] == '' else float(r['featureValue']) for _, r in group}) > 1}
        repeated = sum(len(group) - len({None if r['featureValue'] == '' else float(r['featureValue']) for _, r in group}) for group in groups.values())
        usable = sorted([(line, row) for line, row in eligible if row['featureValue'] != ''], key=lambda item: item[1]['recordedAt'])
        # Even equal duplicate rows cannot authenticate one unique source record.
        selected_date = usable[-1][1]['recordedAt'] if usable and not conflicting else None
        selected = [_ref('features', line, 'featureValue') for line, row in usable if row['recordedAt'] == selected_date]
        post = [(line, row) for line, row in all_rows if cutoff and row['recordedAt'] > cutoff]
        missing = sum(row['featureValue'] == '' for _, row in all_rows)
        coverage.append({'featureName': field, 'totalRows': len(all_rows), 'observedCount': len(all_rows) - missing,
                         'missingCount': missing, 'zeroCount': sum(row['featureValue'] != '' and float(row['featureValue']) == 0 for _, row in all_rows),
                         'eligibleRows': len(eligible), 'postIndexRows': len(post), 'unplacedRows': len(all_rows) if not cutoff else 0, 'repeatedRows': repeated,
                         'conflictingDays': len(conflicting), 'selectedDate': selected_date, 'selectedSources': selected,
                         'unit': 'count' if field == 'APOE_E4_COUNT' else 'normalized',
                         'availableDate': None, 'historicalAvailabilityVerified': False})
        decision_refs['POST_INDEX_FEATURES_EXCLUDED'] += [_ref('features', line, 'recordedAt') for line, _ in post]
        decision_refs['CONFLICTING_FEATURE_VALUES'] += [_ref('features', line, 'featureValue') for day in sorted(conflicting) for line, _ in groups[day]]
        for group in groups.values():
            values = [None if r['featureValue'] == '' else float(r['featureValue']) for _, r in group]
            decision_refs['REPEATED_SAME_VALUE'] += [_ref('features', line, 'featureValue') for (line, _), value in zip(group, values) if values.count(value) > 1]
    decision_refs['CORE_COGNITION_MISSING'] = [_ref('visits', line, field) for line, _ in latest for field in COGNITION]
    decision_refs['PARTIAL_COGNITION'] = [_ref('visits', line, field) for line, row in latest for field in COGNITION if row[field] == '']
    decision_refs['AMBIGUOUS_INDEX_VISIT'] = [_ref('visits', line, 'visitDate') for line, _ in latest]
    codes = list(dict.fromkeys(summary['blockingReasons'] + summary['warningCodes']))
    if any(row['repeatedRows'] for row in coverage): codes.append('REPEATED_SAME_VALUE')
    # Decision excerpts have an explicit cap and retain the complete source count.
    decisions = [{'code': code, 'severity': RULES[code][0], 'message': RULES[code][1],
                  'sourceCount': len(decision_refs[code]), 'sources': decision_refs[code][:20],
                  'sourcesTruncated': len(decision_refs[code]) > 20} for code in codes]
    return {'subjectCode': sid, 'qualityStatus': summary['qualityStatus'], 'visitCount': len(visits),
            'indexDate': cutoff, 'spanDays': (date.fromisoformat(dates[-1])-date.fromisoformat(dates[0])).days if dates else None,
            'sameDayVisitGroups': len(ambiguous_days), 'cognition': cognition, 'featureCoverage': coverage, 'decisions': decisions,
            'riskScore': None, 'historicalAvailabilityVerified': False}


def preview_quality(payload):
    """Original preview fields plus an optional, value-free qualityReport."""
    preview, requests = prepare_csv(payload)
    dictionary = field_dictionary()
    rows = _locations(payload) if requests else None
    summaries = {row['subjectCode']: row for row in preview['subjects']}
    subjects = [_subject(request, summaries[request['subjectCode']], rows) for request in sorted(requests, key=lambda row: row['subjectCode'])]
    quality = {'scope': 'COURSE_SYNTHETIC_QUALITY_REVIEW', 'reportVersion': REPORT_VERSION,
               'status': 'NOT_EVALUATED' if preview['errorCount'] else 'REVIEW_ONLY',
               'requestDigest': preview['requestDigest'], **dictionary, 'subjects': subjects,
               'issueGuidance': [{'code': code, 'message': ISSUE_GUIDANCE[code]} for code in sorted({row['code'] for row in preview['issues']})],
               'modelExecuted': False, 'persisted': False, 'predictionProduced': False,
               'clinicalValidityAssessed': False, 'sourceAuthenticityVerified': False,
               'historicalAvailabilityVerified': False}
    return {**preview, 'qualityReport': quality}
