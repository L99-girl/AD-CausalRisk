# Python先验图模板与来源路径

本模块提供FR08/09的课程合成工程子集。默认五节点/四方向仍为原`synthetic-prior-v1`，ACTIVE表示输入资格，不表示学习出的边、因果效应或稳定性。真实研究医学图模板、完整人口学/生物标志物节点及临床证据仍须单独协议和验收。

## 查看与检查模板

```python
from python_service.course_graph import (
    default_graph_template, validate_graph_template, inspect_course_graph,
)

template = default_graph_template()  # 独立JSON对象，可由调用方序列化
view = inspect_course_graph(request)  # request为原AgentRequest

candidate = default_graph_template()
candidate['templateVersion'] = 'demo-candidate-1'
candidate['edges'].pop(0)
checked = validate_graph_template(candidate)
candidate_view = inspect_course_graph(request, template=checked)
```

模板字段固定为schemaVersion、mode、templateVersion、nodes、edges。schemaVersion=`course-prior-template-v1`，mode=`SYNTHETIC_DEMO`；节点保留原COGNITION、WARNING、APOE及左右MRI，允许调整显示标签。方向仅允许三来源→COGNITION及COGNITION→WARNING的子集；标签改变或边删减须使用`demo-*`候选版本。重复/未知节点、悬空/逆向/自环/其他环、重复边、任意权重或学习/因果证据声明被拒绝。证据等级/方向/限制说明保持原定义。

`synthetic-prior-v1`内容不能修改或重排序后复用原版本。候选版本名是调用方声明，不是持久版本注册；每次返回templateSha256绑定精确内容，相同版本名不能代替内容核对。模板上限64KiB，原请求上限128KiB，输入先快照再校验；没有网络、模型、文件或数据库操作。

工作流始终调用默认图构建器，未增加模板请求字段，候选配置不进入任何评分器。`inspect_course_graph`只按原索引日/最新非空/缺失/冲突规则实例化图；riskScore恒为null，modelExecuted/modelFitted/predictionProduced/persisted均false。BLOCKED保留空图，原模板且非阻断时的originalScoringEligible只表示符合原资格，不能解读为已经执行评分。候选始终originalScoringEligible=false。

该图不增加未采集的人口学/PET/CSF字段，不证明医学边方向。原左右MRI均可作为上下文ACTIVE，实际演示规则仍左侧优先、缺失才回退右侧；两侧ACTIVE不产生两个MRI贡献。来源历史可获得日和真实性、边稳定性及临床有效性仍未建立。
