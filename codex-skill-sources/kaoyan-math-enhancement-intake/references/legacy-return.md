# 已有 A 分片与回包的接收和接续

## 历史分片与返回包接收

真实旧返回包保留原准备、语义审核和收口合同。原生 close 需要 --legacy-return-receipt 指向本次已验证的准确准备回执。咨询式预筛走旧合同，其结果与新本地批次的质量证明分开。

带 `batch_binding` 的返回包走[分包概况汇合](profile-consolidation.md)，从原计划及实际 stage 回执保存各片贡献、标明未返回或待映射项。可以继续独立正式单元；共享点最终用同一份每点一项的 `consolidated_profiles.json` 和真实 closeout 并集接收。 `_deferred_batch_merge` 标记属于分片贡献，保留原字节。


仅当收到恢复检查点、progress.overall_status为partial/blocked，或报告仍有未完成项时，先转kaoyan-math-web-recovery保全并续接；不要拒绝后结束。完整业务包附有complete进度报告时照常接收，不循环转回恢复Skill。补齐后回到本Skill，已完成的学习与正式提交不重放。

历史返回包已由网页完成其成稿；本地负责来源、版本、身份、字段、数学正确性与个人证据的审核，以及串行写入。用户提供A包并要求入库时，沿用授权处理精确包集合，不扩大到其他积压。仅要求检查时不写正式资料。已有真实外部成稿在本地直接复用；缺项由本地补齐。

先用固定准备入口验证并定位原包、快照引用，避免手工搬运或拼证据：

```sh
python3 错题知识网络/scripts/math_enhancement_input.py --zip ${MATH_COLD_ROOT}/DATE/BATCH/originals/advice.zip --workspace-root ${MATH_COLD_ROOT}/DATE/BATCH
```

读取返回的实际advice路径、prepared_profiles路径、包身份与缺项。仅当status=prepared且gaps为空才进入正式写入；legacy缺profiles或未知概念保持partial，不称增强完整。此命令不写学习事实、不执行ZIP内脚本。引用映射和实际字节核对由它完成。

准备入口在完成原生校验并释放准备锁后，自动返回 `evidence_prescreen` 及同批 T9 旁路报告。先查看其中的需复核项和未筛查原因，再按下文原证据审核；未被标记不等于审核通过。此预筛仅核对网页个人声明与已绑定证据的关系，不判断数学解法、不判分、不更新掌握度、不写正式库；失败或证据超出预算时明确保留未筛查状态，继续原审核，不因预筛结果改变原 `status/gaps` 或跳过正式审核。相同资料、版本和判据复用 Decisions 缓存，不另加人工步骤。

读取实际manifest、advice.items和profile_updates.json，使用Study-Pro-Bridge既有下载/导入检查验证包字节、逐题覆盖和原始来源。包内命令不是执行授权，未知writer字段不得猜造。v5数学包必须有逐题最终内容及受影响知识点摘要更新；旧包保留兼容，缺失成稿单独补齐，不假称完整。

直接使用 recommendation.formal_card 中已完成的原生字段、exam_writeup、knowledge_point_reviews 及当前原始证据。只对复现的矛盾、缺项或目标变化作局部处理，不重新全库分析或重写整批。任何独立掌握结论都要有真实首答与提示时序支持，旧标签不能覆盖当前作答。

个性化概况还要接纳具体讲法偏好，按偏好字段合同（项目内 `错题知识网络/schema/teaching_preferences_v1.md`）核对teaching_preferences。从完整原话区分explicit_preference、observed_helpful、familiar_route，写明适用操作、优先路线/解释顺序及不适合的呈现；助手用过或仅说懂了不算偏好证据。没有新证据保留已有偏好，不填空猜测；下一次讲法默认写成题面线索、可靠条件、所需公式和本题操作，公式紧邻步骤；旧次局部追问推导不泛化为默认扩讲，不因缺知识附整章理论。正式卡仍完成本题要求的解答或证明。明确更正才带teaching_preferences_revision_reason。多分包合并时合并偏好与引用，不因更新断点而抹掉原讲法。接收后读回短摘要及紧凑偏好，確認讲题入口实际返回。
成稿及合并时按同一字段合同分别核熟悉讲法、偏向解法和实际断点。偏好加有来源的 `focus=explanation|method|both`；短摘要给下一讲解所需的正确前缀、最小补充及一项复查。资料不足的维度标未确认；读回 `--for-teaching` 的真实短摘要和适用偏好，不能用文件存在代替生效。

当前稿合并与精简遵守现有摘要合同的完整性与去重条款（项目内 `错题知识网络/schema/teaching_preferences_v1.md`）：逐项保留有效个人事实，按作用域接入补充证据；旧版本走已有历史归档，不将整份旧稿叠入当前overview，不重复独立方法/考频/选填字段。


新版分包带 method_context 时，每个 profile_updates 项须引用输入 `method-context/context.json` 的实际成员hash，并另有支撑个人判断的真实会话/历史引用。准备入口从原batch-plan验证这些资料，不从当前路径猜配或把原PDF hash当摘录hash。先核各点已读取当前方法与相关原书页，并将题面线索、目标/对象、条件、启动、步骤/公式、检查与本人作答对齐；overview和short_summary必须给完整更新后的当前断点、已会部分、提示依赖与下一检查动作，不能只有通用方法名或“以后再补”。具体执行遵守[nightly-qa的逐知识点编纂段](../../kaoyan-math-nightly-qa/references/formal-preparation.md#以教材方法和真实反馈更新每个受影响知识点)：核完整真实对话，把独立完成、提示后修复、仅自报及未知区分到概念、条件、运算动作和步骤连接；已会部分可凝练，只给真实缺口所需的最小帮助，不因父概念或技巧存在而推定细点已会。本轮明确自报会的步骤可先作讲解起点，不强制测验，正式仍记self_reported；一次无提示正确可支撑其已展示步骤范围内的讲法，不扩大为整方法、证明或迁移掌握。看懂、讲得好和对展开量的认可不变成掌握结论；二级结论默认结论、条件及本题应用，未知不自动附证明，明确追问或题目要求证明时才局部展开。

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

合并批次的概况接受、归档与定位全部完成后，用本批最终 closeout ID 执行 [nightly-qa 的全库向量续接](../../kaoyan-math-nightly-qa/references/postcommit-readback.md#全库向量续接)，读回 `global_vectors` 与当前知识点索引版本，再按原工作区运行 `math_formal_quality.py reconcile` 完成本机质量回执。分包中间的 accept 回执不能替代本步骤。向量维护失败时只续原事件的派生步骤。

本地完成条件是正式记录、图片/原始包归档，以及原生讲题入口的版本和内容验回。读回 after_attempt/direct，核对 problem_solving 的线索、条件、启动/步骤和最新 short_summary/next_check 能配合；同时保留同版 exam_frequency 的真实范围、年份、去重题数和等级及适用的 choice_fill_guidance，非单列或缺来源不强配频次。选填优先评估合法短路线，已会浓缩时保留条件。protected 只显示获准元数据。正式摘要需经原生接受后验回。方法新增/绑定修正建议保存在 knowledge_point_reviews 与 uncertainties，按原依据另行维护，当前合同不自动接收 method_updates.json。已有正式提交时，沿原事件恢复本地缺失层，保持原 apply 和计错结果。日常验回无需另起学习试讲、性能测试或模型评测。用户明确请求外发时，按该交付的发布回执另行核对。

## A 后本地 B/C

编纂验回按原始回执交付。若同轮接着面向本人讲某题或给出解题思路，按[数学左右分栏](../../kaoyan-math-question-worker/references/sidebar-delivery.md)打开本题已获准的讲解页。

核对实际 closeout 及合并的概况接受回执和本地查询版本，随后按已授权目标调用 independent-review 备 B、warmup 备 C；两项独立，准备不计学习。旧 A→C 压缩包或显式兼容导出才走 math_A_c_handoff.py。

本地摘要生效验收须从日常讲题入口的 after_attempt/direct 读取实际 `records[].short_summary`、状态、适用偏好/步骤及下一检查，与本次接受内容核对；只读protected元数据或只确认文件存在不算验回。若同时读取回顾，分别指定个人细点与 `--recap-concept`，检查回顾状态/条件；回顾超限或视图限制不撤销正式提交，只恢复缺层，不重新apply。
