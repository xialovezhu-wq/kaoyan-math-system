# 项目 B 的 408 收尾

408 分支保留原流程。记录真实结束时间，从本场完整对话生成一份 `concept-review-session-v1` 输入，保存全部用户/助手原文、题目与解析、实际附件、真实日期和稳定 `session_id`；把包的 manifest、计划和相应题目来源文件作为来源附件。不用总结代替会话，不伪造缺失附件。规范键不确定时定点核对，只有真实证据支持的知识点才生成观察。

首答明确错误与提示后修复分别引用原话。`unresolved` 不自动算错，`corrected_after_hint` 不反推首答错误。只有明确 `wrong` 增加该知识点本场错误标记。没有实际作答或可确认观察时，不提交空学习事件。

读取 `/Users/your-user/Documents/kaoyan-408/schema/concept_review_v1.md`，然后在 408 repo 运行：

```bash
python3 scripts/concept_review_408.py commit --input /absolute/session.json
```

不建立生成变式的正式题，不修改关联原题的复做日期、错误次数、掌握度或队列。入口不可用时保留完整输入并明确未保存，不退回 Capture 或冒用原题评分。

成功后读回知识点标记与后置状态，用现有 `study_publication.py verify-current --subject 408` 核对查询副本。已提交但后置失败时只按 408 合同恢复刷新/发布，不再增加同一事件。保存耗时不算进 30 分钟学习时间。
