"""AI-driven analysis suggestions + follow-up questions.

Both use Groq's JSON-mode (response_format={"type": "json_object"}) so we
get structured output without parsing free-form text.
"""
from __future__ import annotations

import json
from typing import Any

from src import llm_client, nlq_engine, prompts, storage

MAX_SUGGESTIONS = 5
MAX_FOLLOWUPS = 3
MAX_DATA_IDEAS = 6
ALLOWED_DIFFICULTY = {"easy", "medium", "hard"}
ALLOWED_CATEGORY = {"analytics", "ml", "dashboard", "insight", "segmentation"}


def suggest_analyses(session_id: str) -> list[dict[str, Any]]:
    """Ask the LLM to recommend N interesting analyses for this session's schema.

    Returns a list of {question, why, chart_kind} dicts.
    """
    df = storage.load_dataframe(session_id)
    if df is None:
        raise ValueError(f"Unknown session: {session_id}")

    schema = nlq_engine.build_schema_summary(df)
    client = llm_client.get_client()
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


# Different LLMs / models return idea-list payloads under different keys.
# We try all of these in order before giving up.
_IDEA_LIST_KEYS = ("ideas", "projects", "suggestions", "items", "data", "results")
# Likewise, we accept multiple synonyms for each idea field.
_IDEA_TITLE_KEYS = ("title", "name", "project", "project_name", "heading")
_IDEA_WHAT_KEYS = ("what", "description", "desc", "summary", "details")
_IDEA_HOW_KEYS = ("how", "steps", "approach", "method", "implementation", "plan")
_IDEA_DIFFICULTY_KEYS = ("difficulty", "level", "complexity")
_IDEA_CATEGORY_KEYS = ("category", "type", "kind")


def _pick(d: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return d[k] for the first key in `keys` present in d. None if none match."""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _extract_idea_list(data: Any) -> list[Any]:
    """Pull the list of ideas out of whatever shape the LLM returned."""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in _IDEA_LIST_KEYS:
        if key in data and isinstance(data[key], list):
            return data[key]
    # Last resort: if the dict has exactly one key that's a list, use that.
    list_values = [v for v in data.values() if isinstance(v, list)]
    if len(list_values) == 1:
        return list_values[0]
    return []


def suggest_data_ideas(session_id: str) -> list[dict[str, Any]]:
    """Bigger-picture project ideas the user could build with this dataset.

    Different scope from suggest_analyses(): instead of 'try this chart',
    this asks 'what could you BUILD with this data?' — ML models,
    dashboards, segmentations, insights.

    The parser is intentionally lenient because Llama 3.3 sometimes returns
    `projects` instead of `ideas`, or uses `name`/`description` instead of
    `title`/`what`. We accept all reasonable variants.
    """
    df = storage.load_dataframe(session_id)
    if df is None:
        raise ValueError(f"Unknown session: {session_id}")

    schema = nlq_engine.build_schema_summary(df)
    client = llm_client.get_client()
    resp = client.chat(
        messages=[
            {"role": "system", "content": prompts.DATA_IDEAS_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Schema:\n```json\n{json.dumps(schema, indent=2)}\n```",
            },
        ],
        max_tokens=1500,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content or "{}"

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        print(f"[data_ideas] JSON parse failed. Raw response head: {content[:300]!r}")
        return []

    raw_ideas = _extract_idea_list(data)
    if not raw_ideas:
        print(f"[data_ideas] No list found in response. Keys: {list(data) if isinstance(data, dict) else 'not a dict'}")
        return []

    out: list[dict[str, Any]] = []
    for raw in raw_ideas[:MAX_DATA_IDEAS]:
        if not isinstance(raw, dict):
            continue
        title = _pick(raw, _IDEA_TITLE_KEYS)
        if not title:
            continue
        what = _pick(raw, _IDEA_WHAT_KEYS) or ""
        how = _pick(raw, _IDEA_HOW_KEYS) or []
        if isinstance(how, str):
            how = [how]
        elif not isinstance(how, list):
            how = [str(how)]

        difficulty = str(_pick(raw, _IDEA_DIFFICULTY_KEYS) or "medium").lower()
        if difficulty not in ALLOWED_DIFFICULTY:
            difficulty = "medium"
        category = str(_pick(raw, _IDEA_CATEGORY_KEYS) or "analytics").lower()
        if category not in ALLOWED_CATEGORY:
            category = "analytics"

        out.append(
            {
                "title": str(title)[:120],
                "what": str(what)[:400],
                "how": [str(h)[:200] for h in how[:4]],
                "difficulty": difficulty,
                "category": category,
            }
        )
    if not out:
        print(f"[data_ideas] {len(raw_ideas)} raw items but none had a usable title. First item: {raw_ideas[0] if raw_ideas else None}")
    return out


def suggest_followups(question: str, insight: str, chart_kind: str) -> list[str]:
    """After answering a question, propose 3 clickable follow-up questions."""
    client = llm_client.get_client()
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
