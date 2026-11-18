# 数学空间断点的 iPad 投送

本说明用于用户本轮明确指定 iPad 的场合。默认在[本题左侧 HTML](sidebar-delivery.md)展示当前获准的三维场景，沿用原题坐标、阶段和视图，不执行设备投送。

指定 iPad 后，当前讲题模型在首次需要解释时判断旋转、投影或切片具体能解决哪个疑问。在已有查询上加 `--tutor-presentation three_d`，同次传精确来源题号或正式号和 `--operation`。没有题号时传 `--visual-source-text` 绑定当前题面；旧题更换题面时同样传入已核的当前题文或 `--visual-surface-sha256`，版本不合时定点备图。已有不同小问/空间步骤的独立场景时附登记后缀 `--visual-part`。例如 1994 数一第四题默认显示上下盖面片，转讲侧面时另传 `--visual-part side`。一幅图只显示当前允许解释的关系。公式与推导写在右栏，二维图解沿本题左页。

提示阶段使用 `--view after_attempt`，未解锁题目用 protected 的 question 场景，已授权解答并确需解答模型时才用 `--visual-stage solution --view direct`。原查询 stdout 仍是个人摘要，stderr 的显示回执核对题号、阶段、版本、实际 iPad 及渲染就绪；只有外层 `shown` 可报已显示。未命中摘要仍可投送。离线或失败时在聊天给出当前解释，保留实际投送状态。

若回执要求准备精确场景，依据原题真实坐标、半径、方向、边界和当前提示范围填写一个 JSON。包含 `question_id`、`question_text`、`source:{path,sha256}`、`verification:{kind}` 和 `scenes`。已建题的 source 指向数学项目内稳定的原图或原题，按原字节核对 SHA。只有当前题文的新题可以省略 source，精确题文哈希生成临时身份；各阶段 scene.question_id 使用同一身份。scenes 使用已安装共享播放器的 `study-visual-scene-v1`，以 question、hint、solution 为键，三者分别持有独立的完整数据。只提交本次允许的阶段、面片、向量和短标签。基础模板和相机字段见共享播放器的 `schema/study-visuals-3d-v1.md`；旋转、捏合、选中和方向切换沿用原生播放器。各轴同尺度，法向从所属面片向外，先保留能解释本步的对象。当前单题之外的场景继续独立。

```sh
python3 错题知识网络/scripts/math_ipad_scene.py --repo . --input 本题数据.json --stage hint --workspace 已核T9数学冷目录
```

准备后用上一回执的完整题目身份、当前阶段和 `tutor_presentation=three_d` 直接调用 `study_visual_dispatch.py --input-json`，带已核 `expected_surface_sha256`；先前摘要继续复用。输入 JSON 为当前题的 subject、current_question_id、teaching_goal、current_difficulty、intent、answer_status、permitted_stage 和所选媒介。达到 `shown` 后在聊天写出这个视角说明的数学关系。保留一题内合法直接复用，不将看图、拖动或提示后复述算作独立掌握。
