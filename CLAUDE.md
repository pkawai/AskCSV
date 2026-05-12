# AskCSV — Claude Code context

## What this is
An AI-powered CSV data analyst (web app) built for the AUM "AI-First Agentic Development" course, Spring 2026, Project 3. Drop a CSV → app auto-cleans, profiles, suggests charts, and lets you ask plain-English questions that get answered with a chart + insight.

## Architecture in one paragraph
Flask web app. User uploads a CSV → server parses + cleans (`src/ingest.py`, `src/cleaner.py`) → stores raw frame as parquet keyed by session_id → renders profile dashboard (`src/profiler.py`) and rule-based chart suggestions (`src/chart_suggester.py`). For NLQ: user question + privacy-safe schema summary → Groq (Llama 3.3 70B with `openai/gpt-oss-120b` fallback) → tool-use loop that chains 6 safe pandas operations (`src/tools.py`) → chart + insight. Sessions stored in SQLite (`src/storage.py`). Frontend is vanilla JS + Plotly.

## Hard rules
- **Raw rows never leave the server.** Only schema summaries and aggregated tool results are sent to the LLM.
- **No arbitrary code execution.** The LLM cannot call `eval`, `exec`, or arbitrary pandas. It can only call the 6 tools defined in `src/tools.py`.
- **Local-only.** No deployment, no auth, no multi-user. Single-user demo from `localhost:5000`.

## The 6 safe tools (`src/tools.py`)
1. `filter(column, op, value)` — op ∈ eq, ne, lt, le, gt, ge, in, contains, between
2. `groupby_aggregate(group_cols, agg_col, agg_func)` — func ∈ sum, mean, median, min, max, count, nunique
3. `sort(by, ascending)`
4. `top_n(n, by)`
5. `correlate(col_a, col_b)`
6. `plot(kind, x, y, color?, title)` — kind ∈ bar, line, scatter, box, hist, heatmap, pie

## Project layout
```
AskCSV/
├── app.py                       Flask entry point
├── src/                         Backend modules (ingest, cleaner, profiler, tools, nlq_engine, ...)
├── templates/index.html         Single-page UI
├── static/                      CSS + JS
├── data/samples/                sales.csv, hr.csv, weather.csv for testing
├── data/sessions/               Per-session parquet frames (gitignored)
├── scripts/poc_nlq.py           Day-1 validation script — keep working at all times
├── tests/                       pytest
└── .claude/                     skills, MCP config, commands (added in PR #8)
```

## LLM provider
- **Default model:** `llama-3.3-70b-versatile` on Groq (free tier, OpenAI-compatible API at https://api.groq.com/openai/v1)
- **Fallback model:** `openai/gpt-oss-120b` — used when Llama 3.3 emits a malformed `<function=...>` tool call (Groq returns `tool_use_failed` 400)
- **No prompt caching on Groq.** We cache full responses by `(session_id, normalized_question)` in SQLite instead.
- **Env var:** `GROQ_API_KEY` (read from `.env`)

## Build phases (current state evolves)
- ✅ Day 1: PoC validates 6/6 questions produce charts
- 🚧 PR #1 (in progress): project skeleton, smoke tests
- PR #2: ingest + clean
- PR #3: profile + rule-based chart suggester
- PR #4: the 6 tools, fully tested
- PR #5: Groq client wrapper with fallback + retry
- PR #6: NLQ engine + chat UI + response cache
- PR #7: AI-suggested analyses + follow-up chips
- PR #8: skills + MCP + Ralph Wiggum loop (course requirements)
- PR #9: HTML report export
- PR #10: polish + demo prep

## Conventions
- Mirror `task-manager/` patterns: `app.py` factory + routes, `src/` modules, single `templates/index.html`, vanilla JS frontend, pytest.
- One feature branch per PR. No commits direct to main.
- Test before merging. `pytest -v` must be green.

## Anti-features (do NOT add)
- User accounts / auth
- Multi-CSV joins
- In-browser data editing
- Custom chart styling controls
- Streaming LLM responses
- Vector search / RAG / embeddings
- Excel / Parquet / JSON ingest — CSV only
- A 7th "arbitrary pandas eval" tool
- Render / Vercel / any deployment
- Mobile-responsive design

## Useful commands
```bash
# setup
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # add GROQ_API_KEY

# dev
python app.py           # localhost:5000
pytest -v               # all tests
python scripts/poc_nlq.py  # re-validate the NLQ tool-use loop
```
