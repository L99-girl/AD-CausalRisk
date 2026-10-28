# AD-CausalRisk Java 后端

本目录是 Java 业务后端：数据库与迁移、登录与权限、业务任务、调用 Python 子服务、结果复核、随访、报告与审计。浏览器只调用 Java；Java 通过 `AgentClient` 调用 Python 子服务（`127.0.0.1:8091`）。业务逻辑放 Service，Controller 处理 DTO 与 HTTP 映射，Repository 处理数据访问。

## 模块任务说明（原始）

> 在此目录创建Spring Boot工程，负责数据库、权限、业务任务与审计；Python调用封装在AgentClient中。
>
> 先阅读[需求](../docs/Course_SRS_V3_2.md)、[设计参考](../docs/Design_Guide.md)、[目标接口](../contracts/java-business.target.openapi.json)及[AI协作指南](../docs/AI_Collaboration.md)。首次PR建议完成工程配置、数据库迁移与档案接口；后续依次完成登录与对象权限、访视/特征、导入、质控、持久化幂等任务、AgentClient、结果复核、随访、报告和审计。
>
> 交付包含Maven/Gradle锁定构建方式、数据库建表/迁移、合成账号与密码哈希初始化、HTTP接口测试、Mock Python超时/版本错/409/BLOCKED测试、重启历史查询和患者字段过滤。添加自己的CI；未经实现与验收的模块保持待开发。
>
> 在模块README补充Java/数据库版本、环境变量示例、迁移、启动、测试命令及接口地址。参数通过配置读取，密码使用环境变量。API沿用共同契约，业务逻辑放Service，Controller处理DTO与HTTP映射，Repository处理数据访问。

---

## 1. 已实现范围

共同契约共 **22 个操作**，其中**契约内已实现 19 个**（认证 3 + 档案 3 + 访视 1 + 导入 3 + 评估任务 2 + 评估结果 1 + 人工复核 1 + 随访 3 + 报告 1 + 审计 1）；**未实现 3 个**：`PATCH /api/subjects/{subjectId}`（修改档案）、`POST /api/subjects/{subjectId}/features`（写入特征）、`POST /api/subjects/{subjectId}/quality-checks`（执行质控检查）。另有 **3 个扩展操作**（质控，超出契约 22 个操作的范围，见下）。

### 第一组：认证（auth）
| 操作 | 路径 | 说明 |
| --- | --- | --- |
| `postApiAuthLogin` | `POST /api/auth/login` | JSON 登录，建立 `JSESSIONID` 会话 |
| `postApiAuthLogout` | `POST /api/auth/logout` | 使会话失效 |
| `getApiMe` | `GET /api/me` | 返回当前用户与角色菜单 |

### 第二组：档案管理（subject）
| 操作 | 路径 | 说明 |
| --- | --- | --- |
| `getApiSubjects` | `GET /api/subjects` | 分页查询档案列表，先按权限过滤再分页 |
| `postApiSubjects` | `POST /api/subjects` | 创建档案（ADMIN / RESEARCHER） |
| `getApiSubjectssubjectId` | `GET /api/subjects/{subjectId}` | 查询档案详情；`visits` 来自 `visit` 表，`features` 仍为空数组 |

### 第三组：访视（visit）
| 操作 | 路径 | 说明 |
| --- | --- | --- |
| `postApiSubjectsVisitssubjectId` | `POST /api/subjects/{subjectId}/visits` | 创建访视（ADMIN / RESEARCHER） |

访视**没有独立的查询接口**：契约在该路径上只声明了 `POST`，因此访视通过档案详情的 `visits` 字段读取（`GET /api/subjects/{subjectId}`）。新增一个 `GET` 属于共同契约变更，需先走契约 PR。

### 第四组：质控（qc，扩展操作，超出契约 22 个路径范围）
| 操作 | 路径 | 说明 |
| --- | --- | --- |
| `getApiQcList` | `GET /api/qc/list` | 质控审核队列分页列表 |
| `postApiQcAudit` | `POST /api/qc/{id}/audit` | 提交审核决策（APPROVED / REJECTED） |
| `getApiQcStats` | `GET /api/qc/stats` | 按状态分组的质控计数（仪表盘） |

**QC 敏感字段脱敏规则**（`QcAuditService.getQcList`）——与访视原始分数是**两套独立的权限判断**：
- QC 列表中的 `abnormalItems`（异常详情 JSON）和 `auditComment`（审核备注）属于**审核内部字段**，只有 **AUDITOR_ROLES（ADMIN / RESEARCHER）且不带 PATIENT 角色**才能看到原值，其余角色一律返回 `null`。
- **PATIENT 一票否决**：账号只要带 PATIENT 角色，即使同时拥有 ADMIN 或 RESEARCHER，敏感字段依然被强制脱敏为 `null`——与 `canReadRawScores` 的 PATIENT 优先规则一致。
- **DOCTOR 哪怕有 VIEW / MANAGE 授权**，也永远看不到 `abnormalItems` 和 `auditComment`。DOCTOR 可以看到 QC 队列的状态（status = PENDING / APPROVED / REJECTED）、档案 code/alias、访视 code 等**非敏感元数据**，用于了解自己患者的质控进度，但无法查看具体异常详情或审核员的内部备注。这是 QC 内部字段与临床分数（走 `canReadRawScores`）的关键区别——后者在 DOCTOR 持有 VIEW 时是放行的。
- 提交审核（`POST /api/qc/{id}/audit`）仅限 ADMIN / RESEARCHER，DOCTOR / PATIENT 调用直接返回 403 ACCESS_DENIED。
- **并发安全**：审核决策通过 `QcAuditRecordRepository.updateDecision` 原子条件更新——`WHERE q.id = :id AND q.status = 'PENDING'`。两个审核员同时审核同一 PENDING 行时，数据库行锁保证恰好一个返回 rows=1（成功 transition），另一个返回 rows=0（已被他人处理，Service 层抛 400 VALIDATION_ERROR"该记录已被其他审核员处理"）。`@Modifying(clearAutomatically = true)` 保证一级缓存被清理，后续查询不会读到 stale entity。

**OpenAPI 契约兼容性**：本次实现的三个 QC 端点（`GET /api/qc/list`、`POST /api/qc/{id}/audit`、`GET /api/qc/stats`）**均超出 `contracts/java-business.target.openapi.json` 的 22 个契约路径范围**，属于后端为支持人工审核工作流自扩展的端点。契约中唯一的 QC 相关路径是 `POST /api/subjects/{subjectId}/quality-checks`（subject 级别触发 Python 质量检查），返回 `QualityCheck` schema（`qualityStatus` ∈ PASS/WARN/BLOCKED、`issues`、`ruleVersion` 等），标注 `TO_IMPLEMENT_BY_BACKEND_OWNER`，目前尚未实现。

因此脱敏的 `abnormalItems`（异常详情 JSON）和 `auditComment`（审核备注）两个字段**不在契约文件中**——契约的 `QualityCheck` schema 根本没有这两个属性，也不存在对它们的 required 限制。脱敏返回 `null` 完全不违反 OpenAPI 契约的任何硬性约束，零冲突。未来若契约升级加入人工审核端点，需在契约中明确哪些字段 required、哪些可选，届时以契约为准再评估脱敏兼容性。

**访视超限值脱敏（Python 契约兼容）**：`VisitMapper.maskOutOfRange` 在 HTTP 出口（POST 响应 + GET subjectDetail）将 `mmse > 30`、`moca > 30`、`cdrSb > 18` 的值 mask 为 `null`，但 Entity 仍保留原始值供 QC 规则检测（QC 引擎读的是 `raw_mmse`/`raw_moca`/`raw_cdr_sb` VARCHAR 列，而非 DECIMAL 展示列）。需要写入超限值时必须带 `X-Allow-OOR: true` 头，且 `SubjectAccessPolicy.canReadRawScores` 返回 true 的角色才能在响应中看到未脱敏值——实际上目前所有角色的 HTTP 出口统一脱敏，超限值永远对外返回 `null`。

权限规则：ADMIN / RESEARCHER 全量可见；DOCTOR / PATIENT 仅可见 `subject_permission` 表中有授权的档案。创建档案仅限 ADMIN / RESEARCHER；创建访视沿用**同一条** `SubjectAccessPolicy.canCreate` 规则，因此单档案的 `MANAGE` 授权并不足以创建访视。

**患者字段过滤与原始分数**：判定集中在 `SubjectAccessPolicy.canReadRawScores(principal, subjectId)`，按角色且**按档案**决定：ADMIN / RESEARCHER 直接可读；DOCTOR 必须在该档案上持有 `VIEW` 或 `MANAGE`；PATIENT 与任何未知角色一律不可读。**PATIENT 优先级最高**：账号只要带 PATIENT 角色，即使同时拥有 RESEARCHER 或 ADMIN 也一律不可读。因此"只被授予 `SUMMARY_READ`"的医生同样看不到原始分数——这是防止 `SUMMARY_READ` 被升级成整份读取的关键。不可读时详情响应中的 `visits` 为空数组。

**复核 / 随访 / 审计 / 报告的权限口径**（与档案、访视分开判定）：复核要求 `canReadRawScores`（ADMIN / RESEARCHER，或在该档案上持有 `VIEW`/`MANAGE` 的 DOCTOR；带 PATIENT 一律 403）；随访的创建、修改、查询统一使用 `canView`（DOCTOR 没有 `subject_permission` 授权即 403）；审计列表仅 `ADMIN`；报告复用评估的读权限。评估任务的创建沿用 `canCreate`，并对目标档案追加 `canView` 校验。

访视的分数缺失时按 `null` 保存并返回，**绝不补 0**；范围 `mmse`/`moca` 0–30、`cdrSb` 0–18。契约允许任意精度，**接口永远返回提交的数值**：迁移 `V4` 新增 `raw_mmse`/`raw_moca`/`raw_cdr_sb`（`VARCHAR(64)`），保存的是**提交数值的规范化文本**（`BigDecimal.toString()`：`27.555` 原样保留，但 `07.50` 存为 `7.50`、`1e1` 存为 `1E+1`、`+1` 存为 `1`、`-0.0` 存为 `0.0` —— **数值精度不丢，字面量不保留**），`mmse`/`moca`/`cdr_sb`（`DECIMAL(5,2)`）降级为**派生/展示列**（`round(raw, 2)`），只供图表、列表与 SQL 统计使用，不参与评分。原文与派生值在实体构造函数里一次算出，因此不可能只写一半。超出 `VARCHAR(64)` 能表示的精度由 `@Digits(integer = 2, fraction = 61)` 以 400 拒绝，而不是让数据库报错或静默截断。

**数据导入（`POST /api/import-jobs` / `GET /api/import-jobs/{jobId}` / `POST /api/import-jobs/{jobId}/commit`）**：契约的请求体只有 `file`，没有 `importType`，因此服务端**用精确表头判定导入哪张表**（subjects / visits / features 与 fixtures 表头逐字一致，不猜列名、不重排）。预览阶段只做**单表可判定的规则**：UTF-8（容忍单个表首 BOM）、**空单元格=缺失（不是 0；访视分数与 `featureValue` 同理，空特征值合法地存为 `null`）**、`null`/`NaN`/`Infinity`/布尔文本视为非法数值、数值范围与精度、APOE 字面整数 0/1/2、MRI ∈ [0,1] 与单位、DEMO 编号、alias 长度（纯空白或零宽字符视为空）、档案内 `visitCode` 唯一且**不能是纯空白/零宽字符**（与创建 API 的 `@NotBlank` 一致）、**所有日期字段都必须是严格 `yyyy-MM-dd` 的过去或今天日期**（`+02025-01-01` 这类 ISO 扩展年份、`2025-1-1`、带空格等一律按格式错误拒绝；未来日期与年份 ≤ 0 同样拒绝；`visitDate` 与 `recordedAt` 同规则；"今天"按 `Asia/Shanghai` 的业务日判定，见 `ClockConfig`，不随宿主机时区漂移）、30000 字节与逐表行数上限，以及**每档案 100 访视 / 500 特征**（超出的行按行级错误报出，不整批失败）。**只有表头没有数据行**的文件返回 400，而不是一个永远无法入库的 `BLOCKED` 任务。**跨表质量规则（24 个月窗口、索引日多访视、同日特征冲突）不在 Java 侧实现**，属 Python 预检职责。预览通过的行**不立即入库**：原始 CSV 文本存入 `data_import_job.preview_csv`，`commit` 时重新解析同一份字节再插入，并比较**合格行集合的 SHA-256 摘要**（`preview_digest`，V6；逐字段**长度前缀**编码，字段里含 `|` 也不会产生歧义）：数量不一致或**行集不一致**都返回 400（"数据在预览后已变化，请重新预览"），因此"同数量换行"也无法绕过。`BLOCKED` 任务在创建时即清空 `preview_csv`，不保留上传原文；commit 成功时同样清空。`commit` 读取任务时持有**行级写锁**（`findByIdForUpdate`），因此两个并发提交不会重复插入（特征表没有唯一约束，不加锁会静默插入两份）；入库时的任何数据库约束冲突都映射为 400，绝不以 500 结束。**`commit` 会重新校验导入权限**：预览后账号被降权（如 RESEARCHER → PATIENT）时，即使仍是任务创建者也会得到 403——所有权不等于写权限。**降权后仅禁止 commit（写操作），`GET`（只读历史）依然可用**：读取自己的统计与错误明细没有泄露风险，这是明确的产品约定。`validRows == 0` 的任务是 `BLOCKED`，不可入库；commit 失败会回滚并保留 `preview_csv`，可以直接重试。`Idempotency-Key` 校验为 **1–100 字符**并记录在 `idempotency_record`（`UNIQUE (user_id, operation, idempotency_key)`）：同 key 同内容返回原任务，同 key 不同内容返回 400，并发重试靠唯一约束兜底并重放赢家。`errors` 最多返回 200 条（契约没有 truncated 字段），`totalRows/validRows/invalidRows` 始终是完整计数。

### 第五组：评估任务与结果（assessment）

| 操作 | 路径 | 说明 |
| --- | --- | --- |
| `postApiAssessment-tasks` | `POST /api/assessment-tasks` | 幂等创建（`Idempotency-Key` 1–100）；`PENDING` → 调 Python → `COMPLETED`/`BLOCKED`/`FAILED` |
| `getApiAssessment-taskstaskId` | `GET /api/assessment-tasks/{taskId}` | 任务状态与 `stages`（实测耗时，不伪造进度） |
| `getApiAssessmentsassessmentId` | `GET /api/assessments/{assessmentId}` | 结果详情；PATIENT 直接 403（未实现 `PatientAssessmentSummary`） |

事务边界：`PENDING` 与终态各一个 `REQUIRES_NEW` 短事务，中间夹 Agent 的 HTTP 调用，**等待期间不占数据库连接**。任何异常（包括非 `BusinessException`）都先落 `FAILED` 再抛，任务不会永远卡在 PENDING。同一 `Idempotency-Key` 并发时，输家**重放赢家的任务**而不是再跑一次 Python，因此不会撞 `uq_risk_assessment_task`。`BLOCKED` 表示 `riskScore=null`、`riskLevel=UNAVAILABLE`，绝不用 0 或插值补分。

### 第六组：人工复核（review）

| 操作 | 路径 | 说明 |
| --- | --- | --- |
| `postApiAssessmentsReviewassessmentId` | `POST /api/assessments/{assessmentId}/review` | 记录 `ACKNOWLEDGED` / `NEEDS_DATA` / `REJECTED`，并把 `risk_assessment.review_status` 同步为同一状态 |
| （扩展，不在契约内） | `GET /api/assessments/{assessmentId}/reviews` | 复核历史，倒序 |

注意路径参数是**评估 id**（`risk_assessment.id`）而不是任务 id：复核挂在结果上，`assessment_review.assessment_id` 的外键也指向它。

### 第七组：随访（follow-up）

| 操作 | 路径 | 说明 |
| --- | --- | --- |
| `postApiFollow-ups` | `POST /api/follow-ups` | 创建，初始状态 `PLANNED` |
| `patchApiFollow-upsfollowUpId` | `PATCH /api/follow-ups/{followUpId}` | 改期 / 完成 / 取消；非法状态 400；**不存在的 id 是 400**（契约未声明 404） |
| `getApiSubjectsFollow-upssubjectId` | `GET /api/subjects/{subjectId}/follow-ups` | 按计划时间升序 |

### 第八组：报告（report）

| 操作 | 路径 | 说明 |
| --- | --- | --- |
| `getApiReportsassessmentId` | `GET /api/reports/{assessmentId}` | 报告视图；契约当前的响应体就是 `Assessment`，HTML/PDF 导出待契约 PR |

### 第九组：审计（audit）

| 操作 | 路径 | 说明 |
| --- | --- | --- |
| `getApiAudit-logs` | `GET /api/audit-logs` | 仅 `ADMIN`；按发生时间倒序，**无分页**（契约的 `data` 是数组而非分页结构） |

`@AuditLog(eventType, summary)` + `AuditLogAspect` 在目标方法**成功返回后**写 `audit_log`：写入走独立事务（`REQUIRES_NEW`），失败只记日志、不回滚业务。目前只有复核接口接入了注解，**登录成功/失败仍未写审计**。

另外交付：15 张表的 Flyway 基线迁移、四角色与合成账号种子、统一 `Envelope` 响应与错误映射、`X-Trace-Id` 追踪、会话安全配置、CSV 数据导入（预览 + 确认入库）、后端 CI。

## 2. 固定版本

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| Java | 21 | `java.version`；开发机实测 21.0.10 LTS，CI 使用 temurin 21 |
| Maven | 3.9.16 | 固化在 `.mvn/wrapper/maven-wrapper.properties` 的 `distributionUrl`，并用 `distributionSha256Sum` 校验 |
| Maven Wrapper | 3.3.4 | `only-script` 模式，**不提交 `maven-wrapper.jar`** |
| Spring Boot | 3.5.16 | `spring-boot-starter-parent`；该 Spring Boot 线使用 **Jackson 2**，故未选会切到 Jackson 3 的 4.x |
| 目标数据库 | MySQL 8 | 见[需求](../docs/Course_SRS_V3_2.md)；本机无 MySQL，迁移**只在 H2 上验证过** |
| 测试数据库 | H2 2.3.232 | `MODE=MySQL`；不使用 Docker / Testcontainers |

以下版本由 Spring Boot BOM 管理，未手写（括号内为实测解析结果）：Spring Framework（6.2.19）、Spring Security（6.5.11）、Hibernate ORM（6.6.53.Final）、Flyway（11.7.2）、Jackson（2.21.4）、H2（2.3.232）、MySQL Connector/J（9.7.0）。

仅测试范围：`com.networknt:json-schema-validator` **1.5.9**（对着契约文件校验响应）、`org.mockito:mockito-core` **5.17.0**（以 `-javaagent` 加载，原因见 `pom.xml` 注释）。

## 3. 环境变量

参数全部通过配置读取，密码只从环境变量取，**仓库内不存在任何明文凭据**（`V2` 里只有 BCrypt 哈希）。

| 变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `SPRING_PROFILES_ACTIVE` | 是 | 无 | `local`（MySQL）或 `test`（H2） |
| `ADCR_DB_URL` | 否 | `jdbc:mysql://127.0.0.1:3306/ad_causalrisk?useUnicode=true&characterEncoding=utf8&connectionTimeZone=UTC` | MySQL 连接串 |
| `ADCR_DB_USERNAME` | 是 | 无 | 未设置时启动即失败，不会静默回退 |
| `ADCR_DB_PASSWORD` | 是 | 无 | 同上 |

PowerShell 示例（占位值，请替换为本机实际值）：

```powershell
$env:SPRING_PROFILES_ACTIVE = 'local'
$env:ADCR_DB_URL      = 'jdbc:mysql://127.0.0.1:3306/ad_causalrisk?useUnicode=true&characterEncoding=utf8&connectionTimeZone=UTC'
$env:ADCR_DB_USERNAME = '<your-db-user>'
$env:ADCR_DB_PASSWORD = '<your-db-password>'
```

本目录没有 `.env.example`：Spring Boot 不会读取 `.env` 文件，放一个不会被加载的示例文件只会误导，变量清单以上表为准。`.gitignore` 已忽略 `.env` 与 `.env.*`（保留 `.env.example`），如确需该文件可直接添加。

`application.yml` **刻意不配置 datasource**：必须显式指定 profile。不带 profile 启动会因缺少数据源而立即报错，而不是静默启用内存库。

## 4. 数据库迁移

- 迁移脚本位于 `src/main/resources/db/migration/`：`V1__baseline_schema.sql`（15 张表、唯一约束、外键、索引、枚举 CHECK），`V2__seed_synthetic_accounts.sql`（四角色 + 合成账号），`V3__increase_visit_score_precision.sql`（把 `visit` 的三个分数列从 `DECIMAL(4,1)` 提升为 `DECIMAL(5,2)`），`V4__preserve_raw_visit_scores.sql`（新增 `raw_*` 文本列保存提交原文，把 DECIMAL 列降级为派生列，并回填历史行 —— 回填不可逆，详见 §12），`V5__add_import_preview_storage.sql`（给 `data_import_job` 增加 `import_type` / `preview_csv` / `source_digest`，供导入预览留存与 commit 重放），`V6__add_import_preview_digest.sql`（增加 `preview_digest`，让 commit 能证明"要插入的行集"与预览时一致，而不只是数量相同），`V7__add_qc_audit_record.sql`（新建质量控制审核表 `qc_audit_record`，记录每个访视/档案的 PENDING / APPROVED / REJECTED 审核状态、异常详情与审核备注、审核人及时戳），`V8__drop_visit_score_checks.sql`（移除 `visit` 分数列上的数据库范围 CHECK 约束——0–30 / 0–18 的越界校验移交 QC 引擎处理，因为超限值仍需保留原文供质量检测，但不在数据库层强制拦截；同时超限写入由 `X-Allow-OOR` 头与 `canReadRawScores` 权限控制）。
- **迁移在应用启动时由 Flyway 自动执行**；测试时在 H2 上由测试上下文自动执行。未配置 `flyway-maven-plugin`，因此**没有独立的迁移命令行**。
- 表结构的唯一事实来源是迁移脚本。JPA 配置为 `ddl-auto: validate`：实体与 DDL 不一致时启动即失败，**不允许改成 `update`**，也不靠启动重建表。
- **不要修改已经应用过的迁移**：Flyway 会因校验和不匹配而拒绝启动。新增变更请使用下一个版本号（当前已用到 `V8`，下一个是 `V9__*.sql`）。
- `V1` 顶部写明了"可移植性契约"：同一份 SQL 必须同时跑在 MySQL 8 与 H2 `MODE=MySQL`，因此不使用 `ENGINE=`、`DEFAULT CHARSET`、`COLLATE`、`COMMENT`、`UNSIGNED`、`ON UPDATE CURRENT_TIMESTAMP`、`JSON` 列类型。

## 5. 启动

需要 JDK 21；无需预装 Maven（wrapper 会下载并校验）。

```powershell
# Windows
cd backend
$env:SPRING_PROFILES_ACTIVE = 'local'   # 另需第 3 节的三个变量
.\mvnw.cmd spring-boot:run
```

```bash
# Linux / macOS
cd backend
SPRING_PROFILES_ACTIVE=local ./mvnw spring-boot:run
```

或运行已构建的产物：

```bash
java -jar target/backend-0.1.0-SNAPSHOT.jar --spring.profiles.active=local
```

服务监听 `http://127.0.0.1:8080`。**上述启动命令尚未在本机实际执行过**（本机无 MySQL），见第 13 节。

## 6. 构建与测试

```powershell
# Windows：完整构建 + 测试
cd backend
.\mvnw.cmd -B -ntp verify

# 只跑测试，或只跑某个测试类
.\mvnw.cmd -B -ntp test
.\mvnw.cmd -B -ntp test "-Dtest=AuthApiTest"
```

```bash
# Linux / macOS / CI
./mvnw -B -ntp verify
```

测试使用 `test` profile 的 H2（`MODE=MySQL`），**不需要 MySQL、不需要 Docker**。多数测试类用 `@Transactional` 回滚隔离，而不是删表重建；**4 个类刻意不使用**（`ImportJobCommitConcurrencyTest`、`AssessmentApiTest`、`AssessmentReviewApiTest`、`FollowUpApiTest`），因为它们要验证 `REQUIRES_NEW` 事务真实提交，改为 fixture 先提交、`@AfterEach` 按外键顺序清理。

| 测试类 | 用例数 | 覆盖 |
| --- | --- | --- |
| `SchemaMigrationTest` | 14 | 迁移执行、15 张表精确集合、唯一/外键/CHECK 约束确实生效、种子账号与 BCrypt 口令匹配、`visit` 派生列 precision=5/scale=2、`raw_*` 为长度 64 的字符列、`data_import_job` 的 `import_type`/`preview_csv`/`source_digest` 形状 |
| `EnvelopeContractTest` | 15 | 六键 `Envelope`、null 不省略、未知字段拒绝、400/401/403/404/405/415/500 映射、traceId 透传、真实安全过滤链 |
| `AuthApiTest` | 12 | 登录 / 登出 / `api/me`、多角色并集与菜单、统一失败提示、会话固定防护、会话失效 |
| `SubjectApiTest` | 28 | 三接口正常流程、分页边界钳位、subjectCode 格式/重复校验、不存在返回 400、DOCTOR/PATIENT 创建返回 403、DOCTOR 只看授权档案、未登录 401、详情 visits/features 为空数组、**原始分数按角色+按档案过滤：PATIENT、`PATIENT+RESEARCHER` 双角色、持有 `VIEW` 的 PATIENT、仅有 `SUMMARY_READ` 的 DOCTOR 均收到空 visits（均以 ADMIN 对照证明数据存在），持有 `VIEW`/`MANAGE` 的 DOCTOR 可读，无授权返回 403**、真实登录建立 session、契约 schema 校验 |
| `VisitApiTest` | 31 | 创建访视正常流程、读取闭环（详情 `visits` 出现新记录）、按 `visitDate`/`id` 排序、同 `visitCode` 跨档案可用、分数上下界、50 字符 `visitCode`、缺失分数存 `null` 不补 0、越界拒绝、多余小数原值保留（`27.55` 存回 `27.55`）、**3 位小数原值往返：POST 与 GET 都返回 `27.555`，而实体派生列是 `27.56`、`raw_mmse` 是 `"27.555"`**、**未回填（`raw_*` 为 NULL）的行退回 DECIMAL 列**、**全表不变量 `mmse == round(raw_mmse, 2)`**、**`+02025-01-01`/`2025-1-1`/`2025/01/01` 等非契约形状的 `visitDate` 返回 400 `VALIDATION_ERROR` 且不写库**、**`2025-02-30` 这类形状合法但日历非法的日期是 400 而不是 500**、未知字段拒绝、重复 `visitCode` 返回 400 且不覆盖、档案不存在返回 400、DOCTOR/PATIENT 与仅有 `MANAGE` 授权者返回 403、未登录 401、契约 schema 校验 |
| `VisitServiceTest` | 2 | 纯 Mockito 单测：数据库唯一约束在预检之后触发时返回 400 `VALIDATION_ERROR` 而不是 500；**形状合法但日历非法的 `visitDate` 是业务失败而非 `DateTimeParseException`** |
| `CsvImportParserTest` | 42 | 纯单测：精确表头嗅探与拒绝重排/改名、表首 BOM、引号内逗号/换行与**物理行号**、列数不符、空单元格=缺失而 `0` 保留、**空 `featureValue` 合法且为 `null`**、`null`/`NaN`/`Infinity`/布尔文本非法、范围与精度、APOE 字面整数、MRI 区间与单位、档案内 `visitCode` 重复与库内已存在、**`visitCode` 为纯空格被拒**、**未来日期与年份 ≤ 0 对所有日期字段生效**、**`+02025-01-01`/`2025-1-1`/带空格等非严格 `yyyy-MM-dd` 一律拒绝**、字节与行数上限、**只有表头返回 400**、**每档案 100 访视 / 500 特征上限**、**合格行摘要与顺序无关且随内容变化**、**含 `|` 的字段不会造成摘要歧义**、**仅含零宽空格的 alias 被拒**、**Emoji 按字符而非 UTF-16 单元计数（alias 100/visitCode 50 边界）**、计数恒等式 |
| `ImportJobApiTest` | 29 | 预览三表、缺 `Idempotency-Key` / 缺 `file` / 错误 Content-Type / 超限 / **Key 超长或为空** / **只有表头** 均受控 4xx、幂等重放与同 key 换内容 400、commit 入库（档案/访视/特征）、**空特征值入库为 SQL NULL**、重复 commit 400、**预览后被降权为 PATIENT 的创建者 commit 返回 403 且不写库**、`BLOCKED` 400 且**不保留上传原文**、预览后数据变化 400、**同数量换行被摘要拦下**、**无摘要的旧任务退回数量比较**、`errors` 截断到 200 而计数完整、读权限（创建者 vs 非 ADMIN）、DOCTOR/PATIENT 403、未登录 401、契约 schema 校验 |
| `ImportJobServiceTest` | 13 | 纯 Mockito：幂等唯一约束竞态的失败方**重放赢家**而不是 500、同 key 不同内容被拒、commit 重放计数不一致被拒且不写库、**commit 走加锁查询**、**降权后的拥有者仍被拒（所有权不等于写权限）**、已 `COMMITTED` 的任务被拒、**无记录的非唯一键冲突降级为 400**、Key 长度越界在触库前被拒、**行集变化（同数量）被摘要拦下**、**无摘要时退回数量比较**、**"今天"取自配置时区的 Clock**、**重放时 `result_id` 为空是 400 而非 500**、**重放时拒绝他人的任务** |
| `ImportJobCommitConcurrencyTest` | 1 | 非事务集成测试：两个线程同时 commit 同一任务，**只有一个成功、另一个得到业务异常**，特征行只插入一次（不依赖唯一约束的那张表） |
| `AssessmentApiTest` | 6 | 非事务集成测试：400 而非 404（不存在的评估结果）、`predictionWindowMonths` 5/61 被拒、DOCTOR 创建 403、完整闭环（POST → COMPLETED + `assessmentId`，GET 回读 `riskScore` 与 `reviewStatus`）、**同 key 双线程并发只产生 1 个任务且无 5xx** |
| `AssessmentServiceTest` | 5 | 纯 Mockito：非 `BusinessException` 的客户端异常 → 任务落 `FAILED` 而非卡 PENDING、序列化失败 → `FAILED` 且不写结果行、`" key "` 与 `"key"` 命中同一幂等域、库里 `riskScore=2.0` 的旧结果被 `parse` 拦下、`canView` 为假时 403 且不落库 |
| `AssessmentReviewApiTest` | 3 | 非事务：`ACKNOWLEDGED` 后查库确认 `review_status` 已提交、`@AuditLog` 真实写入 `audit_log`（不 mock `AuditService`）、PATIENT 复核 403 且不改数据、非 ADMIN 读审计 403 而 ADMIN 200 |
| `FollowUpApiTest` | 6 | 非事务：创建即 `PLANNED`、`PATCH` → `COMPLETED`/`CANCELLED` 查库确认、非法状态 400 且不改数据、不存在的 id 是 400（契约无 404）、无 `canView` 的 DOCTOR 在创建/修改/查询三个入口都是 403 |
| `GlobalExceptionHandlerTest` | 3 | `DataIntegrityViolationException` → 400（commit 期间数据冲突不得变成 500）；**行锁等待超时 / 死锁（`CannotAcquireLockException` / `PessimisticLockingFailureException`）→ 400"操作冲突，请稍后重试"**（文案中性，因为该 handler 对所有模块生效）；**无法解析的 multipart → 400，且 `MaxUploadSizeExceededException` 仍走更具体的"超过大小限制"文案** |

总计 **241 个测试**，全部在 H2（`MODE=MySQL`）上通过。

响应同时被 `contracts/java-business.target.openapi.json` **本身**校验：`ContractSchemas` 读取契约文件、解析 `$ref`、按 JSON Schema 2020-12 并开启 format 断言。契约文件找不到时测试直接失败，不会静默跳过。

## 7. 接口地址

| 服务 | 地址 | 本 PR 是否调用 |
| --- | --- | --- |
| Java 业务 API（浏览器调用） | `http://127.0.0.1:8080` | 是 |
| Python 子服务 | `http://127.0.0.1:8091` | **是**（`RestAgentClient`；连接 2s、读 120s，均可用 `python.agent.*` 覆盖；不自动重试） |

本 PR 新增的数据导入端点（均需登录；`Idempotency-Key` 必填，1–100 字符）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/import-jobs` | `multipart/form-data`，唯一字段 `file`；校验并返回 `ImportJob`（预览） |
| `GET` | `/api/import-jobs/{jobId}` | 任务状态；仅创建者或 `ADMIN` 可读 |
| `POST` | `/api/import-jobs/{jobId}/commit` | 把预览通过的合格行入库；无请求体，无 `Idempotency-Key` |

本 PR 新增的评估 / 复核 / 随访 / 报告 / 审计端点（均需登录）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/assessment-tasks` | `Idempotency-Key` 必填；同步跑 Python 后返回终态任务 |
| `GET` | `/api/assessment-tasks/{taskId}` | 任务状态与阶段耗时 |
| `GET` | `/api/assessments/{assessmentId}` | 评估结果（PATIENT 403） |
| `POST` | `/api/assessments/{assessmentId}/review` | 人工复核 |
| `POST` | `/api/follow-ups`、`PATCH /api/follow-ups/{followUpId}` | 随访创建与状态变更 |
| `GET` | `/api/subjects/{subjectId}/follow-ups` | 某档案的随访列表 |
| `GET` | `/api/reports/{assessmentId}` | 报告视图 |
| `GET` | `/api/audit-logs` | 审计列表（仅 ADMIN） |

所有响应都是统一 `Envelope`，成功固定 `code=0`、`errorCode=null`：
```json
{
  "code": 0,
  "message": "成功",
  "data": { "id": 1, "username": "admin", "roles": ["ADMIN"], "menus": ["audit", "system", "users"] },
  "errorCode": null,
  "traceId": "3f1c9a2b7d4e4f0a8b6c5d3e2f1a0b9c",
  "timestamp": "2026-10-12T00:20:00.123Z"
}
```

`data` 是 required：无载荷时也必须出现且为 `null`，不得省略。每个响应都带 `X-Trace-Id` 响应头（与 body 内 `traceId` 一致）；调用方可用该请求头透传自己的追踪 ID，格式须匹配 `[A-Za-z0-9._-]{1,64}`，否则会被替换为服务端生成值。

## 8. errorCode

`errorCode` 是稳定字符串，**等于 `ErrorCode` 枚举名，改名属于破坏性契约变更**；`code` 与 HTTP 状态码一致。成功恒为 `code=0` / `errorCode=null`。

| errorCode | code / HTTP | 触发场景 |
| --- | --- | --- |
| `VALIDATION_ERROR` | 400 | `@Valid` 校验失败、参数类型不匹配、缺少必需参数 |
| `MALFORMED_JSON` | 400 | 请求体无法解析，或包含契约未定义的字段（`additionalProperties: false`） |
| `AUTH_INVALID_CREDENTIALS` | 401 | 登录被拒：用户名不存在 / 密码错误 / 账号停用，三者提示完全相同 |
| `UNAUTHENTICATED` | 401 | 未登录或会话已失效 |
| `ACCESS_DENIED` | 403 | 已登录但无权：安全链规则拒绝，或服务层对象级拒绝 |
| `NOT_FOUND` | 404 | **仅**表示未匹配任何路由；不用于缺失的业务资源 |
| `METHOD_NOT_ALLOWED` | 405 | 请求方法不被支持 |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | 请求体不是 `application/json` |
| `INTERNAL_ERROR` | 500 | 未预期异常；详情只进服务端日志，不回给客户端 |

说明：冻结契约只为在范围内的操作声明了 400/401/403。404/405/415/500 用于框架在进入 Controller 之前就可能产生的拒绝或失败，否则错误体将不是 `Envelope`。**缺失的业务资源不用 404**：契约没有为业务操作声明 404，各模块用 400 + 模块自有错误码（例如档案模块的"档案不存在"）。

## 9. menus 词表

`CurrentUser.menus` 在契约里只是 `array<string>`，**没有枚举**，因此下列 code 是团队约定而非契约保证，**需前端确认**。后端按角色下发，前端负责 code → 路由 / 文案的映射。

| code | 对应区域 | 角色 |
| --- | --- | --- |
| `users` | 用户与角色管理 | ADMIN |
| `system` | 模型配置与系统状态 | ADMIN |
| `audit` | 审计日志 | ADMIN |
| `subjects` | 档案列表与详情 | RESEARCHER、DOCTOR |
| `imports` | CSV 预览与确认入库 | RESEARCHER |
| `quality` | 质量检查 | RESEARCHER |
| `tasks` | 评估任务 | RESEARCHER |
| `graph` | 条件图谱与解释 | RESEARCHER、DOCTOR |
| `reviews` | 人工业务复核 | DOCTOR |
| `followups` | 随访计划 | DOCTOR、PATIENT |
| `reports` | 报告导出 | RESEARCHER、DOCTOR |
| `summary` | 患者摘要 | PATIENT |

多角色账号取各角色菜单的**并集**，去重后按字母序排列；未知角色不贡献菜单，也不会导致登录失败。`roles` 同样按字母序返回。顺序**未定义**，调用方不得依赖。

菜单只是界面可见性提示。所有权限都在服务端再次校验——隐藏前端按钮不构成访问控制。

## 10. 演示账号

以下账号是**合成课程数据**，由 `V2__seed_synthetic_accounts.sql` 写入，密码统一为 `DemoPass!2026`（BCrypt 强度 10，五个账号各自独立的盐，避免从哈希看出密码相同）。

| 用户名 | 角色 |
| --- | --- |
| `admin` | ADMIN |
| `researcher` | RESEARCHER |
| `doctor` | DOCTOR |
| `patient` | PATIENT |
| `research_doctor` | RESEARCHER + DOCTOR（多角色账号） |

⚠️ **这些口令仅为课程演示公开使用，不是真实凭据。任何真实数据环境都不得沿用它们**；上线前必须删除或替换这些账号，并改用环境变量或密钥管理提供凭据。仓库里只保存哈希，明文只出现在本文档中，因为它是刻意公开的演示口令。

当前没有任何 `subject` / `subject_permission` 种子数据：档案由后续的 CSV 导入 PR 写入，授权管理接口也尚未实现。因此 `DOCTOR` / `PATIENT` 在全新库上没有任何档案可见。

## 11. CSRF 取舍（本次 PR 明确记录）

本 PR **关闭了 Spring Security 的 CSRF 防护**（`SecurityConfig` 中的 `csrf().disable()`），并且**没有实现任何 CSRF token 防护**。这是课程范围内取舍，不是已完成的安全能力，不得当作"已防 CSRF"使用。

原因：共同契约 [java-business.target.openapi.json](../contracts/java-business.target.openapi.json) 把会话定义为一个 `JSESSIONID` Cookie（`securitySchemes.sessionCookie`），并且 22 个操作里**都没有声明 CSRF token 的请求字段、响应头或获取端点**。浏览器端无法从契约内取得 token，所以开启 CSRF 防护的结果是前端的每一个写操作（包括登录本身）都返回 403，而不是换来真实防护。

残余风险：会话凭据由浏览器自动随 Cookie 发送，用户已登录时，恶意页面可以伪造写请求（导入、创建档案、复核、随访等）。目前没有任何服务端 token 校验来区分这类请求。

要真正开启，需要先走共同契约变更 PR：新增 token 下发方式（例如 `XSRF-TOKEN` Cookie 或 `GET /api/csrf`），前端改为回传请求头，然后 Java 侧启用 `CookieCsrfTokenRepository`。改完之前不要把这里的配置描述为已具备 CSRF 防护。

另外，本 PR **没有**显式设置会话 Cookie 的 `SameSite` 属性，沿用容器默认值；这同样是待办，不是已完成的缓解措施。

## 12. 未完成项

- 契约 22 个操作，目前**契约内已实现 19 个**（认证 3 + 档案 3 + 访视 1 + 导入 3 + 评估任务 2 + 评估结果 1 + 人工复核 1 + 随访 3 + 报告 1 + 审计 1），另有 **3 个质控扩展操作**（`GET /api/qc/list`、`POST /api/qc/{id}/audit`、`GET /api/qc/stats`）。**未实现**：`PATCH /api/subjects/{subjectId}`（修改档案）、`POST /api/subjects/{subjectId}/features`（写入特征）、`POST /api/subjects/{subjectId}/quality-checks`（触发 Python 质量检查）。
- **档案/访视模块剩余**：授权管理接口（`subject_permission` 写操作）未实现；特征写入未实现（详情接口的 `features` 目前恒为空数组）；访视只支持创建，**没有修改或删除**（契约也未声明）。
- **访视分数的精度（双列语义）**：`raw_mmse`/`raw_moca`/`raw_cdr_sb` 是**权威**值，保存提交数值的**规范化文本**（`BigDecimal.toString()`；`07.50`→`7.50`、`1e1`→`1E+1`、`+1`→`1`、`-0.0`→`0.0`，**精度不丢、字面量不保留**），接口返回它；`mmse`/`moca`/`cdr_sb` 是**派生**列，等于 `round(raw, 2)`，仅供展示、列表与 SQL 统计，不参与评分。因此 `27.555` 会被接口原样返回，而 DECIMAL 列是 `27.56`。两者的派生关系由实体构造函数一次完成，`VisitApiTest` 还有一条**全表不变量**断言 `mmse == round(raw_mmse, 2)`。**V4 的回填不可逆**：V1–V3 期间写入的行早已被舍入，回填只能把"库里仅存的舍入值"复制到 `raw_*`，无法还原原始输入。`raw_*` 为 NULL 的行（手写 SQL、或回填遗漏）读取时退回 DECIMAL 列，不会返回 `null`。入口用 `@Digits(integer = 2, fraction = 61)` 拦掉超出 `VARCHAR(64)` 的精度，避免数据库报错或（MySQL 非严格模式下）静默截断。
- **FR-AUDIT-01 部分完成**：`@AuditLog` + AOP 切面 + `GET /api/audit-logs` 已实现（复核接口已接入，审计行在独立事务里提交），但**登录成功/失败仍只写日志、未写 `audit_log`**，其余业务操作也尚未加注解。日志不等于审计。
- **FR-AUTH-02/03 部分覆盖**：角色管理接口未实现；档案对象级权限已在 `SubjectAccessPolicy` 中实现但授权管理端点缺失。
- **`Idempotency-Key` 已在两处实现**：`POST /api/import-jobs` 与 `POST /api/assessment-tasks`（均走 `idempotency_record` + SHA-256 请求摘要，`operation` 区分模块）；其他声明了该请求头的操作尚未实现。
- **特征模块仍未实现**：没有特征读取端点（详情接口的 `features` 恒为空数组）；导入是当前唯一写 `subject_feature` 的途径，且通过 JDBC 直接插入（该表的实体映射留给将来的特征模块）。
- **患者字段过滤只覆盖了访视分数**（FR-EXPLAIN-02）：PATIENT 的档案详情已不再返回原始量表分数（`visits` 恒为空），但评估结果中的**排序数值、图权重与内部阶段轨迹**仍需在后端过滤，目前未落实（属评估模块）。特征接入详情后也必须套用同一 `canReadRawScores` 判定。**评估结果目前对 PATIENT 直接返回 403**（尚未实现 `PatientAssessmentSummary` 的过滤视图），属"拒绝"而不是"过滤"。
- **Mock Python 的部分失败路径已覆盖**："客户端抛非业务异常 → 任务 FAILED""结果序列化失败 → FAILED" 都有测试；但**超时、版本不匹配、409 `RUN_ID_CONFLICT`、BLOCKED 的 Mock 测试仍未做**，重启后的历史查询（对账）也未做。
- **CSRF token 防护未做、`SameSite` 未显式配置**（见第 11 节）。
- 后端 CI 已添加（`.github/workflows/backend-build.yml`），但**从未在 GitHub 上实际跑过**。

## 13. 未验证项

1. **MySQL 8 上的迁移与运行**：本机无 MySQL 服务、无 Docker，`V1` / `V2` 与全部测试都只在 H2 2.3.232（`MODE=MySQL`）上验证过，MySQL 分支从未执行。
2. **`application-local.yml` 的连接串**：从未连接过真实 MySQL。
3. **第 5 节的启动命令**：`spring-boot:run` 与 `java -jar` 均未实际执行过。
4. **`ddl-auto: validate` 只在 H2 上生效过**：它现在真实检查已映射实体与 DDL 的一致性（`sys_user`、`sys_role`、`user_role`、`subject`、`subject_permission`、`visit`、`data_import_job`、`idempotency_record`），但结论不能外推到 MySQL 的类型名。这一点对 `visit` 尤其重要：三个分数列是 `DECIMAL(5,2)`，实体必须映射为 `BigDecimal`，映射成 `Double` 会在启动时校验失败；对 `data_import_job.preview_csv` 尤其重要：H2 把 `TEXT` 映射成 `VARCHAR`，MySQL 是 `TEXT`（65535 字节），MySQL 上的 validate 结论未知。
5. **`visit_code` 的唯一性在 MySQL 上与 H2 行为不同**：MySQL 8 默认排序规则 `utf8mb4_0900_ai_ci` 大小写不敏感，`'BL'` 与 `'bl'` 在 MySQL 上是同一个键；H2 的 `DATABASE_TO_LOWER` 只影响标识符、不影响值，因此两者在测试中是不同的键。所以"大小写变体算不算重复"**无法在 H2 上验证**（`subject_code` 存在同一问题）。为此 `VisitService` 会捕获 `DataIntegrityViolationException` 并返回 400，而不是 500。
6. **CI 工作流未运行过**：`actions/setup-java` 的 Maven 缓存与 `chmod +x mvnw` 步骤仅经人工核对。
7. **`mvnw` 的可执行位**：本仓库在 Windows 上添加，`core.filemode=false`，因此 `mvnw` 会以 `100644` 提交，Linux 上 `./mvnw` 会报 Permission denied。CI 用 `chmod +x mvnw` 规避；也可以 `git add --chmod=+x backend/mvnw` 从根上解决。
8. **`V5` 与导入模块只在 H2 上跑过**：`ADD COLUMN`（含 `TEXT`）只在 H2 2.3.232 `MODE=MySQL` 上执行过，MySQL 8 从未执行；`preview_csv` 的 `TEXT` 容量（65535 字节）足以容纳 30000 字节上限，但没有在 MySQL 上实测。
9. **`spring.servlet.multipart` 的 64KB/128KB 上限没有自动化覆盖**：MockMvc 自行构造 multipart 请求，绕过 Servlet 容器的尺寸检查，因此 `MaxUploadSizeExceededException → 400` 这条映射只经人工/配置核对；`ImportJobApiTest` 断言的是解析器自己的 30000 字节上限。
10. **跨表质量规则没有在 Java 侧验证**：24 个月窗口、索引日多访视、同日特征冲突等仍由 Python 预检负责，Java 只做单表规则；两边规则是否会漂移尚无对照测试。
11. **浏览器实机联调未做**：Cookie 属性、跨域、前端拦截 401 等均未在真实浏览器验证。
12. **V4 双列与原始分数过滤只在 H2 上验证过**：`V4` 的 `ADD COLUMN` 与**隐式转换**回填（刻意不用 `CAST`，MySQL 不接受 `CAST(... AS VARCHAR)`）只在 H2 2.3.232（`MODE=MySQL`）上执行过，MySQL 8 未执行。MySQL 非严格 `sql_mode` 下 `raw_*` 超长是否静默截断也未验证——入口已用 `@Digits(fraction = 61)` 拦截，但该拦截本身同样只在 H2 上验证。列元数据有断言（`raw_*` 为长度 64 的字符列、派生列 precision=5/scale=2），也跑在 H2 上。`27.555` 的原值往返、全表不变量、以及按角色+按档案的 `visits` 过滤同样只在 H2 上验证；真实浏览器端到患者视图的联调未做。
13. **并发提交的行锁只在 H2 上验证过**：`ImportJobCommitConcurrencyTest` 用两个线程证明"只有一个 commit 成功、特征只插入一次"，但行锁语义来自 H2 的 `SELECT ... FOR UPDATE`；MySQL 8 的 InnoDB 行为（以及锁等待超时时长）未实测。另外 `preview_csv` 目前没有过期清理——未提交或 `BLOCKED` 的任务会一直保留上传原文，属已知的留存问题（建议后续按时间清理）。
14. **业务时区在代码里固定为 `Asia/Shanghai`**：`ClockConfig` 用一个常量定义业务日，未做成可配置项。若部署到其它时区的环境，需要改代码或把 `Clock` bean 改为读配置。空特征值写库时显式使用 `Types.DECIMAL`，但仍只在 H2 上验证过。
15. **CSV 换行符**：解析器识别 LF 与 CRLF；仅用孤立 `\r`（旧 Mac 格式）换行的文件，其后的 `rowNumber` 会偏小——属已知限制，未做处理。
16. **`raw_*` 是数值的规范化文本，不是字面量**：`BigDecimal.toString()` 会去掉前导零、改写指数形式、合并 `-0.0`（`07.50`→`7.50`、`1e1`→`1E+1`、`-0.0`→`0.0`）。**数值精度不丢**（这是 V4 要解决的问题），但若将来审计需要"逐字复现用户输入"，必须改为保存原始单元格文本（会让实体与 `ImportRow` 各多 3 个字段，本 PR 未做）。
17. **commit 提交前 GET 可能读到旧状态**：`commit` 持有 `data_import_job` 行的写锁，而 `GET /api/import-jobs/{jobId}` 是普通的 MVCC 快照读（不加锁、不阻塞）。因此在 commit 事务提交之前的极短窗口内，GET 仍会返回 `PREVIEW_READY`。这是数据库隔离级别的正常表现，不是 bug；调用方若需要"提交后立刻确认"，应以 commit 的响应体为准。
18. **入库不可撤销**：commit 成功后没有任何 API 回滚路径（契约也没有声明），已写入的档案/访视/特征只能人工清理。同一批导入的档案共享一个 `data_version`（`demo-xxxxxxxx`），可作为手工回滚的抓手（例如先按 `data_version` 圈定档案，再删除其访视/特征）。再次 commit 返回 400「当前状态不可入库」。
19. **客户端超时 ≠ 事务回滚**：commit 的 HTTP 请求超时或被客户端中断时，服务端事务**可能仍会完成并提交**。此时**不要重试 commit**（会得到 400），应调用 `GET /api/import-jobs/{jobId}` 确认 `status` 是 `COMMITTED` 还是 `PREVIEW_READY`。
20. **多角色优先级不对称**：写权限 `canCreate` 取**并集**（ADMIN 或 RESEARCHER 任一命中即可导入），而原始量表分数 `canReadRawScores` 由 **PATIENT 一票否决**。因此一个 ADMIN+PATIENT 账号可以导入数据，却读不到自己导入的原始分数。这是有意的安全基线（敏感数据收紧、写操作取最大授权），不是缺陷。
21. **连接池耗尽返回 500**：未显式配置 Hikari（默认池大小 10、连接等待 30s），耗尽时抛 `CannotGetJdbcConnectionException`，没有专门映射，落到兜底 handler 返回 500。属基础设施故障；契约没有 503，因此未做该映射。
22. **`GET` 存在性预言机**：`GET /api/import-jobs/{jobId}` 对不存在的 id 返回 400、对存在但无权返回 403，所以任何已登录用户都能区分某个自增 jobId 是否存在（不含内容、不含归属）。与档案模块的既有约定一致，属有意取舍；若需消除，可把两条路径都返回 400。
23. **PENDING 任务没有对账**：进程若在"写入 PENDING"与"写入终态"之间崩溃，任务会停在 PENDING。`runId` 已持久化，可以拿它去 Python `GET /runs/{runId}` 补齐，但本轮没有实现定时对账任务。
24. **评估失败原因未持久化**：`assessment_task` 没有 `error_code` / `error_message` 列，`FAILED` 任务只在当次响应里带原因，重新查询时两者为 `null`。需要一条新的 V9 迁移补上这两列。