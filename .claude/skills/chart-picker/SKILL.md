---
name: chart-picker
description: Pick the right chart kind given the shape of the data after data-prep tool calls. Used by the NLQ engine before calling plot().
---

# Chart picker heuristics

After data prep (filter / groupby / sort / top_n), pick a chart kind that matches
the resulting shape.

## Decision table

| x type        | y type   | Chart    | Why                                |
|---------------|----------|----------|------------------------------------|
| datetime      | numeric  | `line`   | Time series read left-to-right     |
| categorical   | numeric  | `bar`    | Compare a metric across groups     |
| numeric       | numeric  | `scatter`| Look for correlation               |
| numeric (one) | —        | `hist`   | Distribution of a single column    |
| categorical (one, ≤8 unique) | — | `pie` | Share of a small set of groups |
| categorical (one, >8)        | — | `bar` of counts | Pies become unreadable |

## Cardinality rules

- **bar with > 30 categories** → switch to `hist` of the counts, or `top_n(20)` first.
- **scatter with > 5000 points** → still scatter, but pass `opacity: 0.3` if supported.
- **pie with > 8 slices** → switch to horizontal `bar` of counts.

## Color guidance

- One series → no `color` argument (default theme color).
- Coloring by a 3rd categorical → `color=<that column>` only when ≤6 categories.
- Never color by an ID column or a high-cardinality categorical.

## Titles

- Sentence case, ≤7 words.
- Include the unit when obvious: *"Revenue by region"* not *"Revenue per region in USD by region"*.
- Skip dates in the title — the axis shows them.

## When in doubt

Prefer `bar`. It's the chart users misread least often.
