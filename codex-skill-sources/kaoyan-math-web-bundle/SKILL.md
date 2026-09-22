---
name: kaoyan-math-web-bundle
description: 默认将本地全部尚未正式入库的数学快速包跨日期按知识板块和体量拆成多个A输入ZIP，每包附独立网页提示词，供用户并发交给GPT-6 Pro。今天打包也覆盖历史未入库项；仅用户明确限定单日或集合才缩小。不正式入库、不评分。
---

# 数学A主题分包

工作目录为/Users/your-user/Documents/kaoyan-math。默认范围是截至本次打包日期、仍未正式入库的全部Capture，跨日期收齐，保留各自原学习日期。用户说“今天打包”“今天需要入库的包”“生成快速入库包”均指现在导出全部积压，不是仅取今天发生的Capture。只有用户明确说“仅某一天”“只处理这些ID”才缩小范围。

## 读取与分类

```sh
python3 错题知识网络/scripts/math_A_topic_batches.py inspect > /absolute/inventory.json
```

不传--date。明确截止日期时传--through-date YYYY-MM-DD；仅在用户明确限定单日时才用--date，显式日期区间可同时传这两个参数。以原生账本重放所得pending和完整原包为准；已打包或发过网页不等于正式入库，仍须纳入当前待处理集合。Capture数、原包数、独立题数分别核对，不强行假设三者总相等。

读取inventory的题面/首答/解释片段，按实际知识板块分类；需要时只补读当前题材料，不为分类重新讲题或推断掌握。为每个eligible package_id写一项{package_id,topic,concepts,rationale}，concepts使用现有真实知识点标签或键。保留同unit_key的题目与同次补充在一个主题，不跨包重复；缺件或正在正式写入的项单列，不能无声漏掉。主题只作分工标签，不更新正式知识点或掌握度。

计划默认写scope="all_pending"、cutoff_date=inventory.through_date、inventory_sha256及assignments。仅明确限定日期的任务写scope="date_range"、date和可选through_date。build会重新校验当前全部eligible集合，漏包或新到材料使原计划不完整时补齐计划再继续，不能改回仅当天绕过校验。

## 交付多个ZIP和对应提示词

```sh
python3 错题知识网络/scripts/math_A_topic_batches.py build --plan /absolute/plan.json --output /absolute/output-directory
```

默认每包6题、35000原始对话字符、80MiB递归解包体量；同主题超限继续分册，单题超限保留完整专包并明确oversized。不得截断原话或附件，不强凑固定包数，不输出承载全部题目的总ZIP。

入口复用既有单题pack，输出每包独立ZIP及同名提示词TXT；ZIP内部也包含WEB_PROMPT.txt，并附当前PROJECT_INSTRUCTIONS.txt与具体FORMAL_RENDERING_SCHEMA.md；清单绑定它们的真实哈希，不让网页从旧MCP快照恢复过期交付合同。提示词必须来自真实清单，写明主题、题目/包身份、原学习日期、固定快照、返回身份、共享概况合并及失败保存要求。每次交付都逐包提供“ZIP＋提示词”链接，不只给一个通用项目指令让用户自行拼装。

核对当前pending Capture和输出分包的精确覆盖、无重复、原包成员哈希、共享快照及实际体量。用户提供实时看板时读取其数学数据与Capture IDs对齐，不能仅凭页面数量宣称完整。曾交付的子集被新全量批次覆盖时，明确让用户改用本次文件，不把新旧交叠批次同时发送；保留原文件以便恢复。

用户自己在网页A项目新开独立对话，每个对话上传一个ZIP并粘贴对应TXT。并发只读同一固定MCP快照，仍可能限流或超时；不代开网页任务或调用模型。失败也要保全已有成稿、执行报告和恢复检查点。

返回包交kaoyan-math-enhancement-intake，正式写入串行，共享知识点贡献汇合后再接受一份完整概况，不以后包覆盖前包。导出不产生学习事件或正式写入；不运行速度测试、试讲或模型评测。
