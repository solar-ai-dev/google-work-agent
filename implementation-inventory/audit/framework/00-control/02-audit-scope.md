# Audit Scope Contract

## 향후 포함

- 21 Canonical source의 atomic requirement와 negative requirement
- production owner, caller, import/export, registry/composition, runtime reachability
- Domain lifecycle, persistence/UoW/checkpoint/migration, Application orchestration
- Agent semantics와 LangGraph mechanics의 분리
- Ports/adapters/API/frontend/security/operations/evaluation/release/test evidence
- Wave 2 producer-consumer lineage, E2E lineage, test non-vacuity, global uniqueness

## 이번 framework 단계 제외

- requirement extraction과 production/test census
- current implementation evidence와 negative proof 수집
- finding/verdict/PASS/CLEAN 판정
- remediation 또는 source/test/Ledger/Map 수정
- test/static/build 실행
- 실제 `runs/<SHA>/` 결과 생성
