---
description: Ralph Wiggum autonomous loop — fix failing tests one at a time, commit on green, repeat until no progress.
---

# Ralph loop: autonomous test fixer

Run this when you want Claude Code to grind through failing tests without
hand-holding. Each iteration is a small, committable unit of work.

## The loop

1. Run `pytest -q` and capture the output.
2. If all tests pass: print "All green — nothing to do." and STOP.
3. Pick ONE failing test (the first in the failure list).
4. Read the test source, the module it tests, and any error traceback.
5. Make the minimum change that fixes that one test:
   - If the test is wrong, fix the test.
   - If the implementation is wrong, fix the implementation.
   - If both are wrong, write the test for the behavior you actually want, then
     fix the implementation.
6. Re-run `pytest -q`. If the chosen test now passes AND no new tests broke,
   commit with message `ralph: fix <test_name>`.
7. If a new test broke or the chosen test still fails after 3 attempts, STOP
   and report what went wrong — do not push the failure forward.
8. Otherwise, GOTO 1.

## Guardrails

- Never delete a failing test to make it pass.
- Never `pytest.skip` to silence a failure.
- Never disable test discovery (`__init__.py` deletion, `conftest.py` hack).
- Touch the smallest possible scope: one test, one fix, one commit.
- If the fix requires changing > 50 lines or > 3 files, STOP and ask the user.

## Stop conditions

- All tests green.
- Same test failed 3 attempts in a row.
- A previously-green test is now red.
- More than 5 iterations completed (avoid runaway loops in this session).

## Example session

```
$ pytest -q
F.....
tests/test_cleaner.py::test_outlier_flag_added_for_numeric_with_variance FAILED

[loop iteration 1]
- Read test_cleaner.py + cleaner.py
- Diagnosis: IQR multiplier was set to 0.5, classic rule is 1.5
- Fix: cleaner.py:8  OUTLIER_IQR_MULTIPLIER = 1.5
- pytest -q  -> all green
- git commit -m "ralph: fix test_outlier_flag_added_for_numeric_with_variance"

[loop iteration 2]
- pytest -q  -> all green
- STOP: all green, nothing to do
```
