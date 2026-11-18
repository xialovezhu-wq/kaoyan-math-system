---
name: kaoyan-math-question-worker
description: 数学单题、概念公式与局部纠偏。按当前作答、有界摘要及教材条件讲清考点考频和解法，在当前聊天左侧打开获准的本题 HTML。
---

# 数学单题讲解

<!-- t3-study-panel:begin -->
在真实 T3 对话中，每次讲解、追问解答或快存回顾按宿主安装的 T3 学习分栏合同实际打开或刷新本题左侧 HTML，与右侧聊天各占一半。保留本轮授权范围和原生保存回执，复用当前线程的浏览器标签。
<!-- t3-study-panel:end -->

直接使用用户当前学习模型，不切换模型、推理档位或会话。高数、线代、概率均适用。先核题号或临时题目身份、当前小问、作答与允许的提示层级。尚在独立思考时等待本人作答；明确要求讲解时，在已授权范围内直接解释。

## 从当前证据开始

首次诊断在本机取得同题同点、相应视图的有界摘要或明确的查询缺口。工作区已知时直接使用项目根；需要定位见[本机路径](references/local-paths.md)。常用入口如下。

~~~sh
python3 错题知识网络/scripts/math_teaching_context.py --repo . resolve --for-teaching --audit-context --concept '已核规范细点或稳定键' --operation '本题小问与当前动作' --view after_attempt --max-bytes 4500
~~~

已有正式题号或印刷题号时分别加 `--formal-id` 或 `--source-question-id`。根据当次实际权限选择 protected、after_attempt、direct；作答后仍按已解锁的小问讲。尚在保护阶段，题面、图、文件名、控件及隐藏数据都只能包含本轮可见的信息。

在本轮上下文中按发生顺序串起**题设条件、本人首答、助手提示或解释、本人随后做了什么、后续更正与原始来源**。未作答或只看过讲解时记未观察。提示后修正只支持当次提示下的操作。用已有 memory_context、personal_records、claims、step_evidence 和原消息核角色、范围、时间和来源。保留原句中的否定、量词与条件。历史断点不能直接判本轮复发，晚导入的旧材料沿原学习时间归位。摘要、模型说明和场景状态只供定向解释；来源缺失或冲突时保留未知。

同题同点、同视图、同一请求形态且没有更新信号时复用完整已读材料。只有手中还有同版完整正文时才传 `--known-version`。来源换版、范围变动或原返回不完整则新读并追加。选择候选、取方法原页、读取历史、处理预算缺口时按[查询与恢复](references/teaching-query.md)；查询失败不等于新题。涉及原会话出处见[证据和角色](references/current-question-evidence-v2.md)，须重开原件时用[精确定位](references/raw-archive-reopen.md)。

## 把线索接到解法

实质讲解先报已核考点、来源高/中/低频等级、同卷同题去重的 question_count 和统计范围。仅有父主题时明示父范围；未单列或未核实则说明缺项。题面等待和可能泄题的统计服从答案保护。

保留已经做对的步骤。指出**哪个题面线索触发选法、该方法的条件为何成立、由这一步怎样推出下一步**。题目自带解析优先，用户明确选定的合法路线优先；选填技巧优先检查成立范围。缺公式就给当前需要的公式，缺桥梁就补该步推导，不强迫用户猜公式。讲清知识点的意义和易错条件，考评须落在本人实际展示的步骤。只有用户明确要求卷面写法时提供，使用原题变量和连续等式或推理。公式保留定义域、参数范围、可微性、内点或边界、量词、正负号、单位和必要/充分方向。聊天行内用反斜线圆括号，独立公式用成对双美元定界符并前后留空行。

短追问只处理一个断点，通常争取 20–30秒内交付实质讲解。复杂展开见[本轮讲法](references/teaching-turn.md)、[考试方法与卷面](references/exam-methods.md)和[扩展教学](references/extended-teaching.md)。调用已核公式用[公式记忆](references/formula-memory-v1.md)，排版用[聊天呈现](references/chat-presentation.md)。

给某题答案、思路或纠偏时在**当前聊天左侧打开本题 HTML**，右侧给文字、原生公式及可重开的链接。按[侧栏交付](references/sidebar-delivery.md)复用题目、焦点及授权视图。方法树和分步推导按[数据入口](references/teaching-turn.md#解题思路的数据入口)生成。微调只做一次主宽度渲染与检查。确有帮助的固定反例用[已有场景](references/visual-recipes.md)；本轮点名 iPad 时再查[iPad 三维投送](references/ipad-geometry.md)。

## 结束当前题

用户需要的考点、条件、推导和小结在教学阶段完成。“保存并回顾”时先复用本题已读内容给[教学回顾](references/question-recap.md)，再把已展示的回顾与首答、提示、订正、原图一并交[快速保存](../kaoyan-math-wrong-intake/SKILL.md)。单纯保存沿用已有讨论，缺卷面不补写。仅在明确保存、或已授权逐题保存队列中用户明确结束/下一题时封存。成功后给原生回执，并执行已请求的导航。普通讲解与所有晨间复盘均不正式评分，不把显示反馈计作掌握。实际核对正确的数学作答单元可按既有约定调用一次官方 confetti。

正式编纂按请求交[本地增强](../kaoyan-math-enhancement-intake/SKILL.md)或[日终收口](../kaoyan-math-nightly-qa/SKILL.md)；独立 B 复盘走本科独立复盘入口。
