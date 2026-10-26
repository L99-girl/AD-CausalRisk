# 原生图模型与构造验收

> 交付状态（2026-10-26）：本文件记录原生构造验收阶段。后续54次真实图比较及折外解释诊断已完成，当前累计298基础/36校准；下文244/36及“下一任务”是该阶段的历史状态。当前状态取[Python需求状态](Python_Requirement_Status.md)。

状态：**原生可训练实现与本轮构造验收完成关闭；真实图比较尚未执行。** 9项无优化检查、隔离源码三臂×三种子共9基础拟合通过，9个保存产物两原因CIF重放误差0，36项文件/方案/输入/划分错配均拒绝；另有7项协议/软件/特征/源码/非法张量负例检查。总拟合17.612秒，进程峰值410800128字节（约392MiB），单归档7415–7425字节，全部低于预先固定上限。0临床表解析、旧模型加载、真实或校准拟合；真实账本仍244/36。构造指标不作为研究性能。

本任务对应研究主线第2→3环节：让固定的个人观测门控和先验路由实际参与可训练的预警计算，并为后续绑定实际模型的解释提供基础。沿用[冻结机制规格](Graph_Prediction_Protocol.md)和其NumPy数值参照，不改变已关闭的四边图阴性实验。

## 实现与使用范围

[graph_native.py](../research_runtime/graph_native.py)实现CPU、float64、十节点、宽度8、两层单头注意力，按来源归一化；共568个参数。三臂使用相同参数形状、种子和人月批次。自环对照中注意力没有相同的有效作用，不能宣称有效容量完全相等。

训练只接受内存中的原始十变量人月及0/1/2互斥标签。中位数、标准化在传入的训练人月拟合；缺失状态在插补前捕获，跨边两端必须都有观测。优化严格沿用Adam 0.001、weight_decay 0.0001、40轮、batch256、梯度裁剪1.0，无搜索或早停。读出为24个月三类危险率；沿用原`person_period`、`predict_cif`与评价函数，不另造竞争风险评估器。

[graph_acceptance.py](../research_runtime/graph_acceptance.py)只生成原有90行人工样例，复用`checked_design`核对受试者划分后取第一个构造折。它是有界构造验收，不是1160人研究执行器，也不代表已完成五折图研究。现有嵌套校准编排保持不变；本任务不套用任何旧校准参数。

模型保存为纯数值`.npz`，加载始终`allow_pickle=False`。调用方须提供可信文件SHA256、方案、训练输入摘要及队列/划分摘要；归档同时绑定协议、节点顺序、源码和数值软件版本。只有新构造产物参与本轮保存加载，未加载旧研究模型。新格式尚未接入Java、默认服务或现有九模型试算入口。

## 独立环境与验收命令

与既有演示和表格模型环境分开创建环境，以[requirements.graph.lock](../research_runtime/requirements.graph.lock)锁定CPU依赖。PyTorch CPU源见[官方安装说明](https://docs.pytorch.org/get-started/locally/)；自动求导核对采用[官方gradcheck](https://docs.pytorch.org/docs/2.14/notes/gradcheck.html)，优化采用[Adam](https://docs.pytorch.org/docs/2.14/generated/torch.optim.Adam.html)。无需CUDA、torchvision或torchaudio。环境和构造产物不入Git。

在源码仓库目录执行，替换为该环境的Python路径：

```powershell
python -m pip install -r research_runtime/requirements.graph.lock
python -B -m unittest research_runtime.tests.test_graph_native -v
python -B -m research_runtime.graph_acceptance --output <全新的构造结果目录>
```

最后一条会执行9次构造基础拟合，已有本轮结果时直接复用，不重复执行。预算在`Acceptance_Plan.json`先固定：3臂×3种子、0真实/校准拟合，总拟合300秒、进程峰值2GiB、单归档1MB上限；预算超限或任何数值/身份失败停止，保留日志，不自动重试。

## 证据边界与下一任务

固定协议中的`native_training_implemented=false`是上一规格阶段的历史快照，原文件不重绑；本阶段完成状态以新验收记录为准。无训练的前向逐项比对、有限差分梯度、有效消息和屏蔽边梯度检查，属于软件证据。人工标签信号、损失变化、AUC/Brier及保存加载一致性都不能证明真实图增益、个人因果效应或临床可靠性。

唯一下一任务是**固定1160人三臂图研究执行与交付**：先将已有十变量受控快照、原五折、图协议、代码与新软件锁绑定为执行计划，补齐可复用外折执行与验收，再按原54基础/0校准上限推进；45外折和9全量均交付，阴性同样收口。旧模型不重训、不新增原始表读取，不以本轮构造结果选择新默认。图方向仍是项目历史假设；6/10跨连、四节点只自环/直接读出及回顾性MRI时间限制保留。严格因果、真实增益、独立/as-of/QC/临床、图解释与Java业务接通分别保持未完成。
