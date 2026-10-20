# Evaluation results

`2026-10-16-full-run.md` (and the `.json` with every reply) is the output of

```bash
uv run python -m eval.run_eval --suite all --repeat 2
```

run on 16 October 2026 with the model named in the report. The report's `code` line says
`2423d7d (with uncommitted changes)`: those changes were committed right after the run as
`c687051 Phase 9: hardening`. Nothing in the report was edited by hand.

The run predates the audit fixes of 17 and 18 October and the forecast change of 17 October
(invoices that need verification are no longer counted). It also had 10 tasks; there are now 12.

The team's baselines, including the model-free baseline that holds for any model and a three-run
baseline for `openai/gpt-oss-20b`, are in [docs/baseline/](../baseline/README.md).

New runs write to `eval/reports/`, which is not committed.
