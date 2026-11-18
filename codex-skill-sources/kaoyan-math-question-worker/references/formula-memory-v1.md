# 已核公式调用

## 使用范围

当前数学题确实需要公式、二级结论，或为明确要求的本题教学回顾核对条目、进入晨间公式记忆训练时，按需读取本说明。公式、条件、代入和推导直接在聊天中用原生数学排版呈现；本说明只负责已有公式资料的读取，不启动额外显示流程。

## 活动公式库与逐题使用

练习使用现有practice_only活动规则及其aliases，继续检查practice_ready、真实题源和当前训练资格。教材讲解与回顾使用独立的reference_ready判定：数学内容和来源经核验即可成为参考候选，不再以已配到数一真题为必要条件。旧T9归档项必须先由资料编纂核验并发布到回顾入口，不能直接读取归档绕过审核，也不能全量解封。规则条目数不等于独立公式数或教材逐页审核完成度。

合并条目内variants保留各自数学条件、适用对象和原题具体形式。选当前题真正使用的variant，不能把不同版本条件相加或取最弱条件；只讲当前步骤需要的公式。题目关联或检索命中只是候选，不能认定当前解法用到了全部关联公式。

## 读取完整条目

本题讲解及快速回顾优先复用 `math_teaching_context.py resolve --include-recap` 的 `recap.basic_formulas`、`recap.secondary_conclusions`、`recap.solution_methods`。条目包含完整content、conditions、symbol_roles、source_refs、relation及reference_ready；读取正文后仍须核当前题条件。精确题目／小问映射优先，无精确映射时才用当前细点候选；相近词或关联题不证明适用。`recap.status=available` 仅表示至少有一组已核候选，须逐项检查 `query_coverage.matched_concepts` 与 `unmatched_concepts`。题号未绑定个人记录不影响独立读取已核公式；`no_match` 只说明此次标签或别名未命中，不等于库中不存在。可用已核同义名或条目ID作一次同范围修正。`unavailable`、`source_changed` 与保护限制保持各自含义，不用邻近主题顶替。

`formula_card.status=ready` 是该条当前来源的展示引用，`formula_card_refs` 是小型候选定位，均不扩大使用范围。独立公式请求可按精确已核 ID 用 `math_formula_cards.py query --id ID --view 当前视图` 读取卡片，依 `statement_sequence` 保留分支前提和原式顺序。`projection_pending` 只回同轮已核、已授权的原条目；不链接旧 HTML 或改读高权限视图。`checked_geometry_ref` 只用于已授权的同题同动作直接讲解；图的结论按回执区分推导和单构型核验。

教学阶段同次预取并在本题上下文中保留完整返回；同题同点同view、同include-recap形态且无更新信号时复用。首次追加include-recap或未持有完整返回时不传known-version；只有持有同形态完整结果才复用其组合版本。讲题前按当前权限有界读取；保存时复用已经展示的内容。预算不足只按required_min_bytes补足同一对象一次。实时不启动OCR、全库维护、外部模型或整章查找。

本地入口为 `错题知识网络/scripts/math_formula_registry.py`。`status`返回版本与覆盖；`query --id 真实FCE-ID --view direct --compact`读取教学所需内容；精确数学一原题可用 `query --question-id MATH1-... --view direct`取得已核候选。`--compact`保留公式、条件、变体、等价式、简要推导、本地审核和引用身份，省略重复内容及大段来源审计；需要核对某个来源时，才对同一精确ID移除`--compact`。

`--view`必须服从当前答案保护；默认`protected`只返回身份，recap三组数组为空，不能为了取得公式切换到未获准视图。after_attempt也不自动解锁最终答案或其他小问。按上面的本地 query 与原生训练资格核对当前版本；日常不等待云端。FCE和回顾条目都是参考资料，不是个人知识点或掌握记录。

新v3公式题使用当前item的`formula_entry_ids`；普通错题可用`problem_solving.formula_references`定位。只读本题主线真正需要的条目，先用`--compact`核对完整数学字段和变体；原题映射确需核验时，再读该精确条目的完整来源，不重复输出无关候选。`practice_ready`用于训练准入，不能用reference_ready替代，仍须核对本题条件；held、源漂移及未核内容不可作为已核参考。超出本题范围的内容不展示，重复条目按已有别名合并；题目联系的数量不代替`exam_frequency`。

## 在当前讲解中应用

先按真实首答和卡点选择一条主线，把适用条件、公式和本题代入写在相应步骤旁。可用`memory.recall_prompt`作当前唯一推进问题，问后等待；用户要直接讲解则直接讲，不机械让用户猜已知公式。

快速入库后的回顾固定为基础公式、二级结论、解题思路三段。前两段按整道题的已核讨论覆盖实际调用和用户明确请求重看的公式，不能只取最后一步。保留等式、求和起点、收敛或定义域及必要分支；二级结论按本题核心加同一小专题直接关联组织，不能用操作提醒代替公式。明确未在本题使用的补充条件，主结论与推论分层。解题思路由当前会话结合本题真实最终路线组织，不把通用方法表当作本人实际过程。无适用条目如实说明，不能用证明中间式凑二级结论；待证命题不能循环引用。回顾失败不重放Capture或改写原始保存。

只呈现当前题、当前授权层级需要的内容，下一题私有公式与答案不预载。公式会直接泄漏未解锁答案时，不因记忆训练放宽保护。资料调用本身不制造学习、评分、FSRS或掌握记录；真实回忆与应用表现沿原题完整Capture保存。
