# LangChain SQL Agent

基于 LangChain、SQLAlchemy 和 SQLite 的自然语言只读查询示例，使用 Chinook 数据库。

## 安装

```bash
python -m pip install -e .
```

## 配置

设置兼容 OpenAI Chat Completions API 的 `OPENAI_API_KEY`。`OPENAI_BASE_URL` 可选，默认读取 `src/sql_agent/config.py` 中配置的服务地址。可通过 `SQL_AGENT_MODEL` 和 `SQL_AGENT_SUMMARY_MODEL` 覆盖模型名。

## 运行

```bash
python -m sql_agent "总共有多少张专辑？"
```

CLI 将结构化 JSON 写到标准输出，日志写到标准错误。也可以安装后使用 `sql-agent` 命令。

## 工作流

```text
自然语言问题 → LangChain 表选择 → LangChain SQL 生成 → 确定性安全校验
→ 只读执行（必要时有限次 LangChain 修复）→ LangChain 结果汇总
```

LangChain 负责模型步骤和 Pydantic 结构化输出；数据库访问始终由 Python 代码控制。校验器只通过 `EXPLAIN` 检查 SQL，执行器使用只读 SQLite 连接并限制运行时间、行数和单元格长度。
