# Python构造预测评估

`python_service.prediction_evaluation`实现FR13的合成工程子集：声明的受试者划分预检、ROC-AUC、非插值AP、梯形PR面积、Brier、阈值混淆矩阵及固定分箱校准。输入必须为构造的24个月完整二分类概率与标签；不执行模型、不拟合/重校准、不读文件或网络，也不更新任何历史研究结果。

原课程加性排序不是校准概率，禁止直接作为此工具输入。模块没有AgentResult适配器，不改变原四阶段、版本、HTTP或Java职责；调用方重标构造标签也不能建立来源真实性、许可或临床有效性。真实竞争风险、删失、多分类和NACC映射终点不在这个估计器范围。

## 内存调用示例

以下对象完全手工构造，不来源于课程fixtures或临床样本。

```python
from python_service.prediction_evaluation import evaluate_predictions, protocol_sha256

protocol = {
    'schemaVersion': 'synthetic-binary-evaluation-v1', 'mode': 'SYNTHETIC_TEST',
    'protocolVersion': 'demo-eval-v1', 'dataVersion': 'demo-data-v1',
    'endpointId': 'demo-complete-event', 'horizonMonths': 24,
    'labelPolicy': 'CONSTRUCTED_COMPLETE_BINARY_NO_CENSORING', 'splitType': 'HOLDOUT',
    'evaluationSubjects': ['DEMO-E1', 'DEMO-E2', 'DEMO-E3', 'DEMO-E4'],
    'splits': [{'foldId': 'demo-holdout', 'trainSubjects': ['DEMO-T1'],
                'testSubjects': ['DEMO-E1', 'DEMO-E2', 'DEMO-E3', 'DEMO-E4']}],
    'thresholds': [0.35, 0.5], 'calibrationBinEdges': [0.0, 0.5, 1.0],
}
panel = {
    'schemaVersion': 'constructed-probability-panel-v1', 'mode': 'SYNTHETIC_TEST',
    'protocolSha256': protocol_sha256(protocol), 'modelVersion': 'demo-model-a',
    'source': 'CONSTRUCTED_TEST_VECTOR',
    'predictions': [
        {'subjectCode': subject, 'foldId': 'demo-holdout', 'outcome': outcome, 'probability': probability}
        for subject, outcome, probability in zip(protocol['evaluationSubjects'],
                [0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8])
    ],
}
evaluation = evaluate_predictions(protocol, panel)
```

示例ROC-AUC=0.75、AP=5/6、梯形PR面积=19/24、Brier=0.158125，仅用于核对算术，不是模型性能。返回精确协议/面板内容摘要、版本/目标/窗口、划分摘要、汇总及逐折指标。模型、数据、目标、协议、foldId均要求demo-*，对象要求DEMO-*；所有字段严格检查，不接受额外字段。

## 分组与完整性

HOLDOUT恰好一折；OOF为2—20折。每折trainSubjects/testSubjects非空且唯一、互不重叠；每个evaluationSubjects对象恰好测试一次，不许测试漏项、重复、额外对象或错折。每个面板恰好包含同一测试全集，一个对象一条预测。OOF其他折可含该对象的训练记录，这是声明的交叉验证设计；这些ID检查不能认证实际训练成员、预处理泄漏、历史可获得日或真正折外预测。对应验证标志持续false。

测试对象1—200个、每折训练ID最多1000、JSON输入合计上限1MiB。标签必须为整数0或1，不能用null、bool、删失码或竞争事件码代替；概率必须有限且位于[0,1]，端点0/1可用。没有自动补值、排除不利样本、阈值优化或标签重映射。协议thresholds预声明1—50个递增且严格位于(0,1)的阈值，calibrationBinEdges预声明2—21个递增边界并覆盖[0,1]；面板绑定精确协议摘要。

## 指标约定

ROC-AUC按正负配对的排序一致率计算，同分计半；任一类缺失时null。AP按概率同分组计算召回增量加权精确率，不插值；另列梯形PR面积，两者不能互换。AP及PR面积无阳性时null；只有阳性时可为1，但ROC-AUC仍未定义。[scikit-learn AP说明](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.average_precision_score.html)解释了两种PR摘要的区别。

混淆矩阵固定probability>=threshold判阳性，报告TP/FP/TN/FN、灵敏度/特异度/PPV/NPV；零分母返回null。Brier为概率与0/1标签差的平方均值。固定分箱采用右闭边界，首箱包含0；每箱保留人数/事件数/平均概率/事件比例，空箱保留人数0与比率null。另列整体平均预测减事件比例，以及固定分箱加权绝对差ECE；它们是描述量，fittedIntercept/fittedSlope始终null、fitReason=NOT_FITTED。[校准曲线说明](https://scikit-learn.org/stable/modules/generated/sklearn.calibration.calibration_curve.html)给出分箱平均值的定义。

逐折结果保留单类/小样本的未定义值；不能把折当独立受试者，也不能拿构造数据的良好指标认证外部适用性。sourceAuthenticityVerified、researchAcceptanceEstablished、clinicalValidityEstablished等持续false；既有科研负面结果和NOT_ESTABLISHED临床精度不因这里的算术验证改变。
