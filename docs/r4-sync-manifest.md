# Google Work Agent r4 동기화 Manifest

- 동기화 기준일: 2026-08-06
- 공식 원본: Notion
- Repository Snapshot: `google-work-agent-all-documents-r4.md`
- 상태: `SYNCED`

| 문서 | 버전 | SHA-256 |
|---|---:|---|
| 00 프로젝트 개요 | v1.1 | `038cc511d2861f5f024845e352636b9dc688af27ddae007a973ba179b19a0a20` |
| 01 PRD | v2.3 | `4020ca1980a0855a9d61376a8148067750526ec6729c2fd0c4d39b735b1f19bd` |
| 03 시스템 아키텍처 | v2.5 | `cf3efafef16e553a1b3cbb2416d0a3591b2710100fa5380de42e951d1d036cad` |
| 06 Agent·Workflow | v5.4 | `91ef4559e006a43d232545c40297b2fbea9122215c4b42d3421c7ec97aa685f2` |
| 13 평가·실험 | v2.4 | `16b1ed8f55d828c316e2740c71b2468d3bbc26a2c8d581a02ebe05a405118c40` |
| 통합 r4 Snapshot | r4 | `6b848869d70ac257ac45990324bd2d9c238ee4c52c45577f74e204449c97a935` |

## 동기화된 핵심 결정

- 최대 6개 역할 Node는 제품 불변조건이 아니라 평가 Baseline이다.
- Graph 후보는 `SINGLE_BASELINE`, `THREE_STAGE`, `SIX_ROLE_BASELINE`이다.
- `LocalRunCoordinator`가 HTTP 요청 수명과 LangGraph 실행 수명을 분리한다.
- MCP는 정책 권위가 아니라 Tool·Process 경계이며 Signed Tool Registry가 효과·승인·재시도 정책을 소유한다.
- 초기 Dataset은 Canonical Prompt 92개다.
- 초기 Prompt 작업은 Tier A 5개를 우선한다.
- P0 필수 실험은 모델, Prompt·Schema, Retrieval, Workflow Ablation 네 개다.
