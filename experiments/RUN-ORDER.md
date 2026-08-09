# Experiment Run Order v1.11 — R8.2 Business-ready

1. G00 Dataset·Grader Integrity
2. G01 Safety·Prompt Injection DEV/HOLDOUT gate
3. Changed dataset/prompt Human Sample Review
4. E01 Model·Runtime Screening
5. E02 Prompt·Schema·Repair (including SINGLE/THREE fused prompts)
6. E03 Node capability + LIVE/MUTATED handoff attribution
7. E04 Acquisition·Read Tool Trajectory
8. E05 Retrieval·Evidence·Context Budget
9. E06-A Native 1/3/6 Agent Subgraph architecture ablation
10. E06-B CONTEXT_READY_V1 controlled B1/B2/B3 decomposition (Google Read 0)
11. E07 Routing·Agent Skip
12. E08 Review contribution
13. Freeze integrated finalist (E06-A + E07 + E08 decisions)
14. G02 Fault·Recovery·Write Integrity
15. V01 Holdout·Stress·Paraphrase·Human Review

`experiments/E06/e06-graph-ablation.json` is R7 provenance only and MUST NOT be run.

Prompt activation remains `DRAFT → DEV_VALIDATED → HOLDOUT_VALIDATED → SAFETY_VALIDATED → RUNTIME_ACTIVE`; this pack has not executed a model.
