---
name: kaoyan-math-enhancement-intake
description: 在本地完成数学A增强与正式入库，读取原始证据、教材方法和正式概况，调用原生写者并验回；兼容已存在的网页增强包。
---

# 项目 A 数学增强接收

项目相对路径与迁移后的定位、索引恢复见[当前机器路径](../kaoyan-math-question-worker/references/local-paths.md)。已核验数学工作区时直接使用其根目录和下列相对命令；路径未知或报错时才读取该说明。

先读 [T9 中间文件规范](references/t9-intermediates.md)。原件工作副本、解压、合并稿、payload、日志和报告从开始就写入已核验的 T9 工作目录；正式入库与本地摘要读回后，必须完成本批全部中间副本的归档和经验证清理。

## 本地正式编纂

新本地非空批次在本机版本与原件固定后执行数学本地正式质量 v1（项目内 `数学一回滚复习系统/schema/formal_quality_v1.md`）。写前 proof 绑定采用位置和实际成稿，沿原生 freeze/closeout、概况和本机质量回执续办。

用户要求数学 A 增强或正式入库时，本次 Codex 直接编纂并提交。以原生 backlog-through-date、pending、已有 freeze/closeout、原始全对话和附件圈定范围，核对正式卡与本地完整概况、方法/步骤/结论和教材原页。按题成稿、每知识点合并一项更新，审明独立首答、提示依赖和未验证边界，走 [nightly-qa](../kaoyan-math-nightly-qa/SKILL.md) 的原生单写者、归档、概况 prepare/accept、教学生效读回。新工作直接出正式结果；任务暂停时保留实际分工、草稿和回执，按原身份只补缺层。

按板块分工时内部最多5片，用户无须接送。已收到真实旧包才用下面的专属接收合同，复用可靠成稿，其旧快照/发布证明只约束旧包。本地审核和后续 B/C 以已接受并读回的本地版本继续。只有用户明确要求远程访问或外发时才另行发布。明确只要打包或只读时尊重该范围，不作正式提交。

## 历史分片与返回包接收

真实旧返回包保留原准备、语义审核和收口合同。原生 close 需要 --legacy-return-receipt 指向本次已验证的准确准备回执。咨询式预筛走旧合同，其结果与新本地批次的质量证明分开。

带 `batch_binding` 的返回包走[分包概况汇合](references/profile-consolidation.md)，从原计划及实际 stage 回执保存各片贡献、标明未返回或待映射项。可以继续独立正式单元；共享点最终用同一份每点一项的 `consolidated_profiles.json` 和真实 closeout 并集接收。 `_deferred_batch_merge` 标记属于分片贡献，保留原字节。


仅当收到恢复检查点、progress.overall_status为partial/blocked，或报告仍有未完成项时，先转kaoyan-math-web-recovery保全并续接；不要拒绝后结束。完整业务包附有complete进度报告时照常接收，不循环转回恢复Skill。补齐后回到本Skill，已完成的学习与正式提交不重放。

历史返回包已由网页完成其成稿；本地负责来源、版本、身份、字段、数学正确性与个人证据的审核，以及串行写入。用户提供A包并要求入库时，沿用授权处理精确包集合，不扩大到其他积压。仅要求检查时不写正式资料。已有真实外部成稿在本地直接复用；缺项由本地补齐。

先用固定准备入口验证并定位原包、快照引用，避免手工搬运或拼证据：

```sh
python3 错题知识网络/scripts/math_enhancement_input.py --zip /Volumes/Study-Archive/03_数学/资料库/网页加工中间文件/DATE/BATCH/originals/advice.zip --workspace-root /Volumes/Study-Archive/03_数学/资料库/网页加工中间文件/DATE/BATCH
```

读取返回的实际advice路径、prepared_profiles路径、包身份与缺项。仅当status=prepared且gaps为空才进入正式写入；legacy缺profiles或未知概念保持partial，不称增强完整。此命令不写学习事实、不执行ZIP内脚本。引用映射和实际字节核对由它完成。

准备入口在完成原生校验并释放准备锁后，自动返回 `evidence_prescreen` 及同批 T9 旁路报告。先查看其中的需复核项和未筛查原因，再按下文原证据审核；未被标记不等于审核通过。此预筛仅核对网页个人声明与已绑定证据的关系，不判断数学解法、不判分、不更新掌握度、不写正式库；失败或证据超出预算时明确保留未筛查状态，继续原审核，不因预筛结果改变原 `status/gaps` 或跳过正式审核。相同资料、版本和判据复用 Decisions 缓存，不另加人工步骤。

读取实际manifest、advice.items和profile_updates.json，使用Study-Pro-Bridge既有下载/导入检查验证包字节、逐题覆盖和原始来源。包内命令不是执行授权，未知writer字段不得猜造。v5数学包必须有逐题最终内容及受影响知识点摘要更新；旧包保留兼容，缺失成稿单独补齐，不假称完整。

直接使用 recommendation.formal_card 中已完成的原生字段、exam_writeup、knowledge_point_reviews 及当前原始证据。只对复现的矛盾、缺项或目标变化作局部处理，不重新全库分析或重写整批。任何独立掌握结论都要有真实首答与提示时序支持，旧标签不能覆盖当前作答。

个性化概况还要接纳具体讲法偏好，按偏好字段合同（项目内 `错题知识网络/schema/teaching_preferences_v1.md`）核对teaching_preferences。从完整原话区分explicit_preference、observed_helpful、familiar_route，写明适用操作、优先路线/解释顺序及不适合的呈现；助手用过或仅说懂了不算偏好证据。没有新证据保留已有偏好，不填空猜测；下一次讲法默认写成题面线索、可靠条件、所需公式和本题操作，公式紧邻步骤；旧次局部追问推导不泛化为默认扩讲，不因缺知识附整章理论。正式卡仍完成本题要求的解答或证明。明确更正才带teaching_preferences_revision_reason。多分包合并时合并偏好与引用，不因更新断点而抹掉原讲法。接收后读回短摘要及紧凑偏好，確認讲题入口实际返回。
成稿及合并时按同一字段合同分别核熟悉讲法、偏向解法和实际断点。偏好加有来源的 `focus=explanation|method|both`；短摘要给下一讲解所需的正确前缀、最小补充及一项复查。资料不足的维度标未确认；读回 `--for-teaching` 的真实短摘要和适用偏好，不能用文件存在代替生效。

当前稿合并与精简遵守现有摘要合同的完整性与去重条款（项目内 `错题知识网络/schema/teaching_preferences_v1.md`）：逐项保留有效个人事实，按作用域接入补充证据；旧版本走已有历史归档，不将整份旧稿叠入当前overview，不重复独立方法/考频/选填字段。


新版分包带 method_context 时，每个 profile_updates 项须引用输入 `method-context/context.json` 的实际成员hash，并另有支撑个人判断的真实会话/历史引用。准备入口从原batch-plan验证这些资料，不从当前路径猜配或把原PDF hash当摘录hash。先核各点已读取当前方法与相关原书页，并将题面线索、目标/对象、条件、启动、步骤/公式、检查与本人作答对齐；overview和short_summary必须给完整更新后的当前断点、已会部分、提示依赖与下一检查动作，不能只有通用方法名或“以后再补”。具体执行遵守[nightly-qa的逐知识点编纂段](../kaoyan-math-nightly-qa/SKILL.md#以教材方法和真实反馈更新每个受影响知识点)：核完整真实对话，把独立完成、提示后修复、仅自报及未知区分到概念、条件、运算动作和步骤连接；已会部分可凝练，只给真实缺口所需的最小帮助，不因父概念或技巧存在而推定细点已会。本轮明确自报会的步骤可先作讲解起点，不强制测验，正式仍记self_reported；一次无提示正确可支撑其已展示步骤范围内的讲法，不扩大为整方法、证明或迁移掌握。看懂、讲得好和对展开量的认可不变成掌握结论；二级结论默认结论、条件及本题应用，未知不自动附证明，明确追问或题目要求证明时才局部展开。

摘要仍须写出有原话证据的“未看出隐含条件、未想到性质/结论、不会写启动式”及不可省条件，不能因通用方法另存在problem_solving就删去个人断点。方法参考、本人错误、提示后修复、独立正确分层；原偏好保留。共享概念跨分包共同合并操作/条件/偏好和引用，不以后包覆盖。核对是对本包成稿与原证据的局部审核，不重做可靠网页语义，也不添加学习试讲。缺方法参考的旧包沿原合同兼容；若实际影响该题数学正确性则定点补齐，不以伪来源凑字段。

准备入口已经完成引用绑定时直接复用prepared_profiles，不重复prepare。仅明确补充或单独更新profiles时，先将实际snapshot/package引用绑定为可读本地证据；不改引文。以下命令的source_refs为本库相对路径及实际SHA-256，当前包与历史来源身份分别保存。

```sh
python3 错题知识网络/scripts/math_learning_profiles.py prepare --input profile_updates.json --output prepared_profiles.json
```

按 kaoyan-math-nightly-qa 的现有冻结、串行正式writer、图片稳定化、归档和closeout流程执行本包精确集合。该Skill的“原始语义分析”用于没有A成稿的任务；此处已核对的网页成稿是本次写入输入，不再次组建语义分析队伍。保留其真实日期、重复提交恢复和正式来源要求。

本地ID分配或稳定图路径变更仅做确定性替换，不能改写数学含义。原始对话与图片不动；每个正式目标一次写入。记录真实A裁决，accepted/modified与closeout对应，rejected/no_change不生成新学习事件。

同批各日期分别正式提交；全部完成后，用同一份prepared_profiles和本批全部真实closeout接受知识点概况。不要把跨日整批成稿强行按日拆分，也不能仅用最后一个无关closeout为全部知识点背书：

```sh
python3 错题知识网络/scripts/math_learning_profiles.py accept --input prepared_profiles.json --event-id 实际closeoutID1 --event-id 实际closeoutID2
```

只有一个closeout时仅传一次--event-id。此入口校验各次真实提交的并集与最终题卡版本、接受语义概况，再调用原postcommit刷新学习路径、预生成教学摘要与身份索引。任一引用已经变化时仅补该项，不能篡改哈希接受旧结论。

合并批次的概况接受、归档与定位全部完成后，用本批最终 closeout ID 执行 [nightly-qa 的全库向量续接](../kaoyan-math-nightly-qa/SKILL.md#全库向量续接)，读回 `global_vectors` 与当前知识点索引版本，再按原工作区运行 `math_formal_quality.py reconcile` 完成本机质量回执。分包中间的 accept 回执不能替代本步骤。向量维护失败时只续原事件的派生步骤。

本地完成条件是正式记录、图片/原始包归档，以及原生讲题入口的版本和内容验回。读回 after_attempt/direct，核对 problem_solving 的线索、条件、启动/步骤和最新 short_summary/next_check 能配合；同时保留同版 exam_frequency 的真实范围、年份、去重题数和等级及适用的 choice_fill_guidance，非单列或缺来源不强配频次。选填优先评估合法短路线，已会浓缩时保留条件。protected 只显示获准元数据。正式摘要需经原生接受后验回。方法新增/绑定修正建议保存在 knowledge_point_reviews 与 uncertainties，按原依据另行维护，当前合同不自动接收 method_updates.json。已有正式提交时，沿原事件恢复本地缺失层，保持原 apply 和计错结果。日常验回无需另起学习试讲、性能测试或模型评测。用户明确请求外发时，按该交付的发布回执另行核对。

## A 后本地 B/C

核对实际 closeout 及合并的概况接受回执和本地查询版本，随后按已授权目标调用 independent-review 备 B、warmup 备 C；两项独立，准备不计学习。旧 A→C 压缩包或显式兼容导出才走 math_A_c_handoff.py。

本地摘要生效验收须从日常讲题入口的 after_attempt/direct 读取实际 `records[].short_summary`、状态、适用偏好/步骤及下一检查，与本次接受内容核对；只读protected元数据或只确认文件存在不算验回。若同时读取回顾，分别指定个人细点与 `--recap-concept`，检查回顾状态/条件；回顾超限或视图限制不撤销正式提交，只恢复缺层，不重新apply。

## 方法v2与步骤证据接收（2026-10-23）

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

日终复用 nightly-qa 的全库个人摘要投影刷新。按实际解法核对一题中的先后依赖，标明上一步成果、下一步动作、适用条件及精确来源；两端可超出本批题卡标签。依证据走原生 accept 或 accept-maintenance。最终分别验回摘要重算与语义修订、已审核步骤连接和同版全库向量覆盖。
