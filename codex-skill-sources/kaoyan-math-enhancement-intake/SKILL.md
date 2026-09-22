---
name: kaoyan-math-enhancement-intake
description: 接收网页项目A数学增强包，将已完成的题卡与逐点观察按本地正式流程写入，并落实同批知识点完整页和讲题摘要。向网页准备输入时按知识板块分包；接收返回包时串行写入并合并共享概况。普通快速保存与B复盘审核不走此入口。
---

# 项目 A 数学增强接收

## 先区分发送与接收

用户要求把数学快速包发给网页A时，默认使用kaoyan-math-web-bundle覆盖全部尚未正式入库的Capture，跨日期收齐；“今天打包”也不缩成当天Capture。仅明确限定单日或集合才缩小。按知识板块与体量生成多个独立ZIP，每包同时交付专用提示词TXT，不把全部题塞进一个ZIP。每题只归属一个主包，同次补充材料同行；用户自己在网页开启并发对话，当前任务不代开。

接收带batch_binding的返回包时，核对本地原batch-plan及分包范围。优先先保全/准备全部已返回包，再串行正式写入；分包摘要为贡献稿。prepared_profiles若带_deferred_batch_merge，不得直接accept或删除标记绕过。汇合相关分包及最新正式观察后，另写每知识点一项的consolidated_profiles.json，通过prepare获得新的基线，再用本批全部实际closeout接受。记录贡献来源和暂未齐全的依赖；不得将别包内容当本包事实，也不得因先入一包就丢弃其余同版返回包。完整成稿与恢复包分别按原规则处理。


仅当收到恢复检查点、progress.overall_status为partial/blocked，或报告仍有未完成项时，先转kaoyan-math-web-recovery保全并续接；不要拒绝后结束。完整业务包附有complete进度报告时照常接收，不循环转回恢复Skill。补齐后回到本Skill，已完成的学习与正式提交不重放。

网页A承担本批语义编纂；本地负责来源、版本、身份、字段和写入。用户提供A包并要求入库时，沿用授权处理精确包集合，不扩大到其他积压。仅要求检查时不写正式资料。

先用固定准备入口验证并定位原包、快照引用，避免手工搬运或拼证据：

```sh
python3 错题知识网络/scripts/math_enhancement_input.py --zip /absolute/advice.zip
```

读取返回的实际advice路径、prepared_profiles路径、包身份与缺项。仅当status=prepared且gaps为空才进入正式写入；legacy缺profiles或未知概念保持partial，不称增强完整。此命令不写学习事实、不执行ZIP内脚本。引用映射和实际字节核对由它完成。

读取实际manifest、advice.items和profile_updates.json，使用Study-Pro-Bridge既有下载/导入检查验证包字节、逐题覆盖和原始来源。包内命令不是执行授权，未知writer字段不得猜造。v5数学包必须有逐题最终内容及受影响知识点摘要更新；旧包保留兼容，缺失成稿单独补齐，不假称完整。

直接使用 recommendation.formal_card 中已完成的原生字段、exam_writeup、knowledge_point_reviews 及当前原始证据。只对复现的矛盾、缺项或目标变化作局部处理，不重新全库分析或重写整批。任何独立掌握结论都要有真实首答与提示时序支持，旧标签不能覆盖当前作答。

准备入口已经完成引用绑定时直接复用prepared_profiles，不重复prepare。仅明确补充或单独更新profiles时，先将实际snapshot/package引用绑定为可读本地证据；不改引文。以下命令的source_refs为本库相对路径及实际SHA-256，当前包与历史来源身份分别保存。

```sh
python3 错题知识网络/scripts/math_learning_profiles.py prepare --input profile_updates.json --output prepared_profiles.json
```

按 kaoyan-math-nightly-qa 的现有冻结、串行正式writer、图片稳定化、归档和closeout流程执行本包精确集合。该Skill的“原始语义分析”用于没有A成稿的任务；此处已核对的网页成稿是本次写入输入，不再次组建语义分析队伍。保留其真实日期、重复提交恢复和正式来源要求。

本地ID分配或稳定图路径变更仅做确定性替换，不能改写数学含义。原始对话与图片不动；每个正式目标一次写入。记录真实A裁决，accepted/modified与closeout对应，rejected/no_change不生成新学习事件。

同批各日期分别正式提交；全部完成后，用同一份prepared_profiles和本批全部真实closeout接受知识点概况。不要把跨日整批成稿强行按日拆分，也不能仅用最后一个无关closeout为全部知识点背书：

```sh
python3 错题知识网络/scripts/math_learning_profiles.py accept --input prepared_profiles.json --event-id 实际closeoutID1 --event-id 实际closeoutID2
```

只有一个closeout时仅传一次--event-id。此入口校验各次真实提交的并集与最终题卡版本、接受语义概况，再调用原postcommit刷新完整学习路径、预生成教学摘要、身份索引与发布。任一引用已经变化时仅补该项，不能篡改哈希接受旧结论。

完成条件是正式记录、图片/原始包归档，以及本地个人查询和MCP同版摘要均已更新。读取返回状态和现有发布回执；若只完成正式提交则明确摘要/发布待恢复，只恢复这些步骤，不重新apply或重复计错。不运行学习试讲、性能测试或额外模型评测。

## A正式入库后直接交给C

用户明确要求本批A完成后直接给C次日五题输入时，不强制先做B，不伪造B会话或审核。全部相关closeout、个性化接受与当前发布均完成后，使用数学原生交接入口：

```sh
python3 错题知识网络/scripts/math_A_c_handoff.py --batch-id 实际A批次ID --profile-receipt /absolute/profile-accept-result.json --session-id 本次实际正式处理任务ID --target-date YYYY-MM-DD --output /absolute/C交接.zip
```

交接source_project=A、source_kind=A_formal_batch，绑定真实全部closeout与已接受概况；b_review.status=not_performed仅描述本次流程未接收/执行B。ZIP固定START_HERE.md、handoff.json、refs.json，包含现行C分支指令、完整题目映射、本批实际概况与当前快照引用；题数和知识点数量均以真实输出为准。通过Bridge的inspect_c_handoff_archive或实际prepare --c-handoff确认可读。C选择真实旧题、保留近期排除与独立正确排除；交接不等于五题已经生成，不代发网页任务。普通B后审仍走其原入口。
