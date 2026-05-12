"""Natural-language query engine: question + CSV -> chart + insight.

The flow:
1. Load the session's dataframe + build a privacy-safe schema summary.
2. Check the SQLite NLQ cache by normalized question.
3. If miss: run a tool-use loop against Groq, where the LLM chains the 6
   safe tools to produce a chart and writes a final one-sentence insight.
4. Cache the result so the next identical question returns instantly.
"""
from __future__ import annotations

import json
import time
from typing import Any

import pandas as pd

from src import groq_client, prompts, storage, tools

MAX_LOOP_ITERATIONS = 8


def build_schema_summary(df: pd.DataFrame) -> dict[str, Any]:
    """Privacy-safe: column names, dtypes, sample values, basic stats. No raw rows."""
    summary: dict[str, Any] = {"row_count": int(len(df)), "columns": []}
    for col in df.columns:
        s = df[col]
        col_info: dict[str, Any] = {
            "name": col,
            "dtype": str(s.dtype),
            "null_count": int(s.isna().sum()),
            "unique_count": int(s.nunique(dropna=True)),
            "sample_values": [str(v) for v in s.dropna().head(3).tolist()],
        }
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            clean = s.dropna()
            if len(clean) > 0:
                col_info.update(
                    {
                        "min": float(clean.min()),
                        "max": float(clean.max()),
                        "mean": round(float(clean.mean()), 2),
                    }
                )
        elif pd.api.types.is_datetime64_any_dtype(s):
            clean = s.dropna()
            if len(clean) > 0:
                col_info["min"] = str(clean.min())
                col_info["max"] = str(clean.max())
        summary["columns"].append(col_info)
    return summary


def ask(session_id: str, question: str, *, use_cache: bool = True) -> dict[str, Any]:
    """Run the NLQ tool-use loop for a single question.

    Returns:
        {
          "chart_spec": dict | None,
          "insight": str,
          "tool_trace": list,
          "from_cache": bool,
          "latency_s": float,
        }
    """
    df = storage.load_dataframe(session_id)
    if df is None:
        raise ValueError(f"Unknown session: {session_id}")

    if use_cache:
        cached = storage.get_cached_nlq(session_id, question)
        if cached:
            return {**cached, "from_cache": True}

    schema = build_schema_summary(df)
    state = tools.ToolState(df=df.copy())
    client = groq_client.get_client()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompts.NLQ_SYSTEM_PROMPT},
        {"role": "user", "content": prompts.render_schema_user_message(question, schema)},
    ]

    t0 = time.time()
    final_text = ""

    for _ in range(MAX_LOOP_ITERATIONS):
        resp = client.chat(messages=messages, tools=tools.TOOL_SCHEMAS, max_tokens=1024)
        choice = resp.choices[0]
        msg = choice.message
        tool_calls = getattr(msg, "tool_calls", None) or []

        if not tool_calls:
            final_text = msg.content or ""
            break

        # Echo assistant's tool_calls back so the model sees its own moves.
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

        # Execute each tool, append the tool-role response.
        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = tools.dispatch(tc.function.name, args, state)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, default=str),
                }
            )

    result: dict[str, Any] = {
        "chart_spec": state.chart_spec,
        "insight": final_text.strip(),
        "tool_trace": state.history,
        "from_cache": False,
        "latency_s": round(time.time() - t0, 2),
    }

    # Only cache successful runs (a chart was actually produced).
    if use_cache and state.chart_spec is not None:
        storage.save_cached_nlq(session_id, question, result)

    return result
