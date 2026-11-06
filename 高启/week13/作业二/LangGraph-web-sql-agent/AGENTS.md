# AGENTS.md

## Project structure

- Application code: `src/sql_agent_web/`; web assets: `src/sql_agent_web/web/`; tests: `tests/`; design: `docs/agent-design.md`.
- `ref/chinook.db` is the read-only Chinook fixture. Do not edit it.
- The workflow is a LangGraph `StateGraph` over LangChain structured-output Runnables: table selection, SQL generation, validation, bounded repair, read-only execution, and result summarization.
- Keep generated SQL validation and database execution in deterministic Python. The LLM must never execute SQL or decide whether SQL is safe.

## Runtime

- Python 3.10 or newer. Dependencies are declared in `pyproject.toml` (`langgraph`, `langchain-core`, `langchain-openai`, `python-dotenv`, and SQLAlchemy).
- Install with `python -m pip install -e .`.
- Start the web server from this directory with `python -m sql_agent_web.web`; open `http://127.0.0.1:8000`.
- The JSON API is `POST /api/query`; health check is `GET /api/health`.
- Put `OPENAI_API_KEY` and optionally `OPENAI_BASE_URL` in the project root `.env`, or set them in the process environment; model settings can be overridden with `SQL_AGENT_MODEL`, `SQL_AGENT_SUMMARY_MODEL`.
- The CLI writes logs to stderr and JSON to stdout. `--log-level` or `SQL_AGENT_LOG_LEVEL` controls log verbosity.

## Safety and behavior

- Every database connection is read-only. `SQLValidator` checks single-statement SELECT/WITH SQL and compiles with `EXPLAIN` only.
- Do not relax the validator, read-only URI, query timeout, row caps, or bounded repair loop.
- Empty query results skip the summary model and return the deterministic Chinese empty-result answer.
- Keep prompts, comments, and user-facing responses in Chinese. Never put API keys in source, docs, or fixtures.
