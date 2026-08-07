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

## Dataset·Grader 준비 Gate
- [ ] Fixture Relation Model
- [ ] Fixture Snapshot 12~18개
- [ ] Core 60 / Holdout 12 / Stress 20 Canonical Gold
- [ ] Canonical User Prompt 92개
- [ ] `scenario_family_id`, `fixture_relation_family`, `split`
- [ ] Node·Acquisition·Retrieval·Trajectory·E2E Projection 생성
- [ ] Required·Forbidden·Hard Negative 중복 0
- [ ] Holdout 누수 0
- [ ] Deterministic Grader Contract
- [ ] Human Sample Review
- [ ] Tier A Prompt 5개 Baseline

## P0 핵심 실험
- [ ] E01 Model·Runtime Screening
- [ ] E02 Prompt·Schema·Repair
- [ ] E03 Node 단독·Handoff 오류 전파
- [ ] E04 Source Acquisition·Read Tool Trajectory
- [ ] E05 Retrieval·Evidence·Context Budget
- [ ] E06 Workflow Graph Ablation
- [ ] E07 Routing·Agent Skip
- [ ] E08 Review Agent 기여도

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

## R7 구현 정합성 Gate
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
