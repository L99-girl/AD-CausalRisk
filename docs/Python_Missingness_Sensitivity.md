# Python缺失输入敏感性

这是FR17的课程合成工程子集：有界生成原规则的输入移除组合，随后由调用方显式执行原HTTP/工作流，再分析完整已验证结果。它不生成或选择降级模型，不估计校准可信度，不认证缺失场景的临床可靠性。原模型标识、四阶段、公式、窗口、HTTP、Java职责及研究资料保持。

## 生成场景计划

```python
from python_service.course_missingness import prepare_missingness_requests, validate_missingness_plan

# requests为调用方已有的原AgentRequest列表；run_ids须由调用方业务逻辑显式分配。
plan = prepare_missingness_requests(requests, run_ids, granularity='MODALITY')
verified = validate_missingness_plan(plan)
```

MODALITY默认按COGNITION（MMSE/MoCA/CDR-SB）、GENETICS（APOE）、MRI（左右海马）三组生成8个子集，mask=0为未移除基线。SIGNAL按MMSE、MOCA、CDR_SB、APOE、MRI左、MRI右六项生成64个子集。场景按subjectCode排序、mask递增，依次使用run_ids；没有隐式编号分配、提交、重试或执行。每个编号必须符合原runId格式、全局唯一，并与所有输入基线runId不同；这不认证编号在其他进程/Java中未被使用，调用方仍负责业务分配。

认知值在全部输入访视中置null，保留访视编号/日期和其他值；原本缺失或未提供的字段不伪补值/键。特征按所选名称移除全部历史行，包括重复、null和索引日后记录，避免更早观测重新成为有效来源。未选中的字段/单位/日期/模型/数据版本/窗口保持原样，不插补、不外推。inputChangedBeyondRunId明确记录实际内容是否改变；移除已缺失项不冒称新增证据。

每个场景保留基线/请求摘要、实际置null数量、移除行/非空值数量、原数组sourceMap。sourceMap为子请求保留行对应基线数组的1基序号；后续不能把删除行后的新序号误作原始行。它不是CSV物理行或认证来源ID。

输入1—100个唯一对象/原runId，同一数据/模型版本与窗口；输入JSON合计上限1MiB。最多1000场景，场景编码总量4MiB、整计划上限6MiB。默认100对象×8可用，信号级16对象×64因超过1000被拒绝；调用方应明确分批和分配ID，不会自动拆批或续跑。validate_missingness_plan会根据原请求/分组/显式编号重新生成全部场景，并检查精确JSON内容（含mask类型、来源映射、摘要和执行标志），拒绝只改hash或冒改字段的计划。

计划生成与校验不调用评分器、HTTP、文件或业务数据库；scoringExecutedByThisCall/networkUsedByThisCall=false，clinicalConfidence=null，alternativeModelSelected=false。原阻断请求仍可被计划化用于诊断，不据此认定其已经合格；不支持的窗口仍保持原值，不能通过缺失组合改成24个月。
