# 原生 prepare、消息边界及保存参数

快速入库默认只封存本题完整真实对话、原始题图/解析图/作答图及已有的明确学习附件。不附加公式显示快照、渲染回执或状态日志，不调用math_formula_display.py，不传--formula-display-evidence及其SHA参数，不把旧显示记录作为other_attachment补入。只有用户另外明确要求归档历史显示记录时，才单独处理该范围，不能混入普通快速入库。


复用讲题阶段留下的题目身份、当前session、起始消息位置、附件角色与卷面位置。两端共用本Skill和capture_current_math.py，由脚本识别原生日志、按编号提取原文；不临时编写提取脚本或手工拼接conversation。参数齐全直接保存；缺少位置或图片路径时只执行一次准备入口：

Codex使用--provider codex，日志路径未知时省略--rollout，脚本按当前session-id只读查询应用状态数据库并核对日志身份。Claude Code使用--provider claude-code，复用SessionStart/UserPromptSubmit hook给出的--session-id和--session-context；后者绑定本会话原始日志和本次用户请求。没有hook定位时可传已知的精确--rollout和--end-message-id。两端都不得按文件修改时间挑“最新会话”、搜索其他任务，或把侧聊ID当主线程ID。Claude日志格式已受支持，旧笔记中的“Claude只能人工stage+record”不再适用。

```sh
python3 数学一回滚复习系统/scripts/capture_current_math.py prepare \
  --provider codex --session-id 当前会话ID
```

Claude的同一准备入口：

```sh
python3 数学一回滚复习系统/scripts/capture_current_math.py prepare \
  --provider claude-code --session-id 当前会话ID --session-context hook给出的定位文件
```

已知本题起点时，Codex追加 `--start-line 本题起始行`，Claude追加 `--start-message-id 本题起始消息UUID`。prepare返回save_args和当前题可见消息的行号、Claude原生UUID、预览、图片原件路径、卷面候选和稳定attempt。直接复用save_args；起点为null时只从返回消息中选择本题起点。Claude的结束UUID必须来自本次prepare，不能用“最后一个user记录”猜测；脚本等候本次请求落盘，未到齐时明确报错。根据本题已知上下文选择卷面和图片角色；候选不等于已确认卷面，不能靠“最后一张图”猜题目边界。默认只看当前消息链最近100条可见消息；明确窗口不含本题起点时，用已有起点扩大当前任务范围，不搜索其他任务或旧包。

```sh
python3 数学一回滚复习系统/scripts/capture_current_math.py \
  --provider codex --rollout 当前任务日志 --session-id 当前会话ID \
  --start-line 本题起始行 --end-user-line 准备返回的结束行 \
  --source-question-id 原始题号 --date 原学习日期 \
  --image-role 起始行:题图块号:question_image \
  --image-role 起始行:解析图块号:explanation_image
```

Claude保存沿用同一命令，将provider改为claude-code，将起止参数改为 `--start-message-id 本题起始UUID --end-message-id prepare返回的结束UUID`，其余题目、日期、队列和附件参数相同。--rollout复用save_args的精确日志；--image-role仍使用prepare返回的原始行号和块号。Claude图片的base64原件由脚本解码后原样封存，不截图替代。脚本校验sessionId、UUID及parentUuid消息链，跳过工具调用/结果、thinking、isMeta、侧链及压缩摘要；压缩前原文仍在时可沿原消息链读取，原文缺失或分支不匹配则明确失败，不用摘要补齐。


已有正式ID用 `--formal-id` 替代 `--source-question-id`；无印刷题号用稳定 `--source-locator`。精确身份查询只用准备好的索引；零匹配按new_source，冲突或缺索引明确返回缺项，不能试写正式卡发现身份。题号按题图中明确的来源ID传入，例如合成印刷题号 TEST-001；另一个章节编号保留在原始题图与对话中，不拼接成猜测的索引键。

已有已确认卷面时可追加 `--solution-line 已确认卷面行`；它是prepare返回的1起算日志物理行号，指向包含已展示卷面的整条assistant消息。Claude优先使用 `--solution-message-id 已确认卷面UUID`。脚本把该消息全部可见文字原样保存为solution_text，即使其中也有纠偏和解释，这也是预期行为；不需要裁剪、另写干净版本、重复展示或再查help。仅提到“卷面写法”但未实际给出卷面的消息不是有效候选。

卷面在本次保存请求之后才展示时，使用 `--solution-line current` 替代数字行号，省略 `--end-assistant-line`，并保留prepare确认的 `--end-user-line`。脚本直接选取该请求之后唯一一条非空、可见的assistant消息，将其全部文字原样封存并自动延长会话边界；跳过推理、工具调用、事件副本和空消息，遇到新用户消息或多条候选就报错。该参数是调用者对刚展示消息作为卷面的明确选择，不自动判断内容是否为完整解答。

仅当用户同时明确要求输出卷面写法并保存时，先完成必要的prepare，再把所请求卷面放在一条可见消息展示，紧接着用current直接保存。仅要求快速入库时跳过此展示步骤。不要为寻找刚展示的卷面再执行grep、rg、awk或第二次prepare，也不要输出单独的空泛进度消息造成多个候选。已有已确认卷面行号时沿用数字行号，不重复展示；多条消息的特殊情况只使用已有确切行号，缺少时按明确的边界错误处理，不猜测或反复搜索日志。

没有完成的卷面则省略solution参数，不为保存补写卷面或补解题目；保存层只引用已有原文。块号从0开始；图片角色沿用讲题时已确认身份，不按顺序猜。脚本直接读取本地图片或紧邻image包装声明的原件，不必手写映射JSON。非标准附件或缺件仍使用已有 `--artifacts-json`，不得为提速省略原件或缺件声明。

结束位置已由prepare确认时直接复用；Codex参数齐全且没有新用户消息时可省略end参数使用auto，Claude的auto必须有本次UserPromptSubmit定位。attempt由会话和本题起点确定：Codex保留原行号算法，Claude绑定平台、session及起始UUID；重复请求保持同一起点。已有包或旧attempt必须传原 `--attempt-id`，不能换成auto制造第二份记录。所有相关用户/助手文字、题图、解析、作答图和卷面逐字保存。SVG直接保存原件，缺附件如实标记。

晨间五题、普通warmup及C题都直接附上已知 `--queue-id` 和 `--item-id`，无评分事件时省略 `--score-event-id` 与 `--score`；队列身份不依赖评分。普通题可省略队列参数。仅需引用一个已经存在且可验证的历史评分时，传原 `--attempt-id` 与 `--score-event-id`，不能先补评分或重试评分来满足保存。旧评分引用失败时保留原件与明确缺项，交正式处理或单独修复；不在当前学习中读源码追查。更新表述用 `--requested-action update_representation`；用户要求标记掌握用mastery_candidate，仅保存请求而不宣称掌握。


核对 recorded 或 noop，保留原 attempt、package 和 Capture 身份。结束回执见本 Skill 根。
