# 数学 A 分包概况汇合

对带 `batch_binding` 的实际已暂存回包，在同一次任务用原计划和收到的 stage 回执列清范围：

```sh
python3 错题知识网络/scripts/math_learning_profiles.py inspect-contributions \
  --batch-id ORIGINAL_BATCH_ID \
  --receipt /absolute/staged/S01_RUN/receipt.json \
  --receipt /absolute/staged/S02_RUN/receipt.json
```

只传真实 stage 回执；暂未收到的分片会出现在 `missing_shards`，已收到但未成可用贡献的在 `unprepared_shards`，缺正式提交的包在 `packages_without_closeout`。 `concept_shards` 是当前已验证并有贡献正文的概念与分片，待齐全前不能当作全覆盖。存在真实缺项时保全已完成单元、按原身份续接。未变期间复用同一回执。

按最新本地目录和原始证据，编写每个知识点一项的完整 `profiles` 输入。把上面返回的 `binding` 原样放入根字段 `batch_contributions`；每个有分片贡献的点写 `contribution_reviews`，键为它对应的全部分片，每项用一句说明实际吸收或裁决的内容。保留各片引用并显式处理互相矛盾的判断。改变已有 `claims`、`step_evidence`、`teaching_preferences` 或 `solution_connections` 时，该片的说明点名字段并写明原证据支持什么、不支持什么；同名声明不能靠顺序决定。沿用各字段自身的历史修订要求。贡献来源、补充证据和当前案的学习事实分别查原件。

沿原 `prepare` 冻结合并稿，完成实际的分日 closeout 后重新 inspect 核对。把 `event_ids` 的完整并集传给原 `accept --event-id …`。提交必须对应每片原版包；若实际 closeout 混进批外 Capture、已失效或有未关闭的包，停在该点并保留回执，不能用最后一个事件补证。正式提交完成后只续缺的合并接受、归档和同题同点的本机验回。已完成无该绑定的历史汇合继续用原有回执，勿为补清单重放。

收口先查 `semantic_current`、短摘要、条件、提示依赖、下一检查与原始轮次，再沿原工作区 `reconcile` 验回本机索引与许可视图。回执中的接受或哈希只证明身份与内容匹配，首答是否正确、条件有无省略、最新证据所能支持的范围仍由合并者核完整来源。副本发布只随用户明确要求的远程访问或外发单独执行。
