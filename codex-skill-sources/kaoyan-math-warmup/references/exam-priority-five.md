# 次日题单的真实证据与验选

## 日期和弱点

目标日 D 固定用 D−1 的真实快存。先沿原始学习日完成相应的正式提交和个性化摘要接受，用现行摘要和快存原始对话交叉核对。补充 Capture 跟随真实题目，不重复制造错次。早于或晚于 D−1 的学习不作为本次目标，真实接触仍参与同题去重。

现行候选包为 `math-examstyle-five-candidates-v2`。覆盖模式的 `action_evidence` 收录当日有效的错答、卡住、提示后修复和独立正确逐点观测，`anchors` 给弱观测对应的摘要和同版考频。收到 `previous_day_formal_intake_pending` 或摘要缺失时先续已有正式入库，提交或摘要已完成部分不重放。无有效证据时保留实际缺项。参考题面、图和解析从已核来源读取，无法读原件的地方明示。

候选包的 `learning_inventory` 收齐当天每份 Capture、源包原话、正式目标和裁决。新计划的 `study_review` 以 Capture ID 为键逐项填 `formal_id`、`outcome`、`review`，记录核到的正确前缀、断点和未验证部分。同题补充接到同一次作答。某题无须练习也保留这项盘点。

## 考法与交付题源

- 参照是 2020–2026 含首尾的数一、数二、数三原题。读取 `真题数据库/papers.sqlite3` 的 questions 和 teacher_material，具体真题可用 `math_papers.py question --id ID`；只有内部审核才读 `--teacher`。参照编号可以和实际交付题相同，仍要独立过资格。不能由题目主题推定“考法相同”。
- 原题包括数二、数三，以及有证据表明本人做过的数一。覆盖模式可从已核原卷的 2009–2019 数二三选有近年同考法的原题。2019 年及更早的数一只可作实际练习候选，仍要真题身份、原始作答和 10 天间隔。已证实是合格真题的正式旧卡可复用原始安全题面；另编号不改变资格。
- 数一检查看原卷 ID、题图哈希、错题卡已核别名、跨卷共用整题和直接共享小问。新发现的同题先用原题、解析核为确实同一对象、条件与目标，再按既有身份桥重建，不能靠计划里一句文字放行。做过须由实际作答、正式错题/复做证据或可回原句的本人报告支撑。错题库有编号、已看过解析、题面展示、仅有导入、相似题做过都不能代替。共用小问不自动传播成另一整题做过。数一任一年缺先前作答证据都不交付，近年数一仍可作为后台考法参照。
- 初筛按 10 天：已做、真实展示与其他有据接触共同取最近实际日期，距 D 为 0–9 天排除，第 10 天可候选。同题关系传播接触；两道交付题不得共享已核小问。整题无提示独立正确仍按现行规则排除。已知接触但未核日期要查旧记录或本人原话；无接触记录不声称从未做过，也不能用于放行数一。
- 补题先核能否锚到真题实际要求的同一考查动作与训练方向，再选保留这些条件的旧错题或本地练习原题。共同公式、同章节、题名相似和可选的绕行解法均不足以证明同考法。题库标签未标全时，以题面和原解为准。对照可能承担覆盖的真题，记录同题、间隔、题源、结构或必要条件的拒绝理由。讲义题实际与真题同题时按真题身份及接触规则核。可用全题或独立且题面完整的小问，不从解析改写题干或把多题拼作一题。

2026 年覆盖用 `真题数据库/verified-year-coverage.json` 的实际已核原卷、完整题集、原件及 SHA；数二三同年需核数一。已有 1987–2025 数一及 2009–2025 数二三语料沿用实际身份。数一身份用全部已核年份检查。未读、待证、题源缺失和已确证不合格应分开；缺原卷时不声称优先池已经查完。

## 私有选题计划

使用项目根目录下 `数学一回滚复习系统/scripts/scheduler.py` 的 `warmup-candidates --date D --coverage` 与 `warmup-successor --date D --coverage`。明确题数上限时两边附相同的 `--count`。候选与私有计划放在经核验的 T9。需要补数一作答证据时可给候选入口 `--prior-attempt-file`，内容 schema 为 `math-warmup-prior-attempts-v1`，attempts 每条包含 question_id、basis=actual_user_report、capture_id、sequence、quote、last_attempt_date。只用已存用户轮次中的确切作答证据。优先复用原始日期，复核原话后才推断相对日期。入口核原始角色、轮次、内容、日期和整题身份。

用户确认看过旧清单时，核原话和实际可见题号。账本外的已核接触可由 `--recorded-exposure-file` 提供，本地清单 schema 为 `math-warmup-recorded-exposures-v1`，`exposures` 每条有 `question_ids`、`date`、`basis` 和原始 `source_ref`。只作为本次备题的接触证据，不写学习账本，也不升级为作答。

必要时用 `--practice-source-file` 加入本地书中的补题。T9 清单的 schema 为 `math-warmup-practice-sources-v1`，`exercises` 每条填固定的 `candidate_id`（`PRACTICE-` 前缀）、`locator`、`identity_review`、`identity_aliases`、`original_source`、`question_surface`、`private_solution`。来源三件均引用路径和 SHA-256，题面为 `original_image`。查真实接触和版次题号，列出已核重复错题卡 ID，和数一同卷或共享小问时走现有真题身份保护。只能以已核为不同的练习题进入补位。非真题须有相同考查方向和形式的独立原题参照。

语义计划 schema 为 `math-examstyle-five-selection-v2`，绑定 date、source_study_date 与 candidate_bundle_sha256，含 action_review、weaknesses、assessments 和 study_review。先完成证据与卡点，再对候选题记覆盖。覆盖模式由验选器产生 selected_candidate_ids。若提供该字段，须与实际结果一致。旧题单按原合同读取。

- `action_review` 每条填 action_id、operation、condition、evidence_ids。逐项读原话和提示顺序，覆盖候选包中每条 action_evidence。相同对象、操作和适用条件合为同一个 action_id，即使证据来自不同题、不同主题或同次补充。确有不同断点才拆开。原对话还有未登记的独立正确操作时，可加 `independent_evidence`，每个引文填 capture_id、sequence、quote。原话只支持见过、没展开或尚无法判断时，填 `insufficient_reason` 写明证据欠缺。同一动作有独立正确证据时从弱点清单剔除。
- `weaknesses` 每条填 weakness_id（同 action_id）、anchor_id、evidence_id、kind、detail、topic_id 和 frequency_basis。evidence_id 引用该动作已经审核的弱证据。kind 取 `knowledge_point`、`basic_formula`、`secondary_conclusion`、`solution_method`。选同版考频中能反映该动作考查的一个 topic_id，说明对应依据，确无合适统计项填 null 并说明。多个真实断点可用同一主题的参考考次，按具体动作分别覆盖。一个动作不因挂多个主题而重复计分，泛主题的考次也不能冒充细步骤的直接考次。

- 合格的 `match` 包含 candidate_id、review_method=complete_question_semantic_comparison、weakness_ids、weakness_basis、benchmark_question_id、comparison，以及实际题面与配对解析核验。comparison 分别写 mathematical_objects、conditions、target、key_actions、question_structure、differences。source_refs 包含这道候选、参照原件与本次使用的各条摘要/Capture 引用。旧正式卡另给独立的安全题面文件引用，不能公开含答案的卡。
- 数一审查用 math1_identity_review 保存 coverage_version、checked_years、comparison_basis、source_refs、same_question_ids。与数一排除名单无匹配用 status=distinct；已知有关数一身份且本人已做用 status=previously_attempted。缺乏先前作答的数一候选以双源同题证据剔除。未登记的新同题如果要交付，先重建候选与活动身份，再核日期。
- 真题已核不匹配用 `not_matching`，须实际读原题及解析、给明确拒绝理由和来源。已知确有接触却核不到日期可标 `contact_unverified`，给查过的来源和理由；没有翻过的候选仍为 pending。不得为获准补位把未审核的大批记录填成不匹配。
- 每个 `match` 的 `ordered_operations` 按实际顺序填 operation、condition、action_id，第二步起补 uses_previous。已审核动作填它的 action_id 和 scope_match，写清候选动作及条件如何对应原作答，其他动作的 action_id 填 null。顶部 weakness_ids 只列步骤中实际练到的弱点。已会步骤照常出现在流程中，独立正确的 action_id 不计覆盖。比如首答已完成标准化，卡在从标准正态求绝对矩，只让确实要求处理绝对矩的题覆盖该卡点。
- `topic_alignment` 每个高频卡点填 weakness_id、topic_id、operation_index（从 1 起的实际步骤序号）、basis、benchmark_question_id、exam_form。说明题设对象、条件、设问、共同动作与关键差别，原题面及解析列入 source_refs。topic_id 使用该弱点已审定的主题，步骤必须实际训练该卡点。无高频卡点贡献的题没有选择权重。
- `method_recurrence` 每项为 question_id、shared_operation、condition_and_difference；在 source_refs 绑定独立参照题的原题面和解析。候选自身及同题、共享小问不能计数。无独立参照时填空数组和 `no_repeat_reason`，不要改用章节标签充数。
- 对已核候选比较整组。优先覆盖高频卡点，按数一主窗口题数和近十年题数确定优先级。覆盖范围相同，先比较真题承担的卡点，再取题数最少的一组，必要时用独立复现区分。每道补题的 supplement_reason 写明合格真题未承担的考查动作及原因。缺口仍在时以 weakness_id 为键填 gap_review，写明已查范围与排除理由。最少题数只对经考法验选的候选成立。

公开入口只含日期、顺序、来源题号和安全题面。答案、近期原题参照、个人薄弱点与去重依据都留私有材料。已有开始的队列保持原合同；新产物标 `prepared_not_studied`。
