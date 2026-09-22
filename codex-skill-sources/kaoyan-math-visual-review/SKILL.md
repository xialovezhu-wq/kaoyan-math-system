---
name: kaoyan-math-visual-review
description: "Create a 10–15 minute math daily-review narrative, structured Markdown, or local HTML artifact from verified study evidence. Use for 数学日终复盘, 生成可视化复盘, 10–15 分钟口播稿, or 把今天数学学习整理成 HTML/复盘稿. Ordinary review requests stay read-only; an explicit request for HTML, saving, or a finished artifact authorizes one safe review artifact, not edits to formal cards. Route single-question intake to kaoyan-math-wrong-intake and explicit unified redo selection to kaoyan-math-daily-filter. Chronicle may locate recent context but never serves as the sole evidence for IDs, wrong causes, time, mastery, or redo results."
---

# Kaoyan Math Visual Review

## Goal

把已验证的当天学习证据压缩成一条清晰复盘主线：今天解决了什么、错误模式是什么、第一动作缺在哪里、重点题如何说明问题、明天先做什么。

## Success Criteria

- 成品能在 10–15 分钟内讲完，重点围绕具体证据和下一步动作，不复制长题干或完整解析。
- 所有题号、错因、method_gap、掌握度、时长和复做结果都来自用户输入或稳定本地文件；缺失项明确标记。
- 单题正式写入和统一筛题分别交给对应技能；本技能只消费已经确认的卡片或 shortlist。
- 普通复盘不修改正式卡、`生成/`、回滚账本、wiki 或 Tutor。
- HTML 成品无外部依赖、可本地打开，并在交付前完成渲染检查。

## Authorization And Route

- “总结、复盘、口播稿”默认只在对话中输出。
- 明确要求“HTML、保存、生成成品”时，可在已存在的安全 review/wiki 目录创建一个成品；明确成品请求同时允许创建一个项目内安全复盘子目录；覆盖现存文件或越出本项目范围才需另行确认。
- 只有用户明确要求同步 Tutor 或刷新 StudyVault 时，才执行 `references/tutor-review-closure.md`。
- 混合请求中，当前题入库转 wrong-intake；显式统一筛题先转 daily-filter，再用其结果做复盘。

## Evidence Budget

先使用用户摘要、命名 formal IDs、现有 daily-filter 结果和相关 wiki/method_gap 页面。只有核心事实缺失时才扩大检索：

1. 用 Obsidian CLI 定位正式卡、wiki、backlinks 或安全保存位置；
2. 用户依赖“今天、刚才、当前屏幕”时，用 Chronicle 识别可能的主题、可见 ID 和应用；
3. 回到正式卡、wiki、视觉详情或用户文件验证最终事实。

独立读取可以并行；收齐后先形成一个规范化证据表，再写叙事。已有证据足以支持核心复盘时停止检索，不为增加例子或润色继续搜索。

有可独立验收的证据组时，由当前根任务选择原生只读分工；Ultra 不为开启并发加载自定义委派 Skill，不固定模型、人数、effort、fork 或 service tier。单题教学仍由唯一当前 Agent 完成。成品按用户要求的实时或成品分支完成必要视觉检查，不追加固定 QA 代理或无新问题的反复渲染。

## Output Route

根据请求选择一种主成品：

- Structured Markdown：脚本、提纲或聊天复盘。
- Single-file HTML：默认视觉成品；纯 HTML/CSS/Vanilla JS。
- 分离 HTML/CSS/JS：仅用户明确要求。

具体结构见 `references/output-structure.md`，视觉合同见 `references/html-review-template.md`，保存与保护边界见 `references/safety-boundaries.md`。

程序化处理只用于去重、排序、统计和把大批结构化证据压缩成小表；叙事判断、缺失证据处理、数学表述和最终验证使用直接模型判断。

## Stop Rules

- 无法确认日期、题号、错因或学习时长时写“待确认”或“未记录”，不从屏幕或上下文猜测。
- 少于 5 道可靠重点题时按实际数量输出，不补虚构卡片。
- 明确保存请求下可创建一个项目内安全复盘目录；无保存请求则只在对话中交付。
- HTML 必须渲染检查布局、裁切、移动端和内容完整性；无法渲染时说明原因和次优检查。

## Completion

报告证据来源、缺失信息、输出格式、是否保存及路径、是否使用 Obsidian 或 Chronicle、是否显式同步 Tutor，以及正式卡、生成物和回滚账本未被修改的确认。

## Current Personal Evidence And Teaching

Use exact current formal cards, immutable packages, real review events and their source versions. An imported or generated B review document is not a completed review; only real user answers and corrections enter the subject's canonical outcome route. Do not revive mandatory cold-MCP or fixed reader/QA orchestration to produce this document.

When explaining an actual problem, follow question-worker: choose the fastest reliable single exam mainline, preserve current correct work and answer timing, and use the separate GPT-6 Astra low teaching entry with a complete 30-second target/40-second ceiling. The 10–15 minute review artifact is a requested deliverable, not a reason to compress or omit necessary teaching. Later corrections must affect the next related explanation, including an already-open task; old profiles cannot override newer evidence.

