# 数学 Skill 对齐

本机 Codex Desktop 0.169.0-alpha.11.1 / macOS arm64；在真实数学 cwd 启动全新 app-server，运行 skills/list(forceReload=true)，核对返回的路径、scope、enabled 和磁盘字节。九项均从实际用户安装位置唯一发现、启用，无数学加载错误，且源和完整安装包一致。随后在隔离 cwd 验证候选仓库范围的讲题 Skill 可被同一 loader 发现。实答回放调用的是实际数学读取器和真实 API，不能替代桌面工具调用或旧会话热重载。

源位置：数学工作区 codex-skill-sources/<名称>/SKILL.md。安装位置：~/.codex/skills/<名称>/SKILL.md。包哈希为排序后的逐文件 SHA-256 清单的 SHA-256，覆盖入口、引用、agents、脚本与资产；排除 .DS_Store 与 Python 缓存。下表为实际路径读回哈希；远程公开源码去掉机器专有路径，不能用发布版哈希替代本机安装哈希。

| Skill | 角色 | 实际入口 SHA-256 | 实际包 SHA-256 | 调用及处置 |
| --- | --- | --- | --- | --- |
| kaoyan-math-question-worker | 日常单题讲解 | 16fbf51ccf7a8aee25c0235e73c9a043e3c177214afca3ef07e23853d29e6a1b | 1a1ac217cb1cd89874534158c2372cc65d871771ea76e98f57f19ade834c8d38 | math_teaching_context.py resolve --for-teaching；同题 1–3 细点、三视图、只读。候选 teaching-turn.md 只在评测工作区加载。 |
| kaoyan-math-enhancement-intake | 本地增强及既有 A 回包兼容 | 5f098fc888856ef3c0a1f56fddafebd6211dea15d33ebf0df45d05dd918c1fd3 | f1976b3701190e784f037e48157ae1028a5cc93a3163d00a6710bad79c5f7f00 | math_learning_profiles.py prepare/accept/accept-maintenance；正式审阅继续走原唯一 writer；本轮仅同步规则。 |
| kaoyan-math-nightly-qa | 正式 A / 日终 | df8f2c2c131157e2ca69d50803a4968e26ba8b94690ae18dd3e99cd3e9b828bd | 99c805885ade6294873a559e78f83a543b6c15484e78b10b274fe1e0f5070eca | quick_intake.py、math_formal_quality.py、math_postcommit.py；本轮仅同步规则，没有新冻结或 closeout。 |
| kaoyan-math-wrong-intake | 快速封存 | e17bab132ac68bbf19b4526a4486dd1ceb99568804623898dbd5d45552954bcf | 011f1da390f8ca8cef30deb48184aa11ab12a5d149d25aa0553dccff23056bc2 | capture_current_math.py / quick_intake.py；只在确有授权时封存，不从投影推断学习。未改。 |
| kaoyan-independent-review | 共享原生 B | fb8157886c022be32a1abea4103abaa2094f7b3b53398bbb2c1d424400d2d5fb | b050b4f4edb62f7a3eaa7d3a134dd9b8855ebca1b79f20e78ea77adf1559fb09 | open_package.py、math_review_handoff.py preserve；仍准备和封存真实会话，未改共享 Skill。 |
| kaoyan-math-review-audit | 数学 B 后审 | 4957aee869637783adbcb9cdf66f5c0b95913b67d3cd59dff749cbc01491e75c | 8da815da1af79af747443ad1e80b6fbe48e59fc0bbf0608ea631a93e3b9e972a | math_review_handoff.py read/audit/resume；精确读真实证据，无新的 B 会话。本轮未改。 |
| kaoyan-math-web-bundle | 本地 A 分组，历史外发兼容 | e19efcda99a48d7ff15d28b79ea3c99113a7b8fe38b9387144f7fb3271167645 | 76f976fdce90d8f19654656644701c14dbaaa041d70b4f1dea0bf20865664192 | math_A_topic_batches.py inspect/build；明确外发才启用旧传输。未改。 |
| kaoyan-math-web-recovery | 历史 A/B/C 恢复 | 4df7b58ad3dd34325f3598b645ec333b39a012497a6913187a52c538bbd98876 | 41f0aa59e3a0a761040482118c0ebfbac3a780e933be8515ef68bd26016c326e | math_web_progress.py --project A/B/C；复用原身份和已完成状态。未重新启用退役工作流。 |
| kaoyan-math-warmup | C 次日备题 | 78f90598ab686ec0375486cb34aebd7bc5b58d0f5e82b3109376b497bae129bd | 216f58d3c5c744be368d0abf795502478ee2d14d6591b5687ae587663406caa2 | scheduler.py warmup-candidates/warmup-successor --coverage；保留已有冻结队列和版本校验。不重做题单。 |

生产讲题 references/teaching-turn.md：bffccf8b32ab546beefd8bbdb819b9d624eee7fee2fcce991a07eb5d5602b0fd。隔离仓库范围候选入口哈希仍为 16fbf51ccf7a8aee25c0235e73c9a043e3c177214afca3ef07e23853d29e6a1b，候选整包 55b662cc8a09573d2cb500418ced1eb77e455bfc5082b95aec0e8d3b846ff4c1，改变的 teaching-turn.md 为 dd3e2b5cb0774ac4b7ca1ff8b7591337fd11f36c7201ff232989d5f6332d2747。新旧哈希不同的引用没有切入生产。隔离 cwd 同时看见现行用户副本；这里只证明候选能被 loader 发现，不宣称它是日常教学实际选择。

同步文件只涉及 nightly-qa 和 enhancement-intake 的 SKILL.md。两项 quick_validate.py 退出 0；原 references（包括 profile-consolidation.md 与正式归档/恢复引用）、agents、脚本、资产的全包逐文件比对通过，无覆盖未纳入改动的文件。
九项既有 Claude Code 链接仍解析到同一实际安装目录；未启动 Claude 会话。

C 的默认消费者仍为原生 warmup；math_A_c_handoff.py、旧网页 B/C 以及已冻结的安全题单按历史合同读取及续办。本轮没有修改现行生产算法、启用退役入口或切换第三方记忆后端。
