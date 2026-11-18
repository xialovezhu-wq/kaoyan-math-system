# 向量、同版读回与资料维护

## 全库向量续接

After accepting the final profiles and completing the batch's archive/locator work, run the existing postcommit continuation once with the exact closeout ID and whole-catalog vector refresh:

```bash
python3 数学一回滚复习系统/scripts/math_postcommit.py \
  --repo . \
  --event-id EXACT_CLOSEOUT_ID --refresh-only --refresh-all-profiles --refresh-global-vectors
```

核对 `global_vectors.status=ready|noop`、与 `concept_index.version` 同版、可检索知识点和近邻来源的覆盖数，以及 API 新嵌入量和复用量。此步骤核对全库知识点，更新新建或实际文本变化的 OpenAI 向量，并从全库重算跨点候选，允许旧知识点召回本批新增或修改的相关知识点。没有变化的输入复用同模型、同维度和同内容哈希的向量，归档迁址不产生新学习。发给 API 的是已核数学名称、通用条件和方法片段，个人摘要、原话、图和作答细节留本机。Decisions 继续核正式入库实际取用的候选和成稿，不能把相似度或模型概率当作掌握证据。

日终从现有原生索引重算全库学习路径、讲题短摘要投影和引用状态。概况正文依真实证据更新：检查本批新观察、全库既有摘要及失效来源，并追到本批题解所涉的旧前置和后续点。每个可核的连接写明从哪个操作的产物进入下一动作、适用条件、实际题卡和证据源。两端需要更新时一并验回。记录本身只说明解题的前后依赖，个人独立、提示后或未知继续按各自证据判断。

用 profile 更新的 `solution_connections` 保存上述连接。当前 closeout 涵盖的点可走原生 accept；已提交之后，跨题目标范围或旧摘要修复用原生 `prepare/accept-maintenance`，只续概况，保持学习事实。方法总表换版时优先核真版本与本点绑定，证实相关内容未变后可重绑原字节快照；实际操作或个人依据有变化时针对变化重新核定。回执分别给全库重算数、语义更新数、两端验回和仍待核项。

用错题讲解原入口验回当前摘要及必要的旧关联点，确认候选只提供范围定位。向量待办单列 `global_vectors=pending` 与原因；正式业务已提交时只续该后置命令，沿用请求回执。没有同版成功回执不得声称全库向量已更新。


## 本机读回与质量回执

原件归档、概况接受和本机索引刷新后，在本批原工作区完成核验：

```bash
python3 数学一回滚复习系统/scripts/math_formal_quality.py reconcile --workspace DIR
```

学习用时由 math_study_timing.py 读取同一包的请求和完整回执。既有 trial 的历史回顾标记仅描述该时期。现行教学质量回到保存前已展示的教学轮核对，用时和回顾均不构成作答或掌握。

`reconcile` 在三视图验收之外，按日常 4,500 字节重新核对短摘要和下一检查，并保存实际返回字段。`reconcile` 实际调用 `math_teaching_context.py resolve --for-teaching` 对本批已接受的每个个人点读三个视图。`after_attempt` 和 `direct` 核对实际短摘要、下一检查及同一来源版本，`protected` 核对视图保护。通过后以 `VERIFIED_CURRENT` 和 `verification_basis=native_teaching_readback` 记录质量完成。已有正式提交只刷新本机缺层或续同一 `reconcile`。旧等待发布的批次也用原工作区继续。本地题单及复盘依据本机读回。真实旧网页回包的 close 仍可使用原生准备回执 `--legacy-return-receipt`。

用户明确要求远程访问或外发时，再走该交付要求对应的显式发布或打包入口。授权发布副本时，可用 `math_postcommit.py --event-id EXACT_CLOSEOUT_ID --publish` 请求副本。若要确认副本已达当前版本，发布后以 `study_publication.py verify-current --subject math` 的 `PUBLISHED_CURRENT` 验回。普通 `math_postcommit.py` 与兼容参数 `--refresh-only` 都只刷新本机。若同时核对回顾，按个人点与 `--recap-concept` 各自的实际范围处理。

## 方法v2与步骤证据接收

本地先读现行概况、方法和原页。仅处理旧包时，传输字段合同见三项目共同说明（共享目录 `../Study-Pro-Bridge/web-projects/A/MATH_WEB_ALIGNMENT.md`）及A字段合同（共享目录 `../Study-Pro-Bridge/web-projects/A/FORMAL_RENDERING_SCHEMA.md`）。读取methods、独立steps及依赖、conclusions的条件/例外/direct_use；旧方法与细分候选不等同，不按第一候选选路。选法先核当前题条件，再接本轮正确前缀、适用偏好和有据操作，不按拆分后的步骤个数计算熟悉率。

profile_updates现支持可选step_evidence。省略时原生prepare继承当前有效旧项；显式数组须完整保留仍成立旧观察再追加，不把本包增量当全量覆盖。state沿现有七类，scope限定对象/操作/条件；coverage缺省不补full_operation，partial_operation不证明整步掌握。结构化user/hint引文必须核原角色、轮次和逐字quote。嵌套source_refs与顶层引用一起映射并核验至最终稳定路径，不能只改顶层后留下staging路径。exam_brief和source_guards由本地投影，不接收为新学习事实。

删改旧步骤需step_evidence_revision_reason及真实依据，保留旧历史。accept对任何内容变化自动保存前驱版本，包括跨event更新；对已有观察或判断的归因更正仍经现有prepare/accept-maintenance提交精确更正裁决，不改原始事件，也不以新学习事件替代更正。普通缺省继承和保留旧项后追加不增加这一步。共享点跨片先汇合全部有效步骤、偏好、来源与最新事实，仍串行接受一份完整概况。

接收读回须同时核short_summary/next_check、teaching_preferences、step_evidence的作用域/覆盖以及exam_brief；预算省略整块不等于无记录。本地使用 math_teaching_context 的精确身份和 math_method_context 的方法/步骤目录，核对实际预算与原页。protected不暴露这些提示。不得为修引用或对齐方法新增学习、评分或调度事件。

## 按需资料提取与疑义复核（原入口）

本批 PDF、截图或网页原件辨识困难时，才复用 `../Study-Pro-Bridge/scripts/study_material_preprocess.py`：用 `../Study-Pro-Bridge/.venv-study-mcp/bin/python` 执行，传 `--subject math --source 原件绝对路径 --pages 1,3 --purpose reference`，purpose按来源角色选reference/question/user_work/solution；公开网页可用 `--url`，不带浏览器凭证。先本地文字提取，扫描页/图像按需调用视觉 API；不为清楚的资料重复增加一层模型。输出原件副本、提取稿和缓存走本科已核验 T9 冷目录，来源/hash/页码保持可追溯，不修改 Capture 或正式库。

`--review auto` 是默认，仅对提取疑义页追加 Decisions；已有明确疑义可用 `--review-pages 1,3`，页码必须属于本次 `--pages`，`--review off` 只跳过此旁路。它比较原页图与提取稿，提示可能漏项、混区、角色或文字不一致；HTML/TXT 没有原页图时明确未筛查。无疑义不默认每页复核；空白/过少内容等可程序核查的情况先用代码。失败保留已提取结果与未筛查原因，不重跑成功正式写入。

默认 `protected`，`after_attempt` 也只返回元数据；只有当前任务已授权读取该内容及相应答案范围时，才用 `--view direct --allow-answer-text`。正式审核授权不扩展到未来题、兄弟小问或其他答案。机器提取、疑义复核和回包 `evidence_prescreen` 是不同的派生辅助：均不替代实际核读原图、完整真实对话与本科语义审核；未标记不是审核通过，提示后完成不是独立掌握，缓存不是新学习。只将原证据支持的结论交既有唯一正式 writer，保留原日期、身份、原评分/掌握度与幂等恢复规则。

## 统一记忆的正式维护

数学统一记忆与读取合同（项目内 `错题知识网络/schema/math_memory_v1.md`）为本流程与讲题、快存的共同契约。沿用原 `profile_updates`；有逐项原始依据时填写可选 `claims`，已有偏好和步骤证据继续按原类型与作用域保留。旧稿缺少逐项依据时保持兼容和限制，不批量补造判断。概况接受、观察更正与实际做题是不同事件。

审核短摘要时，将需要保留的旧误解及其已核纠正、适用对象和必要条件、实际作答的提示依赖写成同一可审阅单元，逐项绑现有原件及修订依据。教材结论、本人表现和助手提示分开。不同条件下成立的记录并存；同范围冲突未决时显式保留，不按导入先后选真。没有足够证据时说明缺口，保留原件，不把观察开头、提示后改答或候选来源当作可迁移结论或独立表现。

维护时分别核对学习日期、获知日期、有效范围与更正前驱；同一作用域的证据冲突保留显式冲突，不按文件修改时间强选“最新”。对错误归因的更正须影响有效观察、相关逐点计数和依赖判断，原证据保留，评分与调度不随资料维护改变。

日终最终后置同时重算全库个人摘要投影、验已证跨点连接并刷新同版全库向量。同事件同版本复用已验证结果，派生层失败按原事件续办。后端性能评测只在系统改造或实际需要时运行。
