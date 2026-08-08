# Prompt Bundle Semantic Review v0.9

> Status: INTERNAL REVIEW PASS · Runtime activation not granted

## Scope

- Six Agent base role contracts
- Schema Repair prompts
- Failure-specific Semantic Revision/Recheck prompts
- 65 assembled Prompt slots
- Retry/stop and deterministic-redirection boundaries

## Review result

- **PASS** `request_understanding.base responsibility boundary` — Base role contract declares bounded responsibility/rules.
- **PASS** `acquisition.base responsibility boundary` — Base role contract declares bounded responsibility/rules.
- **PASS** `context_retriever.base responsibility boundary` — Base role contract declares bounded responsibility/rules.
- **PASS** `work_analysis.base responsibility boundary` — Base role contract declares bounded responsibility/rules.
- **PASS** `planning.base responsibility boundary` — Base role contract declares bounded responsibility/rules.
- **PASS** `review.base responsibility boundary` — Base role contract declares bounded responsibility/rules.
- **PASS** `prompts/agent/planning/repair.md schema-only` — Repair explicitly preserves semantics and is single-attempt/schema-only.
- **PASS** `prompts/agent/acquisition/repair.md schema-only` — Repair explicitly preserves semantics and is single-attempt/schema-only.
- **PASS** `prompts/agent/work_analysis/repair.md schema-only` — Repair explicitly preserves semantics and is single-attempt/schema-only.
- **PASS** `prompts/agent/context_retriever/repair.md schema-only` — Repair explicitly preserves semantics and is single-attempt/schema-only.
- **PASS** `prompts/agent/request_understanding/repair.md schema-only` — Repair explicitly preserves semantics and is single-attempt/schema-only.
- **PASS** `prompts/agent/review/repair.md schema-only` — Repair explicitly preserves semantics and is single-attempt/schema-only.
- **PASS** `prompts/agent/request_understanding/revise.md one-failure guard` — Semantic revision/recheck explicitly limits repeated same-failure revision.
- **PASS** `prompts/agent/acquisition/revise_partial.md one-failure guard` — Semantic revision/recheck explicitly limits repeated same-failure revision.
- **PASS** `prompts/agent/context_retriever/revise.md one-failure guard` — Semantic revision/recheck explicitly limits repeated same-failure revision.
- **PASS** `prompts/agent/work_analysis/reassess.md one-failure guard` — Semantic revision/recheck explicitly limits repeated same-failure revision.
- **PASS** `prompts/agent/planning/revise_plan.md one-failure guard` — Semantic revision/recheck explicitly limits repeated same-failure revision.
- **PASS** `prompts/agent/review/recheck.md one-failure guard` — Semantic revision/recheck explicitly limits repeated same-failure revision.
- **PASS** `acquisition QueryAttempt/pagination distinction` — Acquisition revision covers query history, pagination, low confidence, non-LLM faults.
- **PASS** `context supplied-only/untrusted guard` — Context revision cannot fetch/invent and preserves untrusted-source boundary.
- **PASS** `analysis evidence/missing-data guard` — Analysis revision is evidence-only and redirects missing facts.
- **PASS** `planning tool-target-evidence-approval guard` — Planning revision preserves effect/target/evidence/approval and allowed-field scope.
- **PASS** `review no-self-repair/repeat-stop` — Review recheck does not repair and stops repeated failure.
- **PASS** `failure blocks non-empty` — 46 failure-specific blocks are substantive.
- **PASS** `prompt activation remains DRAFT` — 65 slots remain DRAFT pending DEV/HOLDOUT/Safety execution.

## Key decisions preserved

- Prompt assembly remains `Base + Purpose + Failure-specific Block + Output Schema contract`.
- Schema Repair may correct structure only and gets one attempt per Node call.
- Semantic Revision is limited to the supplied failure signature and allowed fields.
- Missing facts redirect to retrieval or user confirmation rather than hallucination.
- Auth/429/5xx/timeout/UNKNOWN_RESULT/verification recovery remains deterministic and has no failure-specific LLM Prompt.
- All Prompt slots remain `DRAFT`; this review validates contract quality, not model performance.
