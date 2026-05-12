"""AI-driven analysis suggestions + follow-up questions.

Both use Groq's JSON-mode (response_format={"type": "json_object"}) so we
get structured output without parsing free-form text.
"""
from __future__ import annotations

import json
from typing import Any

from src import groq_client, nlq_engine, prompts, storage

MAX_SUGGESTIONS = 5
MAX_FOLLOWUPS = 3


def suggest_analyses(session_id: str) -> list[dict[str, Any]]:
    """Ask the LLM to recommend N interesting analyses for this session's schema.

    Returns a list of {question, why, chart_kind} dicts.
    """
    df = storage.load_dataframe(session_id)
    if df is None:
        raise ValueError(f"Unknown session: {session_id}")

    schema = nlq_engine.build_schema_summary(df)
    client = groq_client.get_client()
    resp = client.chat(
        messages=[
            {"role": "system", "content": prompts.SUGGEST_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Schema:\n```json\n{json.dumps(schema, indent=2)}\n```",
            },
        ],
        max_tokens=512,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content or "{}"
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return []
    suggestions = data.get("suggestions", [])
    if not isinstance(suggestions, list):
        return []
    # Defensively limit and trim fields.
    out: list[dict[str, Any]] = []
    for s in suggestions[:MAX_SUGGESTIONS]:
        if not isinstance(s, dict) or not s.get("question"):
            continue
        out.append(
            {
                "question": str(s["question"])[:200],
                "why": str(s.get("why", ""))[:200],
                "chart_kind": str(s.get("chart_kind", "bar"))[:20],
            }
        )
    return out


def suggest_followups(question: str, insight: str, chart_kind: str) -> list[str]:
    """After answering a question, propose 3 clickable follow-up questions."""
    client = groq_client.get_client()
    context = (
        f"Original question: {question}\n"
        f"Chart kind shown: {chart_kind}\n"
        f"Insight delivered: {insight}\n"
    )
    resp = client.chat(
        messages=[
            {"role": "system", "content": prompts.FOLLOWUP_SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ],
        max_tokens=256,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content or "{}"
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return []
    followups = data.get("followups", [])
    if not isinstance(followups, list):
        return []
    return [str(f)[:120] for f in followups[:MAX_FOLLOWUPS] if f]
