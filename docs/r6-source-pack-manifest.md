# Google Work Agent · R6 Source Pack Manifest

> **생성일:** 2026-08-07  
> **Source Document:** 25개  
> **동기화:** Notion 공통 계약 및 `05·06·11·12·13` 보강 반영

## 문서 목록

| No. | 파일 | 역할 |
|---:|---|---|
| 1 | `00-CODE-AGENT-START-HERE.md` | Agent 진입·작업 규칙 |
| 2 | `00-google-work-agent-overview.md` | 프로젝트 전체 개요 |
| 3 | `00-PROJECT-SOURCE-GUIDE.md` | 문서 기준점·읽기 안내 |
| 4 | `0001_initial.sql` | 초기 DB Schema |
| 5 | `01-a-functional-definition.md` | 기능 정의 |
| 6 | `01-b-policy-definition.md` | 정책·승인·금지 규칙 |
| 7 | `01-IMPLEMENTATION-AND-EXPERIMENT-CHECKLIST.md` | 구현·실험 실행 체크리스트 |
| 8 | `01-requirements-prd.md` | 요구사항·PRD |
| 9 | `02-ui-ux-design.md` | UI·UX 계약 |
| 10 | `03-system-architecture.md` | 시스템 아키텍처 |
| 11 | `04-domain-database-design.md` | Domain·DB 설계 |
| 12 | `05-context-retrieval.md` | 수집·Retrieval·Query 계약 |
| 13 | `06-agent-workflow.md` | Agent·Workflow·Budget 계약 |
| 14 | `07-tool-mcp-internal-interface.md` | Tool·MCP·내부 Interface |
| 15 | `08-sequence-design.md` | 주요 시퀀스 |
| 16 | `09-security-auth.md` | 보안·인증 |
| 17 | `10-infrastructure-environment.md` | 인프라·환경 |
| 18 | `11-observability-logging-audit.md` | 관측성·로그·감사 |
| 19 | `12-test-design.md` | 테스트·회귀 Gate |
| 20 | `13-evaluation-experiment.md` | 평가·실험 |
| 21 | `14-operations-troubleshooting.md` | 운영·장애 대응 |
| 22 | `15-agent-capability-failure-prompt-contract.md` | Agent Capability·Failure·Prompt 공통 계약 |
| 23 | `state-transition-contract-v1.3.md` | 상태 전이 계약 |
| 24 | `state-transition-test-matrix-v1.3.md` | 상태 전이 테스트 Matrix |
| 25 | `r6-source-pack-manifest.md` | R6 Source 목록·동기화 기록 |

## 변경 요약

- `15-agent-capability-failure-prompt-contract.md` 신규 추가
- `00-CODE-AGENT-START-HERE.md` 신규 생성
- `05-context-retrieval.md` QueryAttempt·저신뢰·Pagination 계약 보강
- `06-agent-workflow.md` Failure·Retry Kind·Route Budget·Prompt 활성화 Gate 보강
- `11-observability-logging-audit.md` Failure·Retry·Query Trace 확장
- `12-test-design.md` 금지 Retry·Node Holdout·Budget Profile 회귀 추가
- `13-evaluation-experiment.md` E02·E03 분해와 Node Dataset Layer 추가
- `r5-sync-manifest.md` 제외, 본 R6 Manifest로 교체

## 무결성

Pack 루트의 `SOURCE-PACK-MANIFEST.json`과 `SHA256SUMS.txt`를 기준으로 검증한다.
