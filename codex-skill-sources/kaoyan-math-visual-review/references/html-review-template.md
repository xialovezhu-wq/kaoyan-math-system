# 本机晚间复盘 HTML

沿用 `数学一回滚复习系统/知识点复盘/阅读卡片/YYYY-MM-DD/index.html`。已有指定页面时保留旧版，再用同一入口交付。页面离线可读，一个文件包含原题图、MathML 和必要交互。

每卡从上到下给知识点短标题与题号、原题面、二级结论、基本方法与解题过程、基本公式。条件、主式、必要边界直接展开，推导和来源按需点开。左边是有连线的基本方法树，同一行箭头指向右边的过程框，保留必要小问和分支。公式保持离线 MathML，题图按完整原件嵌入。10–15 分钟口播只在明确要求时另交讲稿，普通复盘 HTML 不预制口播。

## 使用模板

复用本 Skill 的 `scripts/render_review.py`。由当前代理先据实选择素材并编写卡片数据，脚本只负责展现。过程 JSON、旧版备份与验证文件都用已核 T9 目录。

```sh
python3 <本Skill目录>/scripts/render_review.py --repo <数学项目根> --input <当日卡片.json> --output <已核T9目录>/index.html
```

输入字段：

- 整页 `date` 为 ISO 日期，`sections` 按计划顺序包含 `key`、`title`、`cards`。
- 每卡有 `id`、`title`（知识点）、`source`、`question_image`、`conclusions`、`method`、`formulas`。题图填 `path` 和已核 `sha256`，可填 `alt`、`width`、`height`。无合格题图时用 `question_parts`，每项 `label` 和 `text`，按原题真实结构。
- `conclusions` 和 `formulas` 是短条目数组。每条 `label`，按需加 `condition` 或 `latex`；长式拆为多条。文字中的数学用反斜线圆括号，`latex` 字段填无定界符的公式。
- 已解锁卡写 `view: direct`。当前条目有已核公式卡时在对应项加精确 `entry_id`，渲染器读同版卡并保持条件和公式顺序；原项的 `condition`／`latex` 只作为有来源的降级，不给过期 ID 自动补前提。受保护卡写 `view: protected`，其分组标题只用允许公开的范围，产物只写已核题面。
- `method` 为递归节点，每个节点有简短的动作 `label` 和非空的 `process`，可带 `children`。每个 `process` 项是一个 `text` 短句或一个 `latex` 公式。给本题的已知量、代入式或得到的结论，例如「由圆方程定半径」对应 `r^2=2\Rightarrow r=\sqrt2`。共用步骤只写一次，结束节点给实际结果。新卡全部填写过程。旧存档整页均无过程时可按原来的方法树重现。

核对每个过程框确实执行同行的左栏动作。后台检查主要宽度下的区域顺序、树分支、逐行箭头和框线、公式与题图显示。验回全部原题身份、专题切换和 MathML 后，用原路径替换交付页。
