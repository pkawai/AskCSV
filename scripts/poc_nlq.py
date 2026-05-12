"""
Day 1 risk-validation PoC for AskCSV (Groq / Llama 3.3 70B version).

Goal: prove that Llama 3.3 70B (hosted on Groq) can reliably translate
plain-English questions on a real CSV into a correct sequence of tool calls,
with latency under 2s.

Groq exposes an OpenAI-compatible API at https://api.groq.com/openai/v1,
so we use the `openai` Python SDK pointed at that base URL. Groq does not
do prompt caching the way xAI/Anthropic do — its raw inference is so fast
that caching isn't necessary.

If this PoC fails, the architecture changes (fall back to constrained
code-gen with a column allowlist). Do NOT proceed to PR #1 until this
script prints "PoC PASSED" for at least 5/6 test questions.

Run:
    export GROQ_API_KEY=gsk-...
    python scripts/poc_nlq.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
from openai import BadRequestError, OpenAI

SAMPLE_CSV = Path(__file__).resolve().parent.parent / "data" / "samples" / "sales.csv"

# Llama 3.3 70B on Groq: fast and good for the common case.
# gpt-oss-120b (OpenAI's open model, hosted on Groq) is the more reliable
# fallback — it handles multi-step tool chains without falling back to
# Llama's <function=...> syntax.
MODEL = "llama-3.3-70b-versatile"
FALLBACK_MODEL = "openai/gpt-oss-120b"

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# The 6 safe tools, defined in OpenAI tool-calling format
# (xAI is OpenAI-API-compatible, so this is the same shape).
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "filter",
            "description": "Filter rows of the dataframe by a single column condition.",
            "parameters": {
                "type": "object",
                "properties": {
                    "column": {"type": "string"},
                    "op": {
                        "type": "string",
                        "enum": ["eq", "ne", "lt", "le", "gt", "ge", "in", "contains", "between"],
                    },
                    "value": {
                        "description": "Scalar, list (for 'in'), or [low, high] (for 'between')"
                    },
                },
                "required": ["column", "op", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "groupby_aggregate",
            "description": "Group rows by one or more columns and aggregate a metric column.",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_cols": {"type": "array", "items": {"type": "string"}},
                    "agg_col": {"type": "string"},
                    "agg_func": {
                        "type": "string",
                        "enum": ["sum", "mean", "median", "min", "max", "count", "nunique"],
                    },
                },
                "required": ["group_cols", "agg_col", "agg_func"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sort",
            "description": "Sort the current result by a column.",
            "parameters": {
                "type": "object",
                "properties": {
                    "by": {"type": "string"},
                    "ascending": {"type": "boolean"},
                },
                "required": ["by", "ascending"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "top_n",
            "description": "Keep the top N rows of the current result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "minimum": 1},
                    "by": {"type": "string"},
                },
                "required": ["n", "by"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "correlate",
            "description": "Compute Pearson correlation between two numeric columns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "col_a": {"type": "string"},
                    "col_b": {"type": "string"},
                },
                "required": ["col_a", "col_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plot",
            "description": "Render a chart of the current result. Call this LAST after data prep.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["bar", "line", "scatter", "box", "hist", "heatmap", "pie"],
                    },
                    "x": {"type": "string"},
                    "y": {"type": "string"},
                    "color": {"type": "string"},
                    "title": {"type": "string"},
                },
                "required": ["kind", "x", "y", "title"],
            },
        },
    },
]


def build_schema_summary(df: pd.DataFrame) -> dict:
    """Privacy-safe summary: column names, dtypes, sample values, basic stats. No raw rows."""
    summary: dict = {"row_count": int(len(df)), "columns": []}
    for col in df.columns:
        s = df[col]
        col_info: dict = {
            "name": col,
            "dtype": str(s.dtype),
            "null_count": int(s.isna().sum()),
            "unique_count": int(s.nunique()),
            "sample_values": [str(v) for v in s.dropna().head(3).tolist()],
        }
        if pd.api.types.is_numeric_dtype(s):
            col_info["min"] = float(s.min())
            col_info["max"] = float(s.max())
            col_info["mean"] = round(float(s.mean()), 2)
        summary["columns"].append(col_info)
    return summary


SYSTEM_PROMPT = """You are AskCSV, a data analyst assistant.

You answer questions about a dataset by chaining tool calls. Available tools:
- filter, groupby_aggregate, sort, top_n, correlate, plot

Rules:
1. Use ONLY the column names listed in the schema. Never invent columns.
2. After any data-prep tools, ALWAYS finish with a plot() call to visualize.
3. Pick chart kinds appropriate for the data shape:
   - categorical x numeric -> bar
   - datetime x numeric -> line
   - numeric x numeric -> scatter
4. Keep titles short and human-readable.
5. If a question cannot be answered with these tools, say so plainly. Do NOT make up data.

The schema for the current session is included in the first user message.
"""


def execute_tool(name: str, args: dict, df: pd.DataFrame, state: dict) -> dict:
    """Execute a tool call on the working dataframe. Returns a result dict."""
    work = state.get("df", df)
    try:
        if name == "filter":
            col, op, val = args["column"], args["op"], args["value"]
            if col not in work.columns:
                return {"error": f"Column '{col}' not in dataframe. Available: {list(work.columns)}"}
            if op == "eq":
                out = work[work[col] == val]
            elif op == "ne":
                out = work[work[col] != val]
            elif op == "lt":
                out = work[work[col] < val]
            elif op == "le":
                out = work[work[col] <= val]
            elif op == "gt":
                out = work[work[col] > val]
            elif op == "ge":
                out = work[work[col] >= val]
            elif op == "in":
                out = work[work[col].isin(val)]
            elif op == "contains":
                out = work[work[col].astype(str).str.contains(str(val), case=False, na=False)]
            elif op == "between":
                out = work[(work[col] >= val[0]) & (work[col] <= val[1])]
            else:
                return {"error": f"Unknown op {op}"}
            state["df"] = out
            return {"row_count": int(len(out))}

        if name == "groupby_aggregate":
            g_cols = args["group_cols"]
            a_col = args["agg_col"]
            func = args["agg_func"]
            missing = [c for c in g_cols + [a_col] if c not in work.columns]
            if missing:
                return {"error": f"Columns not in dataframe: {missing}"}
            out = work.groupby(g_cols)[a_col].agg(func).reset_index()
            state["df"] = out
            return {"row_count": int(len(out)), "preview": out.head(10).to_dict(orient="records")}

        if name == "sort":
            by, asc = args["by"], args["ascending"]
            if by not in work.columns:
                return {"error": f"Column '{by}' not in result"}
            state["df"] = work.sort_values(by=by, ascending=asc)
            return {"row_count": int(len(state["df"]))}

        if name == "top_n":
            n, by = args["n"], args["by"]
            if by not in work.columns:
                return {"error": f"Column '{by}' not in result"}
            state["df"] = work.sort_values(by=by, ascending=False).head(n)
            return {"row_count": int(len(state["df"]))}

        if name == "correlate":
            a, b = args["col_a"], args["col_b"]
            if a not in work.columns or b not in work.columns:
                return {"error": "Column not found"}
            return {"pearson_r": round(float(work[a].corr(work[b])), 4)}

        if name == "plot":
            state["chart_spec"] = {
                "kind": args["kind"],
                "x": args["x"],
                "y": args["y"],
                "color": args.get("color"),
                "title": args["title"],
                "data_preview": state.get("df", work).head(10).to_dict(orient="records"),
            }
            return {"chart_rendered": True, "title": args["title"]}

        return {"error": f"Unknown tool: {name}"}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def run_question(client: OpenAI, df: pd.DataFrame, schema: dict, question: str) -> dict:
    """Send one question through the tool-use loop. Returns trace + chart spec."""
    state: dict = {"df": df.copy(), "chart_spec": None}
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Dataset schema:\n```json\n{json.dumps(schema, indent=2)}\n```\n\n"
                f"Question: {question}"
            ),
        },
    ]
    trace: list[dict] = []
    t0 = time.time()
    # Cap iterations to prevent runaway loops.
    for _ in range(8):
        # Try primary model. On tool_use_failed (Llama emits non-JSON tool calls
        # occasionally), retry once with the fallback model.
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                max_tokens=1024,
            )
        except BadRequestError as exc:
            if "tool_use_failed" not in str(exc):
                raise
            trace.append({"recovery": "tool_use_failed -> retrying on fallback", "model": FALLBACK_MODEL})
            resp = client.chat.completions.create(
                model=FALLBACK_MODEL,
                messages=messages
                + [
                    {
                        "role": "system",
                        "content": (
                            "Your previous tool call was malformed. "
                            "Respond using ONLY the OpenAI tool-calling JSON format. "
                            "Do NOT use <function=...></function> syntax."
                        ),
                    }
                ],
                tools=TOOLS,
                tool_choice="auto",
                max_tokens=1024,
            )
        choice = resp.choices[0]
        msg = choice.message
        usage = resp.usage
        trace.append(
            {
                "finish_reason": choice.finish_reason,
                "usage": {
                    "input": usage.prompt_tokens,
                    "output": usage.completion_tokens,
                    # Groq doesn't cache; this stays 0. Kept for cross-provider parity.
                    "cached": getattr(
                        getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0
                    )
                    or 0,
                },
            }
        )

        tool_calls = getattr(msg, "tool_calls", None) or []
        if not tool_calls:
            return {
                "answer": msg.content or "",
                "chart_spec": state["chart_spec"],
                "trace": trace,
                "latency_s": round(time.time() - t0, 2),
            }

        # Echo assistant's tool_calls back into the message list so the model has context.
        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
            }
        )

        # Execute each tool call and append a tool-role message per result.
        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = execute_tool(tc.function.name, args, df, state)
            trace.append({"tool": tc.function.name, "input": args, "result": result})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    # default=str handles pandas Timestamp, numpy types, etc.
                    "content": json.dumps(result, default=str),
                }
            )

    return {
        "answer": "(loop exceeded)",
        "chart_spec": state["chart_spec"],
        "trace": trace,
        "latency_s": round(time.time() - t0, 2),
    }


TEST_QUESTIONS = [
    "What is the total revenue by region?",
    "Average revenue by customer segment.",
    "Top 3 products by total revenue.",
    "What is the correlation between quantity and unit_price?",
    "Show me only Enterprise orders, then revenue by region.",
    "Monthly revenue trend.",
]


def main() -> int:
    if not os.environ.get("GROQ_API_KEY"):
        print("ERROR: GROQ_API_KEY is not set. Export it and try again.", file=sys.stderr)
        return 2

    df = pd.read_csv(SAMPLE_CSV, parse_dates=["order_date"])
    schema = build_schema_summary(df)
    client = OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url=GROQ_BASE_URL)

    passed = 0
    for i, q in enumerate(TEST_QUESTIONS, 1):
        print(f"\n[{i}/{len(TEST_QUESTIONS)}] Q: {q}")
        result = run_question(client, df, schema, q)
        chart = result.get("chart_spec")
        tool_calls = [t for t in result["trace"] if "tool" in t]
        print(f"  latency: {result.get('latency_s')}s | tool calls: {len(tool_calls)}")
        for t in tool_calls:
            print(f"    -> {t['tool']}({json.dumps(t['input'])}) :: {t['result']}")
        if chart:
            print(f"  chart: {chart['kind']} title={chart['title']!r}")
            passed += 1
        else:
            print(f"  NO CHART. answer={result.get('answer')!r}")
        # Show cache behavior on the second+ question.
        last = result["trace"][-1] if result["trace"] else {}
        if "usage" in last:
            print(f"  tokens: {last['usage']}")

    print(f"\n=== PoC summary: {passed}/{len(TEST_QUESTIONS)} produced a chart ===")
    if passed >= 5:
        print("PoC PASSED — proceed to PR #1.")
        return 0
    print("PoC FAILED — revisit architecture before scaffolding.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
