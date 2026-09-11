# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: Deep Research Assistant (深度研究助手)

Week 08 作业二. Takes a research topic and automates a research loop to produce a structured, source-cited report. The core README is the single spec for product behavior; `README.md`.

Pipeline (distinct from one-shot Q&A): **plan** (decompose into sub-questions) → **multi-round search** → **read & extract** → **judge & supplement** (iterate) → **synthesize report**.

The designed report must include four deliverables:
1. Structured report (summary, body sections, key conclusions, open questions)
2. Source list (each conclusion maps to URL/title, traceable)
3. Research process log (keywords, pages read, iteration rounds)
4. Confidence notes (reliability level, info cutoff, and mark unsourced conclusions as "model inference")

## External APIs & Configuration

Two providers are used; keys are read from `.env` (copy `.env.example`) or environment. **Never hardcode keys in code.** Real values never committed.

- **Bocha web-search** (`search.py`): `POST https://api.bocha.cn/v1/web-search`, header `Authorization: Bearer $BOCHA_API_KEY`, body `{"query": ..., "summary": true, "count": N}`.
- **DeepSeek LLM** (`llm.py`): OpenAI-compatible, `base_url=https://api.deepseek.com`, model `deepseek-chat`, key `DEEPSEEK_API_KEY`.

## Running

```bash
pip install -r requirements.txt          # openai requests python-dotenv
cp .env.example .env                     # fill BOCHA_API_KEY / DEEPSEEK_API_KEY
python -m research_assistant.cli "竞品分析：主题" [--rounds 3 --count 5 --questions 4]
```

Without keys the run automatically falls back to built-in no-op stubs (`NoLLM`/`NoSearch`) and still emits a template report — used for mock / smoke verification with zero network & no error.

## Architecture

Single package `research_assistant/`:

| file | responsibility |
|---|---|
| `config.py` | load `.env`, expose `ChatConfig`/`SearchConfig` |
| `schemas.py` | data structures: `SourceRef`, `SubQuestion`, `ProcessLog`, `Report` |
| `search.py` | Bocha web-search client -> `list[SourceRef]`; `NoSearch` stub |
| `llm.py` | DeepSeek chat/JSON client (`chat`, `chat_json`); `NoLLM` stub |
| `agent.py` | orchestration: plan -> search loops -> judge-supplement -> report |
| `report.py` | markdown rendering + source/confidence/"model inference" annotation |
| `cli.py` | argparse entrypoint |

Data flows top-down: `agent` produces a `Report` (with nested `ProcessLog` and collected `SourceRef`s); `report.render_full` is pure logic that renders traceability. LLM JSON outputs (sub-question plans, supplement decisions) are best-effort parsed and degrade gracefully to acceptable defaults rather than crashing.

## Conventions

