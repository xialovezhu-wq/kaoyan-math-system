# 当前机器路径与迁移恢复

Skill 内的 `错题知识网络/...` 和 `数学一回滚复习系统/...` 均相对当前数学项目根，不相对 Skill 安装目录。已确认当前工作区就是数学项目时，直接将命令工作目录设为该根，使用相对脚本和 `--repo .`。不要从旧会话复制用户名、机器缓存目录或旧机器的 Python 绝对路径。

路径未知时运行已安装的只读定位器：

```sh
python3 "${CODEX_HOME:-$HOME/.codex}/skills/kaoyan-math-question-worker/scripts/math_entry.py" root
```

它依次使用显式 `--repo` / `KAOYAN_MATH_PROJECT_ROOT`、当前工作区、Skill 源位置、Obsidian 库登记和当前用户默认目录。候选必须包含真实数学脚本；多库歧义或已配置目录失效时明确停止，不猜路径、不扫描全盘、不创建空库。把返回路径用于后续命令的工作目录；执行环境中的 `KAOYAN_MATH_PROJECT_ROOT` 也绑定这一根。`run` 可以直接完成这两项：

```sh
python3 "${CODEX_HOME:-$HOME/.codex}/skills/kaoyan-math-question-worker/scripts/math_entry.py" \
  run 错题知识网络/scripts/math_teaching_context.py --repo . resolve \
  --for-teaching --concept '当前具体知识点' --operation '当前动作' --view after_attempt --max-bytes 12000
```

共享的 Study-Pro-Bridge、Study-Storage-Map 默认与数学项目并列；若分别迁移，用执行环境 `STUDY_PRO_BRIDGE_ROOT`、`STUDY_STORAGE_MAP_ROOT` 的已核实绝对路径覆盖。下列只读入口返回实际位置，Skill 中 `../Study-Pro-Bridge/...` 和 `../Study-Storage-Map/...` 示例以此为准，不假定它们永远在 Documents：

```sh
python3 "${CODEX_HOME:-$HOME/.codex}/skills/kaoyan-math-question-worker/scripts/math_entry.py" paths
```

所有 Python 命令使用当前可用的 `python3`；PDF 提取沿原入口选择有 pypdf 的解释器，必要时使用已核实的 `MATH_PDF_PYTHON`。不靠不存在的旧缓存路径运行。T9 的 `/Volumes/Study-Archive` 是本系统约定的外盘挂载入口，继续核对原 UUID 与 sentinel；它与可变用户名路径不同，不能为消除硬编码而取消卷身份保护。

Codex 状态库中的旧日志地址和原对话中的 `.codex` 附件地址由捕获入口映射到当前 `CODEX_HOME` 的同一相对位置，再按原 session 与消息边界核验；不改写原日志，不按文件时间找近似替代。任意外部附件仍须准确路径或显式缺件声明。

仅在迁移后维护、路径报错或索引读取明确失败时运行 `math_entry.py check`。它只读核对题号索引、原始快速入库账本及共享入口，不写学习事实。索引 stale/unreadable/corrupt 不表示原题或历史记录不存在，不能据此按 new_source 保存。

讲题链接的后台服务另有本机安装配置。迁移后配置路径过期、服务不可用或已确认映射缺失时，用同一定位器的 `repair-bridge` 生成当前库映射，备份并重写当前机器的 LaunchAgent 与运行副本，再验回 loopback 服务；不复制旧机器的 plist、不打开 Obsidian。`check` 仅检查其配置路径，服务运行与具体题号跳转仍以本次 health/handoff 读回为准。日常讲题不执行安装或刷新。

已授权修复时，用 `math_entry.py repair-index` 在快存之外先完成一次维护：备份旧派生数据库到核验后的 T9，重新读取当前原件，完整重建并原子替换索引。重建失败保留旧库；原始账本不合法时停止并按原证据恢复，不截断账本或初始化空记录。维护成功后沿原题号、原 attempt/package 重试缺失步骤，不重复已成功保存或正式提交。此维护不是每题前置，不放进 capture 的正常热路径。

普通讲题仍只读；快速保存仍一次 prepare/save；正式入库仍走原单写者与 closeout。路径修复不授权新增学习、判分、掌握度、题序或正式卡。
