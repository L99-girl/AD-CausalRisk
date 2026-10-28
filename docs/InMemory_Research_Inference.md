# 研究输入到既有CIF的受控内存适配

本模块完成第3→4环节的有界工程支撑：把[版本化输入声明门槛](Real_Input_Admission.md)接到既有`discrete.predict_cif`数值路径。只有构造上下文、替身回调和人工常数月危险率的验收；没有真实输入读取、参数加载、模型拟合、共享HTTP、业务权限服务或部署。

原合成CLI及共同Java/HTTP契约不变。元数据相容、调用授权、模型归档核验和临床资格分别处理。模块不建立因果识别或证明上下文、模型摘要及权限声明真实。

## 两条独立条件与单次调用

`validate_snapshot`的METADATA_CONSISTENT不授予预测权限，原报告的`predictionAllowed=false`保持。可信宿主在独立核对访问授权、数据/参数许可及调用范围后，才可另行构造一个内存许可；请求JSON不能携带授权对象。

```python
from research_runtime.inmemory_inference import (
    authorize_once, bind_existing_model, run_in_memory,
)

# model必须已由宿主通过原严格加载器独立核验；这里不读参数文件。
predictor = bind_existing_model(
    model, verified_identity=trusted_context['model'], state_token=model_state_digest,
)
permit = authorize_once(
    request, trusted_context=trusted_context,
    authorization_ref=host_authorization_reference,
    authorization_granted=host_independent_authorization_decision,
)
result = run_in_memory(
    request, trusted_context=trusted_context, predictor=predictor, permit=permit,
)
```

`authorization_granted`只接受Python的True，默认False；它及引用是可信宿主的声明，不是模块验证出来的权限。Java授权、对象范围、模型发布许可和业务审计仍由相应宿主负责。不要从来件或METADATA_CONSISTENT自动生成该决定。

许可只在内存中绑定**完整请求和独立上下文**，含记录顺序、观测/缺失证据、模型身份、索引日、版本和时间政策。内部临时摘要不返回、不写入文件；字典键顺序不影响绑定，数组顺序和数值表示改变会影响绑定。许可和绑定预测器均拒绝序列化，repr不输出个体信息或内部摘要。

| 情况 | 返回/行为 |
| --- | --- |
| 元数据BLOCKED | BLOCKED，预测器零调用、predictions=null，保留全部诊断分母 |
| 元数据相容、无许可 | PERMISSION_REQUIRED，零调用、predictions=null |
| 绑定、状态及许可通过 | 调用一次，完整校验通过后COMPLETED，预测只返回宿主内存 |
| 许可对应另一快照/上下文 | 固定码拒绝，零回调 |
| 许可已使用或正在执行 | 拒绝，不重算、不等待后重放或返回缓存 |
| 身份/状态/回调/结果异常 | 抛固定码InferenceError，不返回部分预测，不自动重试 |

元数据阻断和快照错配发生在实际调用之前，不消耗回调预算。匹配许可一旦进入CLAIMED，后续预检失败也记为FAILED；回调是否已进入可读`permit.prediction_calls`（0或1）。并发共享同一个许可时最多一个线程进入回调；许可状态为READY→CLAIMED→COMPLETED/FAILED。

单次性针对同一内存许可对象；重新调用授权函数会产生新许可。它不是跨进程幂等、授权引用去重、撤销服务、队列或业务重试机制，不能代替Java的持久化任务/幂等控制。

## 输入、模型与结果绑定

`BoundPredictor`在绑定时保存独立模型身份与状态指纹基线。执行前核对身份与上下文一致，前后状态指纹必须不变；同一预测器的执行受锁保护。指纹函数必须覆盖参数、预处理、类别、图及相关运行状态；固定假指纹无法证明状态未变。绑定元数据不替代原归档hash、源码、软件锁及模型作用域核验。

回调只收到由冻结快照生成的`subject_id`及有序七/十特征值，不含结局、观察月或来源日期。缺失保留为null；科学桥接时转为NaN，不补零或重新拟合预处理。不允许回调改动传入行。调用方原对象与回调返回对象均与结果分离。

回调协议`research-inmemory-predictor-v1`要求schemaVersion、完整model身份、严格整数24月窗口、原输出政策和records。每行必须精确为subject_id、ad_cif_24m、other_dementia_cif_24m，人数/标识/顺序与原输入一致；禁止缺行、加行、重排、重复关联、bool/NaN/无穷/负值或非法两原因概率和。任一行不合格则整批不返回，不裁剪或重标结果。

成功外层格式为`research-inmemory-inference-v1`，返回原dataVersion/indexDate/时间政策和绑定模型、原声明诊断、调用计数及内存预测。`executionPermissionUsed=true`表示使用了宿主许可；临床、来源、历史实时和个人因果认证仍为false，默认模型不变。源值和原始声明不附加回显；个体标识及CIF仅供独立获授权的宿主处理，模块不保存、记录或导出。

可信回调不是沙箱。模块检查已提供的行和有效状态指纹，不能撤销任意Python回调在其他对象、文件或网络上的副作用；宿主须限制其来源与执行环境。异常消息只返回固定码，模型/解析器可能带值的异常文本不转发。发生失败后应保留宿主实际调用计数和失败事实，不自动重试或把未知结果标为成功。

## 原数值路径复用

`bind_existing_model`不打开清单、归档或临床文件，不构造/训练风险模型。它把原七/十特征和None→NaN的浮点表示送入原`discrete.predict_cif`；整数无法在float64中精确表示时拒绝，不偷偷舍入。使用原24个人月网格、类别到两原因CIF的累计计算，不复制另一套累计公式，不施加新校准或阈值。

模型须支持predict_proba及named_steps['hazards'].classes_，类别恰为0/1/2。科学桥接在原函数前检查每人月危险率的形状、有限性、范围及互斥和为1，保留合法类别排列，拒绝网格修改；原CIF的返回再进入整批结果检查。两个阶段均不进行归一化修复。图模型继续使用调用方提供的既有模型实际路径；此桥接验收未加载真实图权重，不能把人工常数危险率当成真实图模型验证。

## 可运行构造示例与验收

在已有研究科学环境、仓库根目录运行：

```powershell
python -B -m research_runtime.examples.inmemory_constructed
python -B -m unittest research_runtime.tests.test_inmemory_inference research_runtime.tests.test_inmemory_cif_bridge -v
```

示例在程序内生成构造元数据和常数月危险率[0.94,0.04,0.02]，先验证无许可不调用，再独立给出构造许可，调用原CIF一次；只打印聚合操作状态。不存在真实参数/输入路径或拟合。宿主控制层本身仅依赖标准库，科学桥接按需使用原NumPy/pandas/sklearn环境。

55项源码复制隔离检查首次通过（30项原声明/兼容＋25项本轮适配/桥接）：同许可并发单调用、失败不重试、完整快照绑定、输入/状态修改、错误模型/结果关联/概率、无损数值转换、缺失保留，以及人工常数危险率下两原因解析解、类别排列和边界。测试中40次构造回调尝试、14次原CIF调用单列，0真实解析/权重/预测或风险拟合。对任意回调错误不返回部分分数；结构检查不能认证来源、临床概率或因果。

该内存适配、声明校验和数值路径复用工程包到此关闭，不追加控制器层。真实上下文建立、参数/软件核验、独立调用权限、真实研究/业务接通和临床验收继续分别开放。下一科研任务为尚未完成的七/十变量表格基线分组Shapley/LIME方法适配与执行规格，先复用现有来源清单/源码和通用解释算子做无真实数据验收；不重开已关闭置换/参考替换或先验图固定归因研究，不自动读取/加载/拟合。
