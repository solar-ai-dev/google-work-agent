# E02/E03 Experiment Runner Pack

## Execution order

1. Resolve the API model/runtime winner from E01 into a copy of `candidate-e01-finalist-prompt-baseline.template.json`.
2. Run G00 preflight and confirm dataset/grader/hash integrity.
3. E02-A DEV -> E02-B DEV -> E02-C DEV -> E02-D DEV.
4. Freeze one prompt candidate per slot. Do not open Node HOLDOUT during tuning.
5. Run E02 HOLDOUT gates.
6. Run E03-A ORACLE, E03-B LIVE, E03-C MUTATED, then E03-D attribution.

## Hard rules

- One independent variable per candidate comparison.
- ORACLE/LIVE/MUTATED results never share the same aggregate denominator.
- Safety, Tool, Argument, Retry, Budget and End-state graders are deterministic and authoritative.
- Prompt/Completion raw text is a local experiment artifact only; do not persist it into product Trace/Audit.
- A template with unresolved E01 model bindings is not runnable.
- Node HOLDOUT is inaccessible until the DEV candidate is frozen.
