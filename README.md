# AskCSV

AI-powered CSV data analyst. Drop in a spreadsheet, get clean data, smart charts, and an LLM analyst that answers plain-English questions.

> Built for AUM **AI-First Agentic Development** (Spring 2026), Project 3.

## What it does
1. **Upload a CSV.** Encoding, dtypes, and date columns are auto-detected.
2. **Auto-profile.** Per-column stats, missing-value heatmap, correlation matrix.
3. **Auto-suggested charts.** Rule-based picks driven by column dtypes.
4. **AI analyst.** Ask plain English ("average revenue by region for orders over $500"). The model chains a small set of safe tools (`filter`, `groupby_aggregate`, `sort`, `top_n`, `correlate`, `plot`) and returns a chart + insight.
5. **Export a report.** Standalone HTML with every chart and insight from your session.

Privacy: raw rows never leave your machine — only schema summaries and aggregated results are sent to the LLM.

## Setup
```bash
git clone <repo-url> AskCSV && cd AskCSV
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # paste your GROQ_API_KEY (free tier at https://console.groq.com/keys)
python app.py          # http://127.0.0.1:5000
```

## Tests
```bash
pytest -v   # 120+ tests, all mocked — no network required
```

## Demo walkthrough (Week 16, ~7 minutes)

1. `python app.py`, open `http://127.0.0.1:5000`.
2. Drag `data/samples/sales.csv` onto the upload zone.
3. **Overview** card appears: rows, columns, encoding, duplicates removed.
4. **Columns** grid shows per-column dtype + null / unique counts.
5. **Missing values** bar chart and **Correlation matrix** heatmap render.
6. **Suggested charts** grid shows 4–6 rule-based suggestions.
7. **Ask the analyst** panel appears. Try:
   - "average revenue by region"
   - "top 3 products by total revenue"
   - "monthly revenue trend"
8. Each turn shows: question, insight, Plotly chart, follow-up chips,
   expandable **Tool trace** with every `groupby_aggregate`/`filter`/`plot` call.
9. Click a follow-up chip → second answer renders, often with **cached** badge.
10. Token chip in the header updates after every call (`5 calls · 7,832 tokens`).
11. Click **Export report ↗** in the chat header — standalone HTML opens
    with the whole session.
12. In a terminal, run `pytest -v` to show the test suite is green.
13. Walk through `git log --oneline --graph` to show the 10 PRs with proper
    merge commits.

## Tech stack
- **Backend:** Flask 3.0+, pandas 2.2+, pyarrow (parquet sessions), SQLite (response cache).
- **LLM:** Groq (OpenAI-compatible API). Primary `llama-3.3-70b-versatile`, fallback `openai/gpt-oss-120b`.
- **Frontend:** vanilla JS + Plotly.js (no build step).
- **Tests:** pytest.

## Project layout
```
AskCSV/
├── app.py                  Flask entry point
├── src/                    ingest, cleaner, profiler, chart_suggester, tools, nlq_engine, ...
├── templates/              index.html, report.html
├── static/                 styles.css, app.js, plotly.min.js
├── data/samples/           Sample CSVs for the demo
├── data/sessions/          Per-session parquet (gitignored)
├── scripts/poc_nlq.py      Day-1 risk-validation script for the tool-use loop
├── tests/                  pytest suite
└── .claude/                skills, MCP, Ralph Wiggum loop (course requirements)
```

## Sharing publicly

AskCSV runs locally by default. Three ways to share it:

### Option A — ngrok (fastest, 60 seconds, temporary)

For a one-off demo where you want a public URL anyone can hit:

```bash
# 1. Install ngrok once (https://ngrok.com/download)
brew install ngrok          # macOS

# 2. Start AskCSV
python app.py               # runs on localhost:5000

# 3. In a second terminal, open a tunnel
ngrok http 5000
```

ngrok prints a public HTTPS URL like `https://a1b2-c3d4.ngrok-free.app` — share it with anyone, they hit your local app. Free tier sessions live ~2 hours; restart for a new URL. **Anyone with the URL can use your API keys** — only share during active demos.

### Option B — Render (free, permanent)

For a long-lived public URL (e.g. to show your instructor a week later):

1. Push to GitHub (already done at https://github.com/pkawai/AskCSV).
2. Sign up at https://render.com (free tier, no card).
3. New → Web Service → connect the repo.
4. Build command: `pip install -r requirements.txt`
5. Start command: `gunicorn 'app:create_app()'` (add `gunicorn` to requirements.txt).
6. Add env vars in Render's dashboard: `GROQ_API_KEY`, `GEMINI_API_KEY`, `LLM_PROVIDER`.
7. Deploy. Render gives you `https://askcsv-<random>.onrender.com`.

Cost: $0 on free tier. Caveat: free Render workers sleep after 15 min idle; first hit after sleep takes ~30s to wake.

### Option C — Hugging Face Spaces (free, permanent, designed for ML demos)

If you want a `huggingface.co/spaces/...` URL that doubles as a portfolio piece:

1. Sign in at https://huggingface.co with GitHub.
2. New Space → SDK: Docker (or use the included Flask Dockerfile template).
3. Push your repo. HF builds + serves it automatically.
4. Add `GROQ_API_KEY` and `GEMINI_API_KEY` as Space secrets.

### About cost / abuse risk

All three options expose your LLM API keys to anyone who can hit the public URL. Risk levels:

- **ngrok**: low if you only run it during demos
- **Render / HF Spaces**: someone could rate-limit your free LLM tiers (no real cost since free tier caps are hard)

To eliminate risk entirely, add a password gate or rotate the keys after a public session.

## Course integrations (in `.claude/`)
- **Skills** — `analyst-persona/SKILL.md` (insight tone + refusal rules) and
  `chart-picker/SKILL.md` (which chart kind for which data shape). Loaded by
  Claude Code on demand.
- **MCP server** — `settings.json` registers a filesystem MCP scoped to
  `data/samples/` so Claude can browse demo CSVs during dev without
  filesystem-wide access.
- **Ralph Wiggum loop** — `commands/ralph.md` is an autonomous test-fixer:
  it picks one failing test, fixes it, commits on green, repeats. Hard stop
  conditions prevent runaway loops.
- **Seed-tests command** — `commands/seed-tests.md` generates fixture-driven
  tests for the 6 safe tools from any CSV path.

## Git workflow
- One feature branch per PR. Merged with `--no-ff` to preserve history.
- `pytest` green before merge.
- No commits direct to `main`.

## License
Coursework — not for redistribution.
