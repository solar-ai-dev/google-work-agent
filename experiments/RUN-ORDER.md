# Experiment Run Order v1.14 — R8.4

1. G00 Dataset·Prompt·Grader·Gold·Scoring Integrity
2. Independent Human Sample Review (Gold author와 분리)
3. G01 Safety·Prompt Injection DEV/HOLDOUT gate
4. E01 Model·Runtime Screening
5. E02 Prompt·Schema·Repair
6. E03 Node capability + ORACLE/LIVE/MUTATED attribution
7. E04 Acquisition·Read Tool Trajectory
8. E05 Retrieval·Evidence·Context Budget
9. E06-A Native 1/3/6 Agent Subgraph architecture ablation
10. E06-B CONTEXT_READY_V1 controlled post-retrieval decomposition
11. E07 Routing·Agent Skip
12. E08 Review contribution
13. Freeze integrated finalist
14. G02 Fault·Recovery·Write Integrity + R8.4 Claim V2/Attachment positive & negative hard gates
15. V01 Holdout·Stress·Paraphrase·Human Review

`experiments/E06/e06-graph-ablation.json` is superseded provenance and MUST NOT be run.
Prompt activation remains `DRAFT → DEV_VALIDATED → HOLDOUT_VALIDATED → SAFETY_VALIDATED → RUNTIME_ACTIVE`. No model result is fabricated by this pack.
