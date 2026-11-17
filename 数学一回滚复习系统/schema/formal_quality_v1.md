# 数学本地正式质量 v1

此流程用于新本地非空正式批次。快录、讲题、历史已提交批次和经原生校验的旧网页回包沿各自合同。正式业务身份继续使用原学习日、原 Capture、freeze、closeout 和概况接受。

1. 运行原生 backlog 和 pending，检查真实包、附件及旧回执，按原日 freeze。作者用本机材料写脱敏 scope，逐项绑定题面、附件 disposition 和实际回合。
2. 在经验证的 T9 工作区运行 math_formal_quality.py begin --workspace DIR --scope FILE。读候选内容、真实 Decisions 和来源，在实际成稿里落实采用位置。
3. 制作 draft 清单，列实际题卡完整草稿、逐点观察、教学 prior、每个 Capture 的正式裁决及合并后的 profile 输入。运行 requirements --workspace DIR --draft FILE，按生成的稳定位置逐项审稿。
4. reviewed 逐位置提供原声明哈希、证据单元及安全文本。受保护位置由本机逐项验回。候选逐项记录 action、position 和理由。运行 finalize --workspace DIR --reviewed FILE。QUALITY_PREPARED 才可将 proof 交给 quick_intake.py apply-formal-targets --proof FILE。
5. 使用图件稳定化、lint、wrongnet rebuild、回滚、SHADOW、Wiki、教学切片及 close。概况使用工作区的 prepared-profiles.json 及实际 closeout。概况接受、归档和定位完成后按原 event 用 math_postcommit.py --refresh-only --refresh-global-vectors，核本机读取、全目录向量覆盖与摘要状态。
6. 本机索引刷新后运行 `math_formal_quality.py reconcile --workspace DIR`。对本批已接受的个人点，以 `math_teaching_context.py resolve --for-teaching` 的原生入口验 `protected`、`after_attempt` 和 `direct`。两个授权视图的短摘要和下一检查与已接受概况匹配，受保护视图只留获准元数据。同一原生版本下生成 `VERIFIED_CURRENT` 质量回执，包含三个实际视图的版本和哈希。

候选和终稿使用 text-embedding-3-large 的 1536 维向量及 gpt-6-luna Decisions。输入只含经核对的客观数学文本和最少的角色转述。原题解锁状态、原图、原话、精确定位及个人历史留本机。按真实服务端请求和结果哈希证明覆盖。准备失败不开始正式写入，结果未知保留原请求身份。同批续接只用相同输入的有效回执。

候选池先保留精确身份，也可用兼容的全库向量定位同数学空间的旧知识点。仍按现有来源校验、条件和 Decisions 审核实际片段。全库向量后置失败记录为派生待续，使用原 closeout 和已有请求回执恢复。

scope 使用 `math-formal-quality-scope-v1`，含 `redacted: true`、`freeze_id` 和 `units`。单元使用 `capture_id`、`mechanism`、`objects`、`conditions`、`goal`、`exact_labels`、`turns` 和 `attachments`。每个回合仅提供 `sequence` 与脱敏 `text`，程序从真实会话重取角色。附件以原 SHA 为键，标为 `verified_question`、`verified_reference` 或 `archive_only`。

draft 使用 `math-formal-quality-draft-v1`。cards 中每项含 `formal_id`、仓库相对 `path`、工作区相对 `draft` 及 `operation`。observations、priors、outcomes 和 profiles 指向工作区中的 JSON。priors 以正式题号为键，outcomes 以 Capture 为键，值含原生 `outcome` 及作者裁决 `reason`。逐点观察和概况沿原生 schema。

已准备的 prior 若将 unresolved 写成字符串，物化时只把该原文本展开为 `evidence_origin=unresolved`、来源继承同一 prior 的 `first_break.source_capture_id` 的标准证据项。质量原稿与 proof 字节不改；close 比较这一规范表示，其他字段、原文本、来源或证据角色变化仍按漂移拒绝。新稿直接使用教学切片的标准证据项。

reviewed 使用 `math-quality-reviewed-v1`、`requirements_sha256`、`statements` 和 `uses`。statement 填原声明 `sha256`、`classification`、本地绑定的 `units` 及安全 `text`。受保护声明改填 `local_verified: true`。uses 以候选判断 ID 为键，使用 `adopt`、`revise`、`reject` 或 `keep_conditions` 并给 `position`、`reason`。有未决冲突的组留待审。日志中的概率用于标记待复查位置，作者回原材料判数学和学习事实。

新冻结的候选回执把同一次 Capture 的已核角色、顺序和原文 SHA 留在本机。向服务只送既有匿名投影；在精确、标签与向量候选中按来源去重。建议区分同一结论、条件不同、仅形式相似与证据不足；父任务读完整条件后才给 `uses`。原批次按原回执续办，外部调用失败不标为已完成。`verify-candidates` 可验证已落盘的真实回执而不重复调用服务。

需要把本次正式解释纳入公式阅读卡时，在原卡的「可迁移结论」下以「### 公式：已登记精确知识点名」标出独立结论，紧接「适用条件：…」和原式，必要时加「边界：…」。该段只放普适关系，不带当前题的代入、首答或答案。沿原 writer 提交后由 `math_postcommit.py` 生成展示；无充分条件留在正式原文里待核。

新 `frozen.json` 记录 `memory_review=scoped-learning-memory-v1`。其中的概况字段、逐点观察与教学切片须逐条对照实际题面、原始回合和适用方法，写 `local_verified: true` 后才按原安全范围请求终稿 Decisions；后者检查对象和必要条件、正确前缀、首个断点、关键提示前后、可支持的后续独立动作和仍未知的范围。冻结时没有该标识的旧批次保留原谓词和 proof。冲突或跨日依赖未齐时保存未决；精确定位需复核的定义、原题或前驱 closeout。

`status` 区分质量待核、原生写入待续、正式已提交待索引、本机读回或回执收尾待续、已验当前。已有正式评分、调度和归档按原事件续接。旧等待副本的批次使用同一工作区 `reconcile` 完成本机核验，已完成的历史回执按原字节保留。默认正式收尾刷新本机派生层；明确要求远程访问或外发时才单独执行发布或打包。

多日按原生日期组串行完成。先处理更早日期，同一正式题按原合同检查前驱和有授权的 source-verified 重绑，概况继承仍有效的较早版本。已有终态依其真正回执读取。
