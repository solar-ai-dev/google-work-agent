# Google Work Agent — Code Agent Start Here

> 구현 Agent용 온보딩 문서다. 충돌 시 25개 Canonical 계약을 따른다.

## 현재 기준

- Workflow v7.14 / Interface v2.19 / Sequence v3.14
- Test v3.31 / Evaluation v3.20 / Operations v2.17 / Prompt Contract v1.20
- Dataset `rebuild-v1.17-r8.6-phase7.5-contract-correction`
- Projection `projection-v1.1-r8.6-phase7.5`
- Prompt `0.9.0-r8.6-phase6`
- 상태 `CONTRACT_CORRECTED_READY_FOR_REAL_MODEL_PILOT_NOT_ACTIVE`

## 구현 전 핵심

1. Tool Route LLM은 semantic candidate만 만든다. Policy precondition은 deterministic resolver가 만든다.
2. Work Analysis 호출은 ACTION 여부가 아니라 `effective_analysis_required`로 결정한다.
3. `tasklist_id/calendar_id`를 LLM이 추측하지 않는다. deterministic binding 후 Planning에 전달한다.
4. Write는 Approval → Claim → MCP Write → Verification이며 UNKNOWN_RESULT blind resend 금지다.
5. 실제 Local model pilot 전 Runner가 PrePolicy Gold/Final Route Gold를 단계별로 채점하는지 확인한다.
