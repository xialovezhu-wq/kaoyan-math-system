# MarginNote 可视化错题导入流程

本流程用于把 MarginNote 4 中的题目图片、解析图片和解析文字迁移到 Obsidian 可见的单题详情页。它是视觉详情层，不替代 wrongnet 的正式错题卡，也不改变回滚复习账本。

## 适用场景

- 用户提供 MarginNote 4 导出的 `docx`、脑图 `PDF`、学习集备份或同源小样本包。
- 用户要求在 Obsidian 中直接看到题目图片，并且解析默认折叠。
- 用户做完题后，需要 Codex 复述题目、判断连线位置、识别是否为正式错题或候选错题。

## 预读文件

每次处理 MarginNote 可视化导入前读取：

1. `README.md`
2. `错题知识网络/README.md`
3. `错题知识网络/AI维护规则.md`
4. `错题知识网络/schema/ingest.md`
5. `错题知识网络/schema/query.md`
6. `错题知识网络/schema/lint.md`
7. `错题知识网络/wiki/index.md`
8. `错题知识网络/wiki/log.md`
9. `错题知识网络/可视化错题详情/index.md`
10. 相关 `错题知识网络/错题卡/{GS|LA|PR|MX}-*.md` 轻量字段

## index/log 检索式访问

- `wiki/index.md` 不通读：新条目写在文件头部；先读头部最近约 100 行，再按 `wrongnet_id`、visual_id、source_locator、来源 ID 或关键词用 `rg` 检索。
- `wiki/log.md` 不通读：新条目写在文件尾部；先读尾部最近约 200 行。更早视觉导入历史查 `wiki/log_archive/YYYY-MM.md`。

## 导出格式优先级

首批试点推荐同一焦点分支导出 3-5 道题，并尽量同时提供：

1. `导出到 OmniOutliner (.oo3)`：主结构输入。`.oo3` 包内的 `contents.xml` 保留节点层级、节点标题、note 图片引用、子节点解析文字，包内 PNG 可直接作为 Obsidian 图片资产来源。
2. `导出到 MS Word(docx)`：辅助输入。用于快速预览文本层、抽取嵌入图片、检查公式和节点顺序是否与 `.oo3` 一致。
3. `导出脑图为 PDF 格式`：可选视觉校验。用于人工核对脑图整体位置，不作为第一版自动导入主输入。
4. `导出学习集备份`：raw 备份，只保存，不在第一版强行解析。

如果只能选一种，优先使用 `.oo3`。如果没有 `.oo3`，再使用 `docx`。如果 `docx` 丢图或图片顺序不稳定，再用脑图 `PDF` 切图或 OCR。`导出文档为压平 PDF` 仅在题目和解析主要位于原 PDF 文档页时使用。

## 目录边界

- 原始导出包：`错题知识网络/raw_sources/marginnote_exports/`，大体积原件也可以保留在用户指定外部路径，并在索引中登记绝对路径。
- 题图和解析图资产：`错题知识网络/assets/visual_wrong_questions/{wrongnet_id}/`
- Obsidian 单题详情页：`错题知识网络/可视化错题详情/{subject}/{wrongnet_id}_标题待确认.md`
- 视觉详情索引：`错题知识网络/可视化错题详情/index.md`
- 机器可读清单：`错题知识网络/可视化错题详情/manifest.json`

raw export 原件只读。导入时只从原件抽取副本图片、OCR 文本和详情页，不改写原始导出文件。

## 单题详情页字段

```yaml
---
visual_id: GS-905
wrongnet_id: GS-905
source_app: MarginNote 4
source_export: 错题知识网络/raw_sources/marginnote_exports/xxx.docx
source_locator: 待确认
status: imported
last_updated: YYYY-MM-DD
---
```

正文必须包含：

- `## 题目`：直接嵌入题目图片。
- 折叠解析块：使用 Obsidian callout，默认折叠。
- `## 复述`：题目定位、正确第一步、核心方法、易错触发。
- `## 连线建议`：wrongnet、知识点、方法页、错因模式、触发页。
- `## 入库判断`：`review_only`、`candidate_card`、`formal_card_needed`、`already_in_wrongnet`。

未知字段写 `待确认`、`未记录`、`待补充`，不得编造。

## 允许动作

- 保存 MarginNote 导出包到 raw source 目录。
- 从导出包抽取题图、解析图和 OCR 文本副本。
- 新建或更新 `可视化错题详情/` 中的详情页。
- 更新 `可视化错题详情/index.md` 和 `manifest.json`。
- 在 `wiki/index.md`、`wiki/log.md` 登记视觉来源处理状态。
- 基于详情页、正式错题卡和 wiki 轻量字段，给出题目复述和连线建议。

## 禁止动作

- 不把完整题图、完整题干、完整长解析写进 `错题卡/*.md`。
- 不手改 `错题知识网络/生成/`。
- 不修改 `数学一回滚复习系统/复习单元.json` 或 `复习记录.jsonl`。
- 不把 Tutor 结果反写掌握度。
- 不凭图片内容编造用户错因、掌握度、做错日期、知识点或来源页码。
- 不把视觉详情页当作正式 wrongnet 源数据；正式复做召回仍以 `错题卡/*.md` 为准。

## 导入流程

1. 将用户提供的小样本包放入 `raw_sources/marginnote_exports/`，或在索引中登记外部绝对路径，保留原文件名。
2. 优先解析 `.oo3/contents.xml`：读取节点标题、层级、note 中的 `cell refid`，再把 refid 映射到同名 PNG。
3. 用 `docx` 或 `textutil` 输出校验文本顺序；若 `.oo3` 与 `docx` 顺序冲突，以 `.oo3` 的节点层级为主。
4. 按 `wrongnet_id` 建立资产目录，命名为 `question_01.png`、`solution_01.png`、`solution_02.png`。
5. 用模板创建单题详情页，题目图片直接显示，解析图片和 OCR/节点文字放入折叠块。
6. 读取对应错题卡轻量字段，补充 knowledge、methods、error_causes、method_gap 和相关 wiki 链接。
7. 更新视觉详情索引和 `manifest.json`。
8. 在 `wiki/log.md` 记录本次视觉导入，不运行 `wrongnet.py rebuild`。

## 做题后复述与连线

用户做完题后，基于详情页和 wrongnet 卡片输出：

- 题目复述：只写一句到三句定位，不复制完整题干。
- 正确第一步：写成可执行动作句。
- 连线建议：知识点、方法页、错因模式、触发页、相关旧题。
- 错题判断：`仅复习题`、`候选错题`、`已在 wrongnet`、`需要正式入库`。
- Obsidian 链接：优先给详情页链接；必要时再给图片文件路径。

如果判断需要正式入库或更新错题卡，必须切换到数学正式错题入库流程，读取 `录入模板.md`、`知识点库.md` 和相关旧卡。只要修改 `错题卡/*.md`，必须运行：

```bash
python3 错题知识网络/scripts/wrongnet.py rebuild
```

只更新视觉详情层、wiki index/log 或 manifest 时，不运行 rebuild。

## lint 检查

视觉详情层 lint 至少检查：

- `manifest.json` 是否为合法 JSON。
- `index.md` 中登记的详情页和图片资产是否存在。
- 每个 `wrongnet_id` 是否存在对应正式错题卡，若不存在标记 `candidate_card` 或 `待确认`。
- 解析是否默认折叠。
- 是否误改 `错题卡/`、`生成/` 或回滚 JSON。
- 是否把完整解析复制进正式错题卡或 Tutor safe source。
