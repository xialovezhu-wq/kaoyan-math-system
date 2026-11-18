# 方法、步骤证据及资料复核

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

逐小问回对原文及历史作答。前题回顾和本题题面同处一个消息时，记录归属当前小问的具体句段。新旧作答作用域一致时核对提示先后，保留曾独立做对的操作和后来复发的条件。审核短摘要时，将需要保留的旧误解及其已核纠正、适用对象和必要条件、实际作答的提示依赖写成同一可审阅单元，逐项绑现有原件及修订依据。教材结论、本人表现和助手提示分开。不同条件下成立的记录并存；同范围冲突未决时显式保留，不按导入先后选真。没有足够证据时说明缺口，保留原件，不把观察开头、提示后改答或候选来源当作可迁移结论或独立表现。

维护时分别核对学习日期、获知日期、有效范围与更正前驱；同一作用域的证据冲突保留显式冲突，不按文件修改时间强选“最新”。对错误归因的更正须影响有效观察、相关逐点计数和依赖判断，原证据保留，评分与调度不随资料维护改变。

日终复用 nightly-qa 的全库个人摘要投影刷新。按实际解法核对一题中的先后依赖，标明上一步成果、下一步动作、适用条件及精确来源；两端可超出本批题卡标签。依证据走原生 accept 或 accept-maintenance。最终分别验回摘要重算与语义修订、已审核步骤连接和同版全库向量覆盖。
