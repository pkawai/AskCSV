---
description: Generate pytest cases for the 6 safe tools using a fixture CSV.
argument-hint: <path-to-csv>
---

# Seed tests from a CSV fixture

Given a CSV file path as input, generate a `tests/test_tools_fixtures.py` that
exercises each of the 6 safe tools against that file.

## Steps

1. Read the CSV path from `$1` (the argument). Default to `data/samples/sales.csv` if empty.
2. Load it with `pd.read_csv` and call `src.profiler.profile(df)` to find:
   - The numeric columns (for `correlate`, `groupby_aggregate`, `top_n`, `sort`)
   - The categorical columns (for `filter eq`, `groupby_aggregate` keys)
   - The datetime columns (for `filter between`, `sort`)
3. Generate one parametrized pytest test per tool. Each test should:
   - Use real column names + plausible values from the CSV.
   - Assert the result dict shape (`row_count`, `preview`, etc.).
   - Have a deterministic expected value where possible (e.g. `count` aggregations).
4. Write the file to `tests/test_tools_fixtures.py`.
5. Run `pytest tests/test_tools_fixtures.py -v` and report results.

## What this is for

The 6 safe tools are the security boundary for the NLQ layer. Each new sample
CSV deserves a tailored test pass — but writing them by hand is busywork. This
command turns a CSV into a working test file in under a minute.

## Do not

- Generate tests for tools that don't exist yet.
- Hardcode column names from other CSVs.
- Skip the `correlate` test if there's only one numeric column — generate a
  test that asserts `ToolError` instead.
