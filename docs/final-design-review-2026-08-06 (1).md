# Google Work Agent 최종 설계 점검

## 판정

- 시스템 아키텍처: **GO — 조건 충족, 코드 구현 시작 가능**
- 실험 설계: **GO — 범위 제한 조건으로 산출물 작성 시작 가능**
- 공개 배포: **NO-GO — 팀 Test User 통합 이후 별도 OAuth 검증 단계**

## 구현 시작 범위

1. Domain 상태 전이와 SQLite Migration
2. Command Receipt와 조건부 Update
3. Fake Google Gateway와 Fixture Loader
4. Answer-only 수직 흐름
5. READ-only 수직 흐름
6. 단일 WRITE 승인·Claim·실행·GET 검증
7. UNKNOWN_RESULT 복구
8. LocalRunCoordinator와 SSE Projection

## 실험 산출물 시작 범위

- Dataset: Core 60 + Holdout 12 + Stress 20 = Canonical Prompt 92개
- Prompt: Tier A 5개 우선
  - request_understanding.classify
  - acquisition.plan_sources
  - context.select_evidence
  - planning.draft_plan
  - review.inspect
- Fixture: 12~18개 Snapshot
- 실험: 모델 Screening, Prompt·Schema, Retrieval Baseline, Workflow Ablation

## 구현 전에 고정할 계약

- Tool Schema와 Signed Tool Registry Version
- Domain 상태 전이 v1.3
- `command_id`, `claim_token`, Approval Hash 계약
- Graph Profile Config Schema
- Evaluation Item ID 생성 규칙
- Fixture Snapshot Hash 방식

## 남은 비차단 사항

- 01-A·01-B·02 등 하위 문서의 본문 버전은 현재 계약과 충돌하지 않지만, 다음 정기 동기화 때 상단 참조 버전을 일괄 정리한다.
- 공개 OAuth 검증과 Limited Use 대응은 P0 팀 테스트 완료 후 별도 Release Gate다.
- Embedding·Vector Index·Reranker는 Baseline Retrieval이 목표를 못 넘을 때만 추가한다.
