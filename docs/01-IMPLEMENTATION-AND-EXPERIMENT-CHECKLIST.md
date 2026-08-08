# Implementation and Experiment Checklist

## 구현 Gate
- [ ] State Transition v1.3 구현
- [ ] SQLite Migration 및 Constraint 테스트
- [ ] Command Receipt 멱등성
- [ ] Approval Snapshot과 Arguments Hash
- [ ] Claim Token 검증
- [ ] Fake Google Gateway
- [ ] Effect별 Write Verification: CREATE·UPDATE GET_COMPARE / DELETE GET_ABSENT / SEND SENT_LOOKUP
- [ ] UNKNOWN_RESULT 비자동 재실행
- [ ] LocalRunCoordinator 동시성 계약
- [ ] SSE 재연결 Projection

- [ ] Agent 정의: Main Graph가 호출하는 독립 LangGraph Subgraph
- [ ] AgentLocalState invocation isolation
- [x] SINGLE=1 / THREE=3 / SIX=6 Agent Subgraph topology test
- [ ] Agent→Agent 직접 호출 0
- [ ] Agent 내부 bounded Schema Repair / Semantic Revision loop
- [ ] Agent invocation count와 LLM call count 분리 Trace
- [ ] Acquisition Subgraph 내부 결정적 Read Node + invocation continuity
- [ ] SINGLE Unified Agent integrated self-review
- [ ] E06-B `CONTEXT_READY_V1` / 동일 `context_snapshot_id` Replay (Google Read 0)
- [ ] E06-B B1/B2/B3 post-retrieval topology test
- [ ] Prompt Runtime Slot Key에서 `failure_reason_code` 제외 + Failure Block assembly metadata 검증
- [x] `prompt_semantic_bundle_version` parity lock
- [ ] Handoff required-field / Evidence ID / constraint preservation grader
- [ ] `evaluation_environment_hash`로 Hardware·Concurrency·Timeout 조건 고정

## Dataset·Grader 준비 Gate
- [ ] BTS split별 numerator/denominator + Holdout 반복 일관성 보고
- [ ] Grader Registry v0.4 + Scoring Contract v1.1 고정
- [ ] Acquisition Gold budget `CONSTRAINT_ENVELOPE` grader 검증
- [ ] CanonicalCaseV5 `run_outcome_expectation` stop boundary 검증
- [ ] Fixture Relation Model
- [ ] Fixture Snapshot 12~18개
- [ ] Core 60 / Holdout 12 / Stress 20 Canonical Gold
- [ ] Canonical User Prompt 92개
- [ ] `scenario_family_id`, `fixture_relation_family`, `split`
- [ ] Node·Acquisition·Retrieval·Trajectory·E2E Projection 생성
- [ ] Required·Forbidden·Hard Negative 중복 0
- [ ] Holdout 누수 0
- [ ] Deterministic Grader Contract
- [ ] CanonicalCaseV5 `expected_interactions` ordered Gold
- [ ] E2EProjectionV3 self-contained Gold
- [ ] E06-A common score에서 SIX exact route 제외
- [ ] Grader Registry v0.4 + Scoring Contract v1.1
- [ ] Hard Gate 비보상성 + Business Task Success 집계
- [ ] Core/Stress/Holdout denominator 분리
- [ ] Prompt model input에 grader/gold/evaluation label 0
- [ ] Human Sample Review
- [ ] Tier A Prompt 5개 Baseline

## P0 핵심 실험
- [ ] E01 Model·Runtime Screening
- [ ] E02 Prompt·Schema·Repair
- [ ] E03 Node 단독·Handoff 오류 전파 + Error Propagation Matrix
- [ ] E04 Source Acquisition·Read Tool Trajectory
- [ ] E05 Retrieval·Evidence·Context Budget
- [x] E06-A Agent Subgraph Native Architecture Ablation
- [x] E06-B Controlled Post-Retrieval Decomposition
- [ ] E07 Routing·Agent Skip
- [ ] E08 Review Agent 기여도 (catch / false-block / over-correction / cost)

## Gate·Finalist
- [ ] G00 Dataset·Grader Integrity
- [ ] G01 Safety·Prompt Injection 100%
- [ ] G02 Fault·Recovery·Write Integrity 100%
- [ ] V01 Holdout·Stress·Robustness·Human Review
- [ ] Product Decision Record

## 비교 Graph
- `SINGLE_BASELINE`
- `THREE_STAGE`
- `SIX_ROLE_BASELINE`

## 권장 Micro Dataset
- [ ] `resource_selected_variants` 8~12
- [ ] `review_challenges` 30~40
- [ ] `structured_output_repair` 20~30
- [ ] `fault_profiles` 15~20
- [ ] `injection_variants` 10~15
- [ ] Finalist Paraphrase 주요 Core 20 × 2

## Write·Recovery 구현 정합성 Gate
- [ ] `0002_action_effect_send_delete.sql` Migration + `foreign_key_check`
- [ ] External Adapter 호출 시 SQLite Write Transaction 미보유
- [ ] 외부 호출 후 `expected_version`·Action·Attempt 상태 재검증
- [ ] `RequireRecovery`·`ResolveRecovery` 외 Run Recovery 직접 상태 변경 0
- [ ] Gmail SEND 승인·Hash·Sent Lookup·UNKNOWN_RESULT No-Resend
- [ ] Task 완료 UPDATE 승인 경로
- [ ] Calendar DELETE / Attendee UPDATE 승인 경로
- [ ] Gmail 원문 삭제·Task 삭제·반복 Event 전체 일괄 수정 Tool 미등록
- [ ] `ClarificationQuestionV1` 후보·차이·선택지·same-thread Resume
- [ ] 전체 Mailbox/무제한 Workspace 조회 BLOCK
- [ ] Calendar `overlap != conflict` 관계 판정 테스트
