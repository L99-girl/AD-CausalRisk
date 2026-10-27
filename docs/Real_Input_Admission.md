# 版本化研究输入声明与离线一致性校验

`research_runtime.input_admission`服务第1→3环节的工程接入准备。它在内存中核对输入声明与调用方独立持有的模型、来源映射和记录证据；本阶段仅以构造数据验收。模块仅依赖Python标准库，没有文件读取器、模型加载、预测、拟合、插补、保存或HTTP入口。

原`python -m research_runtime`继续只接受合成数据。新模块的`METADATA_CONSISTENT`表示声明与给定上下文相容，**不授予预测权限，不证明上下文真实或独立，也不认证来源、历史实时、因果或临床准入**。`predictionAllowed`和所有认证标记始终为false。Java仍负责权限、业务取数和持久化；这里没有改变共同契约。

## 调用与版本

```python
from research_runtime.input_admission import validate_snapshot, validate_json

# 两个参数均由已获授权的调用方提供；本模块不读取文件。
report = validate_snapshot(request, trusted_context=context)
# 已持有的UTF-8 JSON字节也可校验，重复键和非JSON数值被拒绝。
report = validate_json(raw_bytes, trusted_context=context)
```

| 对象 | 版本与用途 |
| --- | --- |
| 请求 | `research-real-input-admission-v1`，`purpose=OFFLINE_RESEARCH_ADMISSION` |
| 调用方上下文 | `research-input-context-v1`，从独立受控来源建立，不可由来件自证 |
| 返回诊断 | `research-input-admission-result-v1`，仅聚合计数及模型元数据 |

请求和上下文先复制为有界JSON快照，不修改调用方对象。请求上限128KiB、1–100条记录，两者同时适用；元数据较多时会先触及字节上限。上下文上限1MiB、最多1000项证据。格式/版本/字段/单位/非法数值等错误抛出`AdmissionError`，消息只有固定错误码，不回显输入或个体标识。形状合法但证据/质量/时序不足返回`BLOCKED`，不会补0、丢弃记录、换模型或静默放宽政策。

## 请求与独立上下文

请求顶层字段必须精确为`schemaVersion`、`purpose`、`dataVersion`、`indexDate`、`predictionWindowMonths`、`availabilityPolicy`、`model`、`records`。窗口只接受严格整数24；单批次使用一个索引日。每条记录必须有唯一`subjectCode`和完整`features`。标识只做语法/唯一性检查，不证明已去标识、参与者身份或访问权限。结局、观察月、随访标签和额外字段均不进入该输入契约。

上下文字段必须精确为`schemaVersion`、`dataVersion`、`indexDate`、`availabilityPolicy`、`model`、`sourceMappings`、`evidence`。索引日、数据版本、时间政策及完整模型身份必须与请求一致；来件不能自行后移索引、降为回顾性政策或选择另一模型。全局绑定错配阻断整批，个别记录错配则计入阻断记录数；报告仍保留完整批次分母。

### 模型身份

`model`必须提供`family`、`specification`、`role`、有序`features`、`predictionPolicy`，以及`manifestSha256`、`artifactSha256`、`trainingPlanSha256`、`runtimeSourceSha256`、`softwareLockSha256`、`sourceMappingSha256`、`graphProtocolSha256`。摘要必须为64位小写十六进制，图协议摘要在表格模型中必须为null。它们是调用方的独立预期身份，本模块不打开相应文件，也不证明软件/参数在当前机器已验证。

| 类型 | 允许身份 |
| --- | --- |
| 七变量表格 | `specification=seven`，LR/RF/XGBoost，原最终七变量角色 |
| 十变量表格 | `specification=multimodal_values`，LR/RF/XGBoost，原最终多模态角色 |
| 十变量先验图 | `family=prior_graph`、`role=GRAPH_FINAL`，图协议摘要必填 |

表格family使用`logistic`、`random_forest`、`xgboost`。不接受外折角色、自动选模、可获得性对照、校准后输出或其他图臂。输出政策固定为`raw_uncalibrated_24month_CIF`；这不是默认模型切换或模型发布批准。

### 来源映射与记录证据

`sourceMappings`按特征精确覆盖，分别包含`sourceId`、`dataset`、`table`、`field`、`release`、`language`、`instrumentVersion`、`processingVersion`。每个特征映射使用唯一sourceId。`mapping_digest()`只对非临床映射做规范JSON SHA256；摘要绑定在模型身份中。调用方须核对该映射确实适用于指定训练输入与模型，不能用请求现场生成的摘要替代原来源依据。未知元数据允许保留null；已观测特征若缺必要来源元数据则阻断。

每个特征的观测或缺失声明都必须给出`evidenceRef`。独立`evidence`目录以该引用为键，每项包含`subjectCode`、`feature`和完整`observation`；与对应观测的标识、字段、数值、单位、日期、质量、扫描及来源引用逐项相同才通过一致性检查。来源表名、一般表单说明或一条公开答复不能自动生成这些逐记录证据。无引用、未绑定、跨人/跨字段复用或数值/日期/QC改变均阻断；将已有观测改为null也须有独立缺失证据，不能靠删除引用绕过。

上下文自身也须结构合法；例如把score观测放入教育年限证据会先报单位错误。若调用方把来件复制成上下文，模块无法证明其独立性；即使两者相符，认证和预测许可仍为false。真实来源的映射过程、访问授权和外部事实核验仍须另行完成。

## 特征及观测字段

特征顺序复用既有估计器，单位与旧合成校验器一致，构造兼容检查覆盖二者相同。

| 特征 | 单位/边界 |
| --- | --- |
| age_years、education_years | years |
| mmse、cdr_sb、cdr_global、adas__total13、faq__faqtotal | score |
| apoe4_count | count，严格整数0/1/2 |
| mri_left_hippocampus_volume、mri_right_hippocampus_volume | mm3，正数，双侧联合 |

七变量取前七项，十变量全部提供。每项必须精确包含`value`、`unit`、`measuredDate`、`availableDate`、`dateBasis`、`sourceRef`、`qc`、`completion`、`missingReason`、`scanId`、`evidenceRef`。有限int/float允许，bool、数字字符串、NaN/Infinity拒绝；没有重新发明量表临床界值或做单位换算。MRI仍为原量纲体积，不做ICV校正。

| 范围 | 已观测值的一致性要求 |
| --- | --- |
| 人口学 | QC/完成标记为`NOT_APPLICABLE`；来源/日期仍须明确 |
| 五项认知/功能 | QC为`PASS`、完成为`COMPLETE`；语言与量表版本必需 |
| APOE | QC为`PASS`、完成为`NOT_APPLICABLE` |
| MRI | QC为`PASS`、完成为`NOT_APPLICABLE`；处理版本、同一扫描标识/测量日/可获得日/日期依据，来源数据集/表/发布/处理版本须一致；索引前最多365天 |

`UNKNOWN`和`FAIL`是可表示的事实状态，不会被格式校验改成PASS；不满足上述要求的已观测值阻断，未知不等于临床错误。`value=null`要求两日期/scanId均null、dateBasis为UNKNOWN，并明确missingReason（UNKNOWN/NOT_COLLECTED/UNAVAILABLE/QC_FAILED）；不能同时声称PASS或COMPLETE。QC_FAILED与FAIL必须一致。缺失组仍保持缺失，不能把保留的未知质量值偷偷改为空值以求通过；若确需排除，应由独立来源与固定策略提供相应缺失证据。所有核心七变量均缺失或仅单侧MRI存在会阻断。

## 日期与返回语义

`dateBasis`为MEASUREMENT_DATE、REGISTRY_PROXY、DERIVED_AT_INDEX或UNKNOWN。未知测量日、索引后测量或可获得日早于所声明测量日均阻断；DERIVED_AT_INDEX只适用于索引当日派生年龄。它不能把注册日认证为实际测量日。

| 时间政策 | 注册日代理 | 可获得日未知/晚于索引 |
| --- | --- | --- |
| RETROSPECTIVE_SNAPSHOT | 明确WARN | 明确WARN，保留回顾性限制 |
| AS_OF_INDEX | BLOCK | BLOCK |

即使严格政策中的声明均一致，也不证明日期来源真实或历史实时资格已建立。原MRI处理晚于索引、来源/QC、MMSE记录补证、因果识别和临床限制仍保留；不把本门槛套用于认证旧1160人已全部合格。

返回值包含状态、全批次/阻断分母、特征顺序和缺失计数、聚合issue、政策及上下文模型身份；不返回个体标识、值、日期、来源行、证据引用、预测或个人hash。每个issue包含code/severity/feature/count，计数可一人多项，不等于阻断人数。检查相容为METADATA_CONSISTENT，有质量/来源/时序问题为BLOCKED；两者都不允许预测。

## 构造验收与后续边界

无需科学依赖即可运行标准库构造示例：

```powershell
python -B -m research_runtime.examples.input_admission_constructed
python -B -m unittest research_runtime.tests.test_input_admission -v
```

示例在程序内生成构造请求和构造上下文，仅输出聚合诊断；里面的模型摘要、来源与记录均是占位构造，不能供真实准入复用。与旧入口的兼容检查另在`test_input_admission_compatibility`，需原科学环境，但不拟合、加载或预测。

本轮30项隔离检查通过，另以`-I -S -B`禁用site-packages运行构造示例，未导入NumPy/pandas/sklearn/torch/joblib。初始一项测试夹具单位冲突已修正且日志保留，未放宽来源或准入逻辑。既有合成CLI、估计器、图实现、固定研究规格、数据/权重和HTTP契约保持。

版本化声明门槛及其[受控内存推理适配](InMemory_Research_Inference.md)均已完成构造验收；工程包到此关闭。元数据相容仍不授予调用许可。实际真实输入读取、独立证据建立、模型发布/软件核验、目标机部署和Java业务接通仍需各自验收，不由此模块自动授权。
