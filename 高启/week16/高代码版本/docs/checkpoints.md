# 开发检查点

以下命令在项目目录的 Conda `py312` 环境中运行。

## 阶段 1：命令行入口

运行 `python main.py --help` 查看参数。省略月份时，按北京时间取上一个完整自然月。传入 `2026-13` 等无效月份时，命令会提示错误并返回退出码 2。

## 阶段 2：运行状态和日志

每次运行生成一个 UTF-8 文件 `logs/<run_id>.jsonl`，每行记录一件事。首行提供运行编号、报告月份和 UTC 开始时间。步骤结束事件提供 `duration_ms`，业务事件提供搜索数量、评价结论等信息，最后一行给出运行状态及报告路径或失败原因。

可以在 Python 中运行这个示例：

```python
from backend.enums import StepName
from backend.errors import RunFailure
from backend.run_tracking import run_with_logging

def example(run):
    with run.step(StepName.SEARCH, attempt=1) as logger:
        logger.record("search_results", details={"count": 0})
        raise RunFailure("示例：没有可用资料")

result = run_with_logging("2026-10", example)
print(result.state.status, result.state.step.duration_ms)
print(result.log_path)
```

查看 `step_failed` 的步骤耗时和 `run_failed` 的失败原因。

## 阶段 3：离线 Agent 流程

```shell
python main.py 2026-10 --offline
```

命令使用合成资料，先补齐来源清单，再删去摘要重复句，共用两轮修正。打开终端给出的 `reports/offline/` 报告和 `logs/` 日志，核对补搜主题、两类评价结论、修正轮次及保存结果。

## 阶段 4：真实检索和原文核验

在 `py312` 环境中安装依赖并运行检索。DDGS 网页搜索无需设置 API 密钥。

```shell
python -m pip install -r requirements.txt
python main.py 2026-10 --sources-only
```

从 `reports/sources/` 打开资料清单，检查每条资料的原文链接、发布日期和摘录。从日志检查主题查询、补搜和资料剔除原因。DDGS 查询包含目标年月，入选资料必须有可核实的原文发布日期。核验范围为 `backend/clients/source_pages.py` 中列出的公开 HTML 网页。

首轮搜索同时查询 DDGS、国家能源局、生态环境部、国家发展改革委、ISSB、上交所和港交所。上交所查询中国神华，港交所还查询中煤能源、兖矿能源和华能国际。固定官网栏目首轮查询一次，补搜对缺资料的主题换一组 DDGS 关键词。官网栏目只覆盖其公开列表中展示的文章，交易所查询使用目标月份的起止日期。

在日志中查看 `search_provider_results` 的候选和 PDF 数量、`search_provider_failed` 的失败原因，以及 `source_provider_verified` 的原文核验通过数量。同一网页可被多个入口发现，最终资料清单会合并重复来源。公告 PDF 计入候选数量，现阶段引用限于已核验的 HTML 原文。

可运行 `python -m unittest discover -s tests -v` 检查月份边界、入口故障隔离和网页原文核验。

## 阶段 5：DeepSeek 报告生成和双评价

安装项目依赖，在项目根目录的 `.env` 设置 `DEEPSEEK_API_KEY`。服务地址和模型可通过 `DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL` 指定。默认使用 DeepSeek 官方地址和 `deepseek-flash`。

可先单独检查 API。此命令通过同一份配置发送一条「你好」，并显示回复：

```shell
python -m backend.tools.check_deepseek_api
```

四个模型步骤读取 `backend/agent/prompts/` 中同名提示词。正文引用使用资料编号，来源清单和链接由程序生成。两类评价使用 JSON 结果。可读性调整只替换反馈章节内可定位的片段，若数字、引用或章节检查失败，则保留原稿并记录原因。

模型输出被截断时，当前步骤扩大输出预算重试一次。日志中的 `model_output_truncated` 记录该次预算，以及服务提供的 token 用量。该重试与五轮报告修正额度分别计算。

每次生成初稿或成功修正后，程序将当轮稿件保存至 `reports/drafts/<run_id>/`，日志中的 `draft_saved` 提供文件路径。可读性调整若未通过章节、数字或引用检查，会把原因交给模型在当前轮重试，最多三次。失败的调整不会占用五轮有效修正额度。

## 完整流程验收

运行 `python main.py 2026-10`，核对报告月份、章节、来源链接和输出路径。同月再次成功生成时，确认两份报告均可打开。用完五轮修正仍未通过时，确认终端和日志给出剩余问题，本次未生成报告。
