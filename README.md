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
pytest -v
```

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

## Git workflow
- One feature branch per PR. Merged with `--no-ff` to preserve history.
- `pytest` green before merge.
- No commits direct to `main`.

## License
Coursework — not for redistribution.
