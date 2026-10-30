# 作业2：用 LangChain 复刻 OpenAI Agents 版 SQL Agent

把 week11 基于 `openai/agents` SDK 的 SQL Agent，**仅替换 Agent 编排层**为 LangChain，
数据库解析、SQL 校验/执行、Pydantic 数据契约全部复用原实现，行为保持一致。

## 原版 vs 复刻版对照

| 能力 | 原版（agents SDK） | 复刻版（LangChain） |
| --- | --- | --- |
| 选表 Agent | `Agent(..., output_type=TableSelection)` | `ChatOpenAI(...).with_structured_output(TableSelection)` |
| 生成 SQL | `Runner.run(sql_generator_agent, prompt)` | `chain.invoke([SystemMessage, HumanMessage])` |
| 修复 SQL | `Runner.run(sql_rewriter_agent, prompt)` | 同上 |
| 结果汇总 | `Runner.run(result_summary_agent, prompt)` | 同上 |
| 工作流 | `workflow.py`（async） | `workflow_lc.py`（sync，逻辑 1:1） |

核心等价关系：

```python
# 原版
response = await Runner.run(agent, prompt)
result = response.final_output          # 一个 Pydantic 对象

# 复刻版（LangChain）
chain = ChatOpenAI(...).with_structured_output(PydanticModel)
result = chain.invoke([SystemMessage(agent.instructions), HumanMessage(prompt)])
```

`with_structured_output` 会利用模型的 function calling 能力，把结果直接绑定回
原来的 Pydantic 模型（`TableSelection / SQLDraft / FinalAnswer`），因此下游的
校验、执行、改写循环、降级汇总逻辑可以零改动复用。

## 文件

```
homework2_langchain_sql_agent/
├── _bootstrap.py     # 注入原作业 src 路径 + 用桩对象替掉 agents SDK
├── agents_lc.py      # LangChain 版四个 Agent（含与原版逐字一致的 instructions）
├── workflow_lc.py    # 工作流编排（选表→生成→校验/执行→改写→汇总）
├── main.py           # 命令行入口（单次 / --json / 交互）
├── requirements.txt
└── README.md
```

> 复刻版通过 `_bootstrap.py` 把 `Week12_2026Q2/week11/.../src` 注入 `sys.path`，
> 直接复用原 `sql_agent.models / config / db` 三个纯 Python 模块，
> 避免重复维护 schema 解析、SQL 安全门禁与执行器。

## 运行

```bash
pip install -r requirements.txt

export OPENAI_API_KEY="你的密钥"
# 默认指向 DeepSeek 兼容端点，可改为通义等：
# export OPENAI_BASE_URL="https://api.deepseek.com"
# export SQL_AGENT_MODEL="deepseek-chat"

# 单次提问
python main.py "每个艺术家的专辑数量，按数量降序排前 10"

# 输出完整 JSON（含 SQL / 证据 / 告警）
python main.py --json "销量最高的 5 首曲目"

# 交互模式
python main.py
```

## 与原版行为差异说明

1. **同步 vs 异步**：原版 `workflow.py` 为 `async`，复刻版改为同步方法
   （`chain.invoke`）。若需并发，把 `.invoke` 换成 `.ainvoke` 即可恢复异步。
2. **Agent 定义**：原版在 `agents/__init__.py` 导入 `agents` SDK；
   复刻版为避免该依赖，将四个 Agent 的 `instructions` 与温度内联声明
   （内容与原文件逐字一致），模型名复用 `sql_agent.config.settings`。
3. **结构化输出容错**：`with_structured_output` 依赖模型支持 function calling。
   若所用端点不支持，可改用 `with_structured_output(..., method="json_mode")`
   或在 `agents_lc._run` 中加 JSON 解析兜底。
4. **依赖复用**：原 `sql_agent` 包 `__init__` 会顺带导入 `workflow` / `agents` SDK。
   复刻版用 `_bootstrap.py` 注册一个轻量 `agents` 桩对象，使原包可被安全 import，
   而其中的 `models / config / db` 逻辑被真正复用。
