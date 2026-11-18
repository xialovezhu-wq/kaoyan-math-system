# 数学提示词与当前题场景审阅

本分支从公开审阅提交 `71782a75a884c28e7056895cfc5709f22e30327b` 接续，只交付数学拥有的通用源码、模板与隔离用例。

| 入口 | 可核对的行为 |
| --- | --- |
| question-worker | 用当前题设与真实作答组织讲解，说明考频统计范围、成立条件和关键推导。题号、焦点、授权视图及版本相同的追问复用完整读回。独立思考等待本人作答。 |
| wrong-intake | 保存原始角色、顺序、附件和已展示解答。明确“保存并回顾”由教学层先完成回顾；末条可见回顾可用 end-assistant-line 纳入同一个包。保存后返回回执。旧 recap 参数可解析，并返回 reuse_teaching_context。 |
| enhancement-intake / nightly-qa | 本地授权批次沿既有冻结、证据审核、单写者、原事件和读回办理。已有网页包才进入专门参考。 |
| 鞍面场景 | 正常讲题按“驻点不一定是极值”选到 saddle-sections-tangent 的第 2 版。保护视图过滤派生场景。两个截面分别说明如何排除极小、极大，水平切平面说明必要条件的方向。 |

正常示例由 `math_teaching_visual.py --recipe` 渲染，再由 `codex-skill-sources/kaoyan-math-question-worker/scripts/render_math_flow.py --figure` 合入当前题页，或用同目录 `math_sidebar.py` 为片段生成独立页面。切换或拖动后，复制按钮读取当前参数、题目/焦点/视图、场景及状态版本、页面实例和提问；剪贴板不可写时提供可选中的原文。T3 的自动传回由宿主维护。操作不计入学习事件。

审阅树现在包含已有的 `references/visual-recipes.md`、方法图脚本和模板，以及增强接收的 `references/t9-intermediates.md`。共享渲染器与 T3 宿主合同由实际安装环境提供。公开参考中的 `${MATH_COLD_ROOT}`、`${STUDY_ARCHIVE_ROOT}` 表示按宿主存储映射解析的位置。快照里的旧 GPT 项目说明仍属保存资料；当前数学教学覆盖高数、线代、概率。真实学习数据、日常会话、账户配置、已生成学习页和私有仓库历史未列入本批导出白名单。
