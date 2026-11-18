---
name: kaoyan-math-wrong-intake
description: 用户明确保存当前数学题，或已授权逐题保存队列中明确结束本题时，按原消息与附件封存一次，返回原生回执。
---

# 数学当前题快速保存

<!-- t3-study-panel:begin -->
在真实 T3 对话中，每次讲解、追问解答或快存回顾按宿主安装的 T3 学习分栏合同实际打开或刷新本题左侧 HTML，与右侧聊天各占一半。保留本轮授权范围和原生保存回执，复用当前线程的浏览器标签。
<!-- t3-study-panel:end -->

只在用户明确保存或已授权逐题保存队列中明确结束本题时执行。讲解结束、展示卷面、答对或自报理解均不触发准备或写入。B 变式走独立复盘入口。

复用讲题时已确认的题目、会话、attempt、queue/item、消息起止、附件角色与已有卷面。按原消息顺序**完整保存原题、本人首答、助手提示和解释、后续修订及原始附件**。没有卷面则省略solution参数。保存本身不评分，不更改掌握或长期调度。已经展示的合规图可按原 HTML 附件合同保存；点图、拖动、复制和助手推导都不是独立作答。

参数齐全直接运行 `数学一回滚复习系统/scripts/capture_current_math.py`；定位参数缺失才用同一脚本的 prepare。两种客户端的具体命令、原始图片及末尾助手消息的边界见[原生保存参数](references/native-save.md)。普通快存只办理原生准备、保存、待整理投影与回执。显式“保存并回顾”由[讲题入口](../kaoyan-math-question-worker/SKILL.md)在保存前复用同题资料完成；若回顾在保存请求后展示，用其精确可见末行作 `--end-assistant-line`，保留原 `--end-user-line`，不把它另标成卷面。

用 stage/record 的 recorded 或 noop、同一 package/Capture ID、formal_write_count=0 和 score_write_count=0 验回。给一句保存状态及可开的原包链接，按用户已要求的导航结束。此后不追加教材检索或另写小结。回包不明先对原 attempt 和回执；已提交只续缺少的投影或反馈。补充原事件或日志确有缺口再用[人工恢复](references/manual-capture.md)。用户明确要求当即正式入库时用[正式收口](references/immediate-full-closeout.md)。

只把已保存的原话当作待整理证据。额外 OCR、衍生稿或正式语义审核遵循各自授权；完整事实包保留原件、原日期和来源身份。
