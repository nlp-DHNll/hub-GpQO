作业要求：参考课件用 openai agents 搭建的 sql agent（课件项目不随仓库分发），使用 langchain 复刻一遍，写出代码。

## 完成

复刻实现见 `./sql-agent-langchain/`（LangChain + LangGraph）：

- 4 个 LLM Agent 用 `ChatPromptTemplate + ChatOpenAI.with_structured_output` 复刻，提示词/数据契约与原版一致；
- 编排用 LangGraph `StateGraph` 复刻原版的显式状态机（选表反馈重试、共享 3 次修复预算、空结果跳过汇总、汇总降级）；
- `db/`（catalog/validator/executor）、日志、CLI 行为与原版一致；
- 23 个 pytest（mock LLM）+ ruff 全部通过，真实 LLM 冒烟三条路径（单表聚合 / 两表 JOIN / 无关问题澄清）通过，运行截图验证见 `./screenshots/`（4 张终端截图）。

详见 `./sql-agent-langchain/readme.md` 的框架对照表。

## 数据库准备

`ref/` 目录（课件下发的 `chinook.db`）为课程内容，**不随仓库分发**（已加入 `.gitignore`）。clone 后运行或测试前，请将课件的 `chinook.db` 放到 `sql-agent-langchain/ref/` 下——默认配置与 pytest 均依赖 `ref/chinook.db` 路径。
