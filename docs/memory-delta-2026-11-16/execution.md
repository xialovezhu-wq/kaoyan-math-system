# MEMORY-DELTA-20261116 数学实施回执

## 本轮变更

- R-M1。当前与 `valid_at` 读取共用替代资格。通过来源核验、已确认且无未解冲突的有效替代才可结束同知识点内的旧判断。明确撤回继续生效。已记录的替代因后继证据变化无法确认时，输出 `supersession_unverified`、冲突和缺口，保留可核的原有记录。
- R-M2。已请求历史的逐点和逐事件缺口参与同版本缓存判断。送达回执分别列出已读索引、来源核验、范围内已知事件、省略及实际送达字段。部分响应重读保留正文和缺口，完整同范围响应仍可复用。来源全量覆盖记 `unknown`，读回侧答案引用绑定记 `not_established`。
- KEEP。沿用 v16 长观察投影、4500 UTF-8 字节验收边界、`protected` 和 `not_requested`、已有来源撤回与提示依赖、快存到正式入库及讲题读链。增量只涉及读取代码与讲题 Skill，无派生重建、学习事件写入或新增模型调用。共享改动为 NONE。

## 前后对照

| 观测 | 修改前 | 修改后 |
| --- | --- | --- |
| 合成 R-M1，纯推断 `candidate` 声称替代已核判断 | 当前把旧判断标成 `superseded`，历史读取只剩候选 | 当前和历史均保留旧判断 `active`，候选仍为 `candidate` |
| 合成 R-M2，4 条已知事件返回 1 条并有来源缺口 | `delivered`，同版重读 `unchanged` | `partial_delivery`，区分事件省略、来源缺口和来源引用省略，同版重读保留正文 |
| 真实读回，既有测试点的 `after_attempt` 历史 | 外层已提示未完整，回执未列历史省略详情 | `partial_delivery`，范围内 7 条，省略 6 条，送达 1 条，未报告历史来源缺口。索引核过该事件的已登记引用，全量来源覆盖未知 |

真实读回固定 `after_attempt` 视图、`valid_at=2026-11-16`、同一知识点及 4500 字节预算。正文扣除查询版本字段后哈希一致，两次均为 3758 字节。新版本 `protected` 为 2121 字节，历史证据和证据指针均为空。本次真实点未观察到同形 R-M1 修订链。

## 加载与验证

实际运行根为 `kaoyan-math`，现有测试索引为 `错题知识网络/个人知识点索引/index.sqlite3`，实现版本 16，索引版本 `c79c831c3242d9e7e771a5b8b3d55b5b99850c4cad72faa1348a3b9a89443641`，读回前后一致。通过已安装 `kaoyan-math-question-worker/scripts/math_entry.py run` 调用 `math_teaching_context.py resolve --for-teaching`。

Codex Desktop 0.169.0-alpha.11.1 在实际工作目录执行 `skills/list(forceReload=true)`。唯一启用的讲题 Skill 来自用户安装目录，与本机源包一致。入口 SHA-256 为 `26f6809041474d2bfbf28a9f8206757be0ce2f24f00f3ace4478e2412078d5da`，安装包 SHA-256 为 `b8aa2a28e80ab28193c363e88f4b2012fcda292d34fbc88244a531de248e974f`。

两组本机定向方法各 5 项通过。随后从发布工作区的源码提交复验 3 项，均通过。范围包括候选和冲突、替代归档及来源变化、明确撤回、跨点隔离、时间截点、缓存与保护、提示依赖。本轮未验证全库行为、端到端讲题耗时、模型答案引用或学习效果。

## 发布

- 仓库 `xialovezhu-wq/kaoyan-math-system`，分支 `memory/20261116-math`。运行工作区使用原 Gitee 映射，代码通过已有 GitHub 审查工作区发布。
- Baseline `a9a7eeff423546073d4ff736f9a8e4e70f5eb925`。
- Tested `192e132ceb9cfd24d4c82d3efef5411c1a99d0f3`。六份发布文件与本机对应文件逐字节匹配。本回执随单独的报告提交交付。
