# Evaluation results

`2026-10-16-full-run.md` (and the `.json` with every reply) is the output of

```bash
uv run python -m eval.run_eval --suite all --repeat 2
```

run on 16 October 2026 with the model named in the report. The report's `code` line says
`2423d7d (with uncommitted changes)`: those changes were committed right after the run as
`c687051 Phase 9: hardening`. Nothing in the report was edited by hand.

New runs write to `eval/reports/`, which is not committed.
