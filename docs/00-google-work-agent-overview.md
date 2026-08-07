## 핵심 제품 방향

- 사용자 로컬 PC에서 실행하는 단일 사용자 Google 업무 Agent
- 공식 환경: Windows 11 x64 · 최신 Chrome·Microsoft Edge
- React + TypeScript + Vite Frontend
- FastAPI Local Agent Service · `127.0.0.1` 동적 포트
- 운영 빌드는 React 정적 UI와 `/api/v1`을 같은 Origin에서 제공
- REST Command·Query + Server-Sent Events 진행 전달
- Launcher가 Local Service 시작·Health Check·브라우저 열기·종료를 조정
- 결정적 LangGraph Supervisor + 최대 6개 전문 LLM 역할 Node Baseline + 결정적 실행·검증 Engine
- Google Work MCP Server (`stdio`)
- SQLite Domain Store + LangGraph Checkpointer + OS Keyring
- 원격 Backend·SaaS·외부 공개 API 없음
- 사용자는 OAuth Client 파일 없이 `Google로 로그인`과 Scope 동의만 수행
- 모든 Google Write는 사용자 승인 후 실행하고 Effect별 결정적 검증을 수행한다. CREATE·UPDATE는 GET 비교, DELETE는 대상 부재/삭제 상태, SEND는 Sent 결과 조회를 사용한다.
- P0에 API_LLM·LOCAL_GPU·AUTO 모두 포함
- Local 제품 Runtime은 Ollama로 고정
- `API_ONLY`·`LOCAL_CAPABLE` 배포 프로필 분리
- CPU-only 또는 GPU 기준 미달은 API_LLM 고정
- GPU 없는 팀원은 API_ONLY·Mock·Fixture로 공통 기능 개발
- sLLM 실험·후보 모델은 제품 배포와 분리
- API 실험은 요청·Token·비용·Quota·동시성 제한 필수
- 모델·Graph·Retrieval 세부값은 실험 후 제품에 고정

## 문서 원본·동기화 규칙

- **공식 원본:** Notion 설계 문서
- **Repository Markdown:** 구현·리뷰용 Export Snapshot
- 설계 변경은 상위 권위 문서부터 Notion에 반영하고 Version을 증가시킨 뒤 Repository로 Export한다.
- Notion Version과 Repository Snapshot Version이 다르면 해당 문서를 구현 기준으로 사용하지 않는다.
- Repository가 더 최신인 경우 자동 승격하지 않고 변경점을 검토한 뒤 Notion에 반영한다.

| 상태 | 의미 |
|---|---|
| `SYNCED` | Notion과 Repository Version·내용이 일치 |
| `NOTION_NEWER` | Notion 변경 후 Export 대기 |
| `REPOSITORY_NEWER` | Repository 변경 검토와 Notion 승격 대기 |

## 문서 버전 Manifest

> **기준일:** 2026-08-07 · **공식 원본:** Notion · **이 파일:** Repository Export Snapshot

| 문서 | 공식 버전 |
|---|---:|
| 00 프로젝트 개요 | v1.2 |
| 01 PRD | v2.4 |
| 01-A 기능 정의 | v2.3 |
| 01-B 정책 정의 | v2.3 |
| 02 UI·UX | v2.3 |
| 03 시스템 아키텍처 | v2.6 |
| 04 Domain·DB | v1.9 |
| Domain DB Schema | v1.3 (`0001` v1.2 + `0002`) |
| 05 Context·Retrieval | v2.1 |
| 06 Agent·Workflow | v5.5 |
| 07 Tool·MCP·Interface | v2.4 |
| 08 Sequence | v2.6 |
| 09 Security·Auth | v2.2 |
| 10 Infrastructure | v2.4 |
| 11 Observability | v2.4 |
| 12 Test | v2.5 |
| 13 Evaluation | v2.6 |
| 14 Operations | v2.2 |
| 15 Agent Capability·Failure·Prompt | v1.0 |
| Domain 상태 전이 계약 | v1.3 |
| 상태 전이 테스트 매트릭스 | v1.3 |

## Agent Graph 결정 원칙

- 최대 6개 전문 역할 구조는 **초기 Baseline**이며 제품 불변조건이 아니다.
- `SINGLE_BASELINE`, `THREE_STAGE`, `SIX_ROLE_BASELINE`을 같은 Dataset·Model·Policy·Retrieval 조건에서 비교한다.
- Release Graph는 E2E 품질, Tool·Argument 정확도, 비용, LLM 호출 수와 p95 Latency를 기준으로 실험 후 고정한다.
- 안전·승인·실행·검증 Engine은 Graph 후보와 무관하게 동일한 결정적 코드와 Domain 계약을 사용한다.

## 핵심 프로세스

```text
실행 관리자(Launcher)
→ FastAPI 로컬 에이전트 서비스
→ React 화면 · REST · SSE
→ 애플리케이션 · LangGraph · 도메인
→ Versioned Prompt Registry · Node별 PromptRef
→ MCP 표준 입출력 · Google 업무 API
→ SQLite · 키 저장소 · API LLM 또는 Ollama
```

## Phase 1. 기획 및 전체 구조
<page url="https://app.notion.com/p/3b2745b25d0b8151af20efa7b4b89715">01. 요구사항 정의서 · PRD</page>
<page url="https://app.notion.com/p/3b2745b25d0b8123bacbe603b62e4eb9">01-A. 기능 정의서</page>
<page url="https://app.notion.com/p/3b2745b25d0b817f9517cd993812b1ed">01-B. 정책 정의서</page>
<page url="https://app.notion.com/p/3b2745b25d0b81b1acdcd16f6ac71dca">02. UI · UX 설계서</page>
<page url="https://app.notion.com/p/3b2745b25d0b81c483f6e8d8ac947a02">03. 시스템 아키텍처 설계서</page>

## Phase 2. 도메인 및 데이터
<page url="https://app.notion.com/p/3b2745b25d0b81ec90d9ee2949597df0">04. 도메인 · 데이터베이스 설계서</page>
<page url="https://app.notion.com/p/3b2745b25d0b81089eb9ffb77b4ff986">05. Context · Retrieval 설계서</page>

## Phase 3. 핵심 Agent 및 인터페이스
<page url="https://app.notion.com/p/3b2745b25d0b81f3ab3dff471cefbc81">06. Agent · Workflow 설계서</page>
<page url="https://app.notion.com/p/3b2745b25d0b81debb0cff12e408c5e8">07. Tool · MCP · 내부 인터페이스 명세서</page>
<page url="https://app.notion.com/p/3b2745b25d0b816f8426e43f8f0a5df6">08. 시퀀스 설계서</page>

## Phase 4. 보안 · 환경 · 관측성
<page url="https://app.notion.com/p/3b2745b25d0b81a4bcafca9843d77cae">09. 보안 · Auth 설계서</page>
<page url="https://app.notion.com/p/3b2745b25d0b81a6b2aefaa069761a1b">10. 인프라 · 환경 설정 설계서</page>
<page url="https://app.notion.com/p/3b2745b25d0b810cac60df3cc143cf0e">11. 관측성 · 로그 · 감사 설계서</page>

## Phase 5. 검증 및 운영
<page url="https://app.notion.com/p/3b2745b25d0b8179b36bca05aa3f86c2">12. 테스트 설계서</page>
<page url="https://app.notion.com/p/3b2745b25d0b811d88e7f51cb1f4ff45">13. 평가 · 실험 설계서</page>
<page url="https://app.notion.com/p/3b2745b25d0b813f812bd16e5d8ca8fe">14. 예외 처리 · 운영 · 트러블슈팅 가이드</page>


---

## 문서 권위 규칙

```text
00 → 01 → 01-A → 01-B → 02 → 03 → 04 → 05 → 06 → 07 → 08 → 09 → 10 → 11 → 12 → 13 → 14
```

- 하위 문서는 상위 문서를 변경하지 않고 구현값·절차·검증 방법만 구체화한다.
- `01-A`와 `01-B`가 충돌하면 금지·승인·개인정보 정책을 가진 `01-B`가 우선한다.
- 상위 결정을 바꿀 때는 상위 문서를 먼저 수정하고 하위 문서를 순차 갱신한다.

## 후속 실험·Prompt 산출물 경계

```text
experiments/datasets/google_workspace/
experiments/user_prompts/
prompts/agent/
```

평가 연결 키는 `experiment_id`, `evaluation_item_id`, `case_id`, `fixture_snapshot_id`, `user_prompt_id`, `candidate_config_hash`, `prompt_id`다. Canonical Case에서 Node·Acquisition·Retrieval·Trajectory·E2E Projection을 파생한다. Agent 하나에 Prompt 하나를 고정하지 않고 `agent_role + subgraph_name + node_name + node_state + purpose`로 Prompt를 선택한다.

## r3 구현 기준 계약

- 상태 변경 Command는 `command_receipts`에 영속 등록하며 Domain 변경과 같은 Transaction으로 완료한다.
- Google OAuth Credential 원문은 MCP Credential Provider와 OS Keyring 경계를 벗어나지 않는다.
- Google Write는 실행 Claim 후 발급되는 짧은 수명의 1회용 `claim_token`을 MCP가 재검증한다.
- 인증 전 Endpoint는 `/health/live`, `/health/ready`, `/api/v1/session/bootstrap`, 일시적 OAuth Loopback Callback으로 제한한다.
- 평가 연결 단위는 `experiment_id`, `evaluation_item_id`, `case_id`, `user_prompt_id`, `fixture_snapshot_id`, `candidate_config_hash`, `prompt_id`다.
- 현행 DB 기준은 Schema v1.3(`0001_initial.sql` v1.2 baseline + `0002_action_effect_send_delete.sql`), 상태 전이 기준은 v1.3이다.


## 2026-08-07 구현 정합성 요약

- External I/O와 SQLite Write Transaction을 분리한다.
- Recovery는 `RequireRecovery`·`ResolveRecovery` Domain Command를 거친다.
- `gmail_send`, Task 완료, Calendar Event 삭제, Calendar 참석자 변경은 승인형 Write다.
- Gmail 원문 삭제, Task 삭제, 반복 Event 전체 일괄 수정은 금지다.
- 모호성은 요청/검색/분석 중 실제 발견된 단계에서 Clarification으로 보낸다. 후보가 있으면 후보·차이·선택지를 표시하고 같은 Run·Thread를 Resume한다.
- 전체 Mailbox·무제한 Workspace 조회 요청은 BLOCK한다.
