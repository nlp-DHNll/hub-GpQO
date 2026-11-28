# ESG Agent Skills 练习项目

本项目按题目整理两个可复用的 Agent skill。skill 用于指导 Agent 自主检索公开网页、筛选并核验信息，再生成 Markdown 报告。

## Skills

- `skills/shenhua-esg-monthly-report/SKILL.md`：汇总中国神华指定月份的 ESG 政策、行业实践、公司动态和同行行动，生成中文月报。
- `skills/esg-tender-intelligence/SKILL.md`：汇总近两年 ESG 相关中标信息，并检索最新招标公告，生成投标情报报告。

## 使用方式

在支持 Codex skills 的环境中，将对应 skill 文件夹放入可发现的 skills 目录，或显式引用其 `SKILL.md`。首次使用提供报告月份；投标情报 skill 默认以运行日为检索截止日，回溯两年，并注明检索时间。

神华月报 Skill 附带 Python 辅助工具：从项目根目录运行 `python skills/shenhua-esg-monthly-report/scripts/report_tools.py period YYYY-MM` 查看月份范围；报告完成后运行 `python skills/shenhua-esg-monthly-report/scripts/report_tools.py check "报告文件路径"` 检查引用编号与来源清单。工具只做结构核对，资料真实性仍由 Agent 核验。

每次报告必须附来源标题、发布机构、发布日期和原网页链接。无法确认的日期、内容或来源应标为待核验或排除，不能补写推测性事实。
