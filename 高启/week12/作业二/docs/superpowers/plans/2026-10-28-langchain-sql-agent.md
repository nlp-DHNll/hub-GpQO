# LangChain SQL Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create an independent LangChain-based copy of the existing Chinook SQL agent.

**Architecture:** Replace OpenAI Agents SDK model calls with cached LangChain ChatPromptTemplate and ChatOpenAI structured-output Runnables. Preserve deterministic Python orchestration, SQL validation, read-only execution, bounded repair, CLI behavior, Pydantic contracts, and fixture database.

**Tech Stack:** Python 3.10+, LangChain Core, LangChain OpenAI integration, Pydantic, SQLAlchemy, SQLite.

**Spec:** `docs/agent-design.md`

## Global Constraints

- Dependencies must be declared in `pyproject.toml`; no direct OpenAI Agents SDK imports remain.
- Database access remains read-only, and SQL validation uses `EXPLAIN` only.
- The copied Chinook fixture is unchanged; credentials stay in environment variables.
- Preserve the existing model override environment variables and CLI JSON contract.

## Review Focus

- No `OPENAI_API_KEY` at import time: construct model chains lazily and let CLI validate credentials.
- OpenAI-compatible provider base URL: route every model through configured `settings.base_url`.
- Structured output schema mapping: every stage must return the existing Pydantic contract.
- Repair loop and SQL tool boundary: LangChain must not execute or approve SQL.
- Empty result: do not call the summary chain for empty result sets.

---

### Task 1: Create the independent project copy

**Files:** `pyproject.toml`, `src/sql_agent/`, `tests/`, `docs/agent-design.md`, `ref/chinook.db`, `AGENTS.md`, `README.md`

- [x] Copy application, tests, design, and fixture without cache files or the reference notebook containing a hardcoded credential.
- [x] Declare `langchain-core` and `langchain-openai` dependencies.
- [x] Document install, configuration, CLI, and safety boundaries.

### Task 2: Replace model integration

**Files:** `src/sql_agent/agents/base.py`, four stage modules, `src/sql_agent/agents/__init__.py`, `src/sql_agent/workflow.py`

- [x] Implement a lazy cached ChatPromptTemplate → ChatOpenAI.with_structured_output Runnable factory.
- [x] Expose one async stage function for table selection, SQL generation, rewrite, and summarization.
- [x] Replace Runner.run / trace with direct async stage invocation while preserving prompts and type checks.

### Task 3: Update workflow test adapters

**Files:** `tests/test_workflow.py`

- [x] Patch the four async stage functions rather than the removed Runner API.
- [ ] Run the existing test suite and lint after implementation.
