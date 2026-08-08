# Dataset Rebuild Contract v0.1

## 목적

기존 Canonical 92개를 최종본으로 간주하지 않고, Agent 개별 Capability Coverage를 먼저 고정한 뒤 Fixture와 E2E Case를 다시 구축한다.

## 고정 기준

- Agent: 6개
- 입력 모드: `ORACLE`, `LIVE`, `MUTATED`
- Failure Reason: LLM·Query 관련 58개, 비-LLM Fault 13개
- Schema Failure는 6개 Agent 모두에 적용
- Agent·Failure 적용 조합: 88개
- 각 적용 조합 최소: DEV 3 + HOLDOUT 1
- Failure Coverage 최소 Node Item: DEV 264개 + HOLDOUT 88개 = 352개
- Canonical E2E 목표: Core 60 + Stress 20 + Holdout 12
- Prompt Version은 Dataset이 소유하지 않고 Prompt Slot만 참조
- Holdout은 Scenario Family와 Fixture Relation Family 단위로 DEV와 분리

## 제작 순서

1. Schema·Taxonomy·Coverage Matrix
2. 합성 Fixture World 12~18개
3. Node Capability DEV·HOLDOUT
4. Query·Low-confidence·Retry Micro Dataset
5. Prompt Repair·Revision Dataset
6. Canonical E2E Core·Stress·Holdout
7. Paraphrase Robustness
8. Fault·Safety Gate
9. 전체 Projection과 Grader Reference 검증

## 기존 92개 처리

기존 Case는 **Scenario 후보 풀**로만 사용한다. 새 Schema와 Coverage Matrix를 통과하지 못한 Case는 자동 승격하지 않는다.
