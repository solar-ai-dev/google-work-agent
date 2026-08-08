# Runtime Handoff v1.9 — R7

이 Pack은 실제 API 호출을 수행하지 않는다. 실행 환경에서는 다음 순서를 지킨다.

## Pinned R7 contracts
- Dataset: `rebuild-v1.9`
- Prompt Bundle: `0.7.0-r7`
- Tool/Interface: `v2.4`
- Policy: `01-B-v2.3`
- Grader Registry: `v0.2`
- DB Effect contract: `READ | CREATE | UPDATE | SEND | DELETE`

## Preflight
- `experiments/datasets/google_workspace/validation/r7-policy-rebase-validation-v1.9.json` PASS 필수
- Candidate Config hash 재계산 일치
- Holdout selection은 tuning lane에서 차단
- SEND/DELETE verification/recovery policy가 R7 계약과 일치해야 함
- supported high-impact write를 forbidden으로 채점하는 stale Gold가 없어야 함
- API credential은 Keyring 또는 Runner secret boundary에서만 로드하고 raw credential을 result/trace에 기록하지 않음

## 실행
1. Independent R7 Human Sample Review PASS.
2. `G01-A`를 E01 후보 A/B/C 각각 실행. Safety hard gate 실패 시 탈락.
3. 통과 후보만 `E01 Smoke 5`.
4. Smoke 통과 후보만 `E01 Screening 20`.
5. Screening hard gate를 통과한 후보만 후속 E02~E08으로 진행.
6. Finalist는 `G02` 64-item R7 Fault/Write Policy Gate를 통과한 뒤 V01을 연다.

## 결과 저장
설계된 Result Artifact를 experiment/candidate/case/trial 키로 연결한다. `UNKNOWN_RESULT`에서 SEND 재전송·DELETE 재삭제를 결과 복구로 간주하지 않는다.

## 사용자 결정이 필요한 시점
독립 Human Gold 검수와, 실제 결과에서 여러 Candidate가 모든 Hard Gate를 통과한 Pareto trade-off가 생긴 경우에만 사용자 결정을 요청한다.
