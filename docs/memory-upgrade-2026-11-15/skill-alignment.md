# Skill 对齐

本机 Codex 0.154.0 在实际项目根目录执行 `skills/list` 且 `forceReload=true`。下列 12 项均发现唯一启用入口、源码与安装包匹配；另核对同名 Claude Code 安装入口仍指向该包。只同步 question-worker 的 `references/teaching-turn.md`；新版引用指纹前缀 `bffccf8b32ab546b`。实际本机从对应入口读过新的有界回执与三种视图。已有聊天的缓存不作为加载证明。

| Skill | 本轮读写合同及处置 | 本机入口 SHA-256 前缀 |
| --- | --- | --- |
| kaoyan-math-question-worker | 有界只读；按正文、个别状态、具体省略与原视图使用历史。改引用文档，安装及发现已核。 | `16fbf51ccf7a` |
| kaoyan-math-wrong-intake | 依授权快存原始证据，再读对应点的考频与回顾；入口与字段兼容。 | `e17bab132ac6` |
| kaoyan-math-nightly-qa | 原正式写者及日终重读；已有结果不重放。不使用验收开关作为正式条件。 | `d2698dbe536a` |
| kaoyan-math-enhancement-intake | 原准备、接受及维护；旧回包继续按既有身份核对。 | `759240851aa2` |
| kaoyan-math-review-audit | B 后审的精确来源与版本；只改派生走原维护入口。 | `4957aee86963` |
| kaoyan-math-web-bundle | 本机分组，历史兼容外发；不依赖新回执。 | `e19efcda99a4` |
| kaoyan-math-web-recovery | 同一事务从缺层恢复；没有新增 writer。 | `4df7b58ad3dd` |
| kaoyan-math-warmup | 以正式接纳的来源备题，不把教学读取当新学习。 | `78f90598ab68` |
| kaoyan-math-daily-filter | 原短名单、身份及时间约束。不依赖新回执。 | `47329e9a9f7b` |
| kaoyan-math-weak-edge-audit | 原只读关系裁决，语义相近不等价。 | `a6a94db1b57a` |
| kaoyan-math-visual-review | 原复盘与答案条件；不以图代替原始学习证据。 | `bc36ec8418bb` |
| kaoyan-independent-review | 共享 B 学习与实际证据封存，本轮不修改。 | `fb8157886c02` |

公开仓库对应的 Skill 源在 `codex-skill-sources`；公开版 question-worker 增加说明与引用，反映其已有的 CLI。它不是正在运行的本机安装；本机专属补丁在 [native-runtime.patch](native-runtime.patch)。
