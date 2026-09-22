# Wiki 页面模板

新建 wiki 页时复制本模板。正式页面放在：

- `错题知识网络/wiki/sources/`
- `错题知识网络/wiki/overview/`
- `错题知识网络/wiki/concepts/`
- `错题知识网络/wiki/methods/`
- `错题知识网络/wiki/topics/`
- `错题知识网络/wiki/error_patterns/`
- `错题知识网络/wiki/triggers/`
- `错题知识网络/wiki/synthesis/`
- `错题知识网络/wiki/questions/`
- `错题知识网络/wiki/maps/`
- `错题知识网络/wiki/maintenance/`

```markdown
---
wiki_id: MATHWIKI-GS-CONCEPT-001
type: concept
title: 标题
subject: 高等数学
knowledge:
  - 待补充
methods:
  - 待补充
error_causes:
  - 待补充
triggers:
  - 待补充
source_refs:
  - 待补充
wrongnet_refs:
  - 待补充
method_card_ids:
  - 待匹配
wiki_refs:
  - 待补充
status: active
last_updated: YYYY-MM-DD
---

# 标题

## 定位

一句话说明本页沉淀什么，不写完整题解。

## 核心结论

- 待补充。

## 触发条件

- 看到什么题面信号时应想到本页。

## 方法链

1. 先做什么。
2. 再做什么。
3. 最后检查什么。

## 常见错因

- 待补充。

## 关联

- 错题：`GS-xxx`
- 方法卡：`Hxx-yyy`
- 相关 wiki：`MATHWIKI-...`

## 来源

- 只列来源路径或页码，不复制长解析。
```

## 字段规则

- `wiki_id`：只从 `wiki/index.md` 查下一个编号，不复用 `GS-901` 这类错题编号。
- `type`：优先使用 `source_summary`、`overview`、`concept`、`method`、`topic`、`error_pattern`、`trigger`、`synthesis`、`question_queue`、`map`、`maintenance`。
- `subject`：使用 `高等数学`、`线性代数`、`概率论与数理统计` 或 `综合`。
- `wrongnet_refs`：只能引用已存在错题卡 ID；不确定写 `待补充`。
- `method_card_ids`：必须优先查 `方法论库/method_card_registry.md`；找不到写 `待匹配`。
- `source_refs`：只写路径、页码、来源名，不复制 raw source 正文。
