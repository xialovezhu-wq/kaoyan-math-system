# 数学记忆验收

2026-11-16，北京时间。源码审查 base 2f8ae347f3f34b239407702a546a0101b38e6dc1，冻结本机工作区 HEAD c3098894a3611fc0e76cc47985e070b454d0f198（有已存在的本地增量）。实际从 GitHub 取回并测试的 code SHA 为 3ae384991be349ee10303585f8bdac0e57263404；报表提交仅增添本目录 4 个文件。现行配置没有切换到候选。以下计时都是本次观察值。

## 输入和命令

B1 为本机 v15 现行代码与同步前本机讲题规则；B2 为 v16 原子观察候选与对应的隔离讲题规则。两组题面、实际输入的合成作答、视图、日期、4500 UTF-8 字节预算完全相同。冻结事件的 study_date=2026-11-14。开发机制以实矩阵正交对角化、同一/不同观察、未知提示和序列化边界为主；留出 24 个独立合成题族，含 21 个长观察/有审核纠正/失效场景（受保护长记录亦单独检查）。首 12 个固定用于真实讲题；不额外发 B0 请求。开发和结论判定没有读留出模型答案来修改候选或提示。评分依据独立于发给模型的消息，按冻结题例和条件检查。

| 本批 T9 相对产物 | 冻结文件 SHA-256 |
| --- | --- |
| evaluation/heldout.tsv | debe51feb00521577fd218381c4079dfb141d4e8092fefb3e8d661156837cfa8 |
| evaluation/gold.txt | 8c6e1b3463cb65a5ebab86145d6837d9a4b03c34aa3115bea94cf3b0872026cd |
| evaluation/protocol.json | bfc5bb9d5d3af15c65c4e97bc737638cf2f3cbff3057f1d64f84d7c7efba8c46 |

以下均运行于合成夹具/隔离源码目录；TMPDIR 为本批已核 T9。$RUN 是本批根，$TOOL_TREE 是对应隔离源码树。运行 unittest 前把 $TOOL_TREE/错题知识网络/scripts、$TOOL_TREE/数学一回滚复习系统/scripts 和 $TOOL_TREE/tests 依次加入 PYTHONPATH，设置 PYTHONDONTWRITEBYTECODE=1。

    python3 "$RUN/input/math_projection_diagnostic.py" --scripts-root "$TOOL_TREE/错题知识网络/scripts" --source-sha SHA
    python3 -m unittest discover -s tests -p 'test_math_atomic_observation_projection.py' -v
    python3 -m unittest test_math_atomic_observation_projection test_math_problem_methods test_math_profile_card_evidence test_math_teaching_preferences test_math_teaching_context test_math_learning_profiles test_math_profile_revision test_math_memory_upgrade test_math_memory_projection test_math_postcommit test_math_memory_lifecycle
    python3 -m unittest discover -s tests -p 'test_math_*.py'
    python3 "$TOOL_TREE/错题知识网络/scripts/math_concept_index.py" --repo-root "$FIXTURE" build
    python3 "$TOOL_TREE/错题知识网络/scripts/math_teaching_context.py" --repo "$FIXTURE" resolve --for-teaching --concept "$KEY" --view "$VIEW" --max-bytes 4500 --audit-context
    python3 "$RUN/evaluation/replay.py" B1
    python3 "$RUN/evaluation/replay.py" B2
    python3 "$RUN/evaluation/timing.py"
    python3 "$RUN/evaluation/recovery.py"
    python3 "$RUN/evaluation/replay.py" model
    python3 "$RUN/check_skill_load.py" "$MATH_CWD" "$RUN/production-skill-loader.json"

## 查错、查询和恢复

| 验收面 | 实测与退出码 |
| --- | --- |
| 公共旧基线重现 | 诊断退出 0，仅代表两个问题重现：观察前缀漏纠正；4500 的 pre-metadata 对象最终 4541 字节。 |
| 本机 B1/B2 重现 | 附件脚本的旧 SQLite 预算夹具缺 records 表，退出 2；本机 B1 的观察缺陷仍实测 OBSERVED，B2 NOT_OBSERVED。替换为本机完整 fixture 后，B1 与 B2 空结果、恰好上限、超过 1 字节（不输出残缺记录）、中文 UTF-8、最终计数字段均通过。预算代码保留。 |
| 候选专项 | 新增 6 个 unittest（含换序和跨记录 subcases）；候选相关 160 项退出 0；从远端取回的实际 tested SHA 用 7 个已存在/新增的纯合成测试文件共 85 项、退出 0。原始观察及完整历史仍可查。 |
| 全量对照 | 905 个 math unittest 两组均退出 1；B1 为 25 failures、4 errors，其中 7 个 failure 来自新增测试对旧行为的有意负对照；B2 为 19 failures、4 errors。共同失败为现有文字契约及隔离外部依赖，新增 1 个断言正是隔离讲题引用未同步到生产副本。全量未标通过，专项和精确 loader 单独报告。 |
| 留出完整查询 | B1/B2 各 24 题、均进程退出 0。B1 的 16 条可见未经审核旧正文，B2 为 0；两版各 2 条已审核纠正完整送达。两版均无受保护原话/答案标记，失效不复用。B1 最终响应 1553–4474 B；B2 1553–4220 B。 |
| 生产数据只读回查 | 两个预先已接受概况，B1/B2 各读三视图共 12 次（退出 0）。保护视图不含摘要或历史定位；可见视图摘要 SHA-256 一致。最大 4336 B。七个冻结权威文件的前后 SHA-256、热索引版本、三个共享运行文件均一致。未触发生产正式事务。 |
| 故障与回退 | 隔离 B2→B1→B2 用真实 build，各产物重新读回；原观察和原卡文件哈希不变。仅对隔离副本故意损坏 SQLite，原生教读报 stale、未重建/写回损坏件；恢复既有夹具指针即可重新查询。已有定点失效、构建期来源漂移、重复维护、版本保护、closeout 不重复与派生失败仅续派生在专项合成回归通过。 |
| 白名单与远端 | 仅 49 个数学白名单源码、规则和合成测试文件，再加四份脱敏报告；继承旧镜像的 writer 文件无本次改动。对 stage 执行 git diff --cached --check 通过，Gitleaks 8.30.1 --staged 出口 0、0 命中；GitHub 上传后的代码树与审核树 SHA 相同。 |

## 性能、I/O 和真实答复

同一 Mac、6 个代表查询、每温度 30 组交错。冷为新 CLI 进程，未清除系统文件缓存；热为持久进程，每次仍走原 SQLite 只读路径。最邻近秩 p95。

| 测量 | B1 | B2 | 门槛与结论 |
| --- | ---: | ---: | --- |
| 冷查询 p50 / p95 | 143.01 / 150.63 ms | 143.23 / 149.97 ms | 未见冷查询回退；各次低于测试进程超时。 |
| 热查询 p50 / p95 | 1.68 / 2.15 ms | 1.66 / 2.33 ms | 门槛 22.15 ms，通过。 |
| 热进程峰值 RSS | 52,822,016 B | 52,559,872 B | 同样的 Mac RSS 口径。 |
| 热查询语句 / 路径 stat | 16–19 / 24–27 | 16–19 / 24–27 | 六例逐对相等；SQL 写入 0，热检索外部模型调用 0。 |
| 隔离建库/复盘准备中位 | 23.32 ms | 23.42 ms | 新的小夹具，含合成正式证据的隔离准备；不代表实际正式整理。正式生产维护耗时/分项解析字节未测。 |
| 实答首句 p50 / p95 | 25.16 / 32.67 s | 20.04 / 34.95 s | 流中完整实质句；相对 p95 1.070，通过。 |
| 实答完整 p50 / p95 | 26.31 / 33.83 s | 20.69 / 36.91 s | 相对 p95 1.091，通过；候选未达 30 s 绝对目标、已完成的均在 40 s 内。 |
| 答复完成数、评分 | 11/12；10/11 | 11/12；10/11 | 10 个完整配对各通过 9 个；无净改善。未完成两次不能从分母隐去作通过。 |

真实调用：官方 Responses API，实际可访问的 gpt-6.1-sol / max / default；固定现行教学读取入口的 stdout 与两版对应 Skill 相关证据规则，模型不读金标准、真实题卡/私库、原对话；无工具委派、无 learner 事件。顺序交错，最多 24 次，每调用最多 2200 输出 tokens、10,000 UTF-8 输入字节。请求 B1、B2 共 24 次，无重复发出。22 个有完整实答，其中 B2 有一次用尽输出 tokens 未完成，B1 有一次流没有终态。p95 只对各自 11 个完整回答观察；完整采样少，且 Responses 耗时未包含桌面应用轮次、呈现或视觉工具。无证据证明真实桌面完整时延达标。

有 usage 回执的 23 次共 43,267 input tokens、31,755 output tokens；[标准公开价](https://developers.openai.com/api/docs/models/gpt-6.1-sol)按 $2/$10 每百万估为 $0.404084，按更保守的缓存写入价和一笔未返回 usage 的 $0.05 预留合计不超过 $0.475718。不是实际账单。数学试验上限 $0.90，为既有共享 $5 试验上限中的小额子限，未新增预算/付费超额，真实正式维护额外模型调用 0。热查询、模型答复、正式试验计时相互独立。

评分先按去掉 arm 的标识核读实际答复，再还原配对；不是独立评审者或模型自报。适用条件、结论、来源判断及独立/提示依赖分开判读。普通题无新数学错误；保护条目没有给出最终答案；本轮未观察有答复把提示后完成直接写成独立。B2 的换元只请填写变量，没有覆盖冻结要求的微分因子检查；B2 对通项必要条件明确给了反例，补上了 B1 缺失的要求。未据实答改变托管 Skill 或重调留出。

### 真实配对逐例

每格为“冻结评分；首个可用完整句 / 完成秒数”。无法计时以 — 标记；不完整请求保留观测截止时长。

| 案例 | B1 | B2 |
| --- | --- | --- |
| L01 洛必达法则的使用条件 | 1；30.23 / 32.93 | 1；20.81 / 22.80 |
| L02 二重积分的区域换序 | 1；17.81 / 18.41 | 1；14.67 / 15.21 |
| L03 三角复合函数换元 | 1；24.79 / 25.32 | 0；20.04 / 20.69 |
| L04 矩阵满秩与逆矩阵 | 1；31.41 / 32.80 | 1；22.28 / 23.16 |
| L05 不相关与独立 | 1；21.61 / 23.38 | 输出未完成；— / 39.37 |
| L06 条件概率分母条件 | 流无终态；— / 16.83 | 1；28.23 / 29.13 |
| L07 幂级数端点的敛散性 | 1；27.21 / 28.43 | 1；17.46 / 18.58 |
| L08 拉格朗日中值定理的可导条件 | 1；28.14 / 30.11 | 1；26.20 / 28.36 |
| L09 定积分的区间对称性 | 1；10.43 / 10.54 | 1；15.47 / 15.57 |
| L10 期望的线性性 | 1；25.16 / 26.31 | 1；17.77 / 18.42 |
| L11 不同特征值的特征向量线性无关 | 1；32.67 / 33.83 | 1；34.95 / 36.91 |
| L12 数项级数的通项必要条件 | 0；17.56 / 19.06 | 1；18.37 / 19.43 |

## 启用判定

M1 离线与检索通过，真实答复门槛未通过；B2 仅保留在本机隔离运行与 GitHub 审查分支。M1b KEEP_EXISTING。M2 正式审阅规则和加载通过，日常讲题候选不替换；M3 复用既有别名和失效机制。Mac 实际 loader 独立通过，生产两项更新；隔离候选能被发现但不代表旧会话或日常路由已加载。新的共享集成、正式生产写入、桌面模型端到端和自动任务未测。
