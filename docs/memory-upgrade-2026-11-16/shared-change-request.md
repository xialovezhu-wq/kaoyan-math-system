# 数学共享变更请求

NONE。数学未修改 Study Pro Bridge、共享只读 MCP、intake backend、共享独立复盘 Skill 或另外两科专属文件。不新增共有字段、权限、发布范围、守护进程、依赖或调度。数学短摘要继续走既有字段，冷投影的历史定位只进入数学本地派生短摘要；受保护视图结构未改变。

| 组件 | 2026-11-16 核对的 GitHub HEAD | 处置 |
| --- | --- | --- |
| study-pro-bridge | 809bf7351abe1282bb1187b82998f48908485d41 | 本机 study_mcp.py、study_bridge.py、study_publication.py 的 SHA-256 前后均一致；无新挂载或发布。 |
| local-study-read-mcp | 5da8f9af60b286fe0e6bb69dcc8f7f40da2832fa | 未写；数学正常读路径 SQL 追踪无写入，候选未接入共享服务。 |
| study-intake-v2-backend | 3c14a3d2f1fbfe0b02ca24bf7a796b55819a21dc | 未写；原正式 writer、资料复制发布权和幂等恢复均沿用。 |

本轮仅验数学本机的原生查询、数学的最小发布消费者测试、既有本地发布绑定。没有拿到 408 冻结共享候选，因此未切换或验收新的共享集成版本。
