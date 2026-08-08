## 5분 안에 이해하기

**무엇을 만드는가:** Gmail·Tasks·Calendar의 근거를 모아 업무를 분석하고, 필요한 경우 승인 가능한 실행 계획까지 만드는 로컬 업무 Agent다.

**어떻게 안전한가:** LLM은 이해·검색 전략·분석·계획을 담당하지만 Policy·Approval·Claim·Google Write·Verification은 결정적 코드가 담당한다.

**왜 1/3/6 Agent인가:** 멀티에이전트를 많이 쓰는 것이 목표가 아니라, 같은 업무 책임을 1·3·6개 Subgraph로 나눴을 때 실제 품질·비용이 어떻게 달라지는지 실험으로 선택하기 위해서다.

**어떻게 평가하는가:** 안전은 Hard Gate, 업무 성공은 Business Task Success, 원인 분석은 Process, 운영성은 Cost·Latency·Reliability로 분리한다.

```text
사용자 요청 → Agent 판단/조회 → 근거/분석/계획 → Domain·Policy → 승인 → 실행 → 검증
```

## 핵심 제품 방향

- 사용자 로컬 PC에서 실행하는 단일 사용자 Google 업무 Agent
- 공식 환경: Windows 11 x64 · 최신 Chrome·Microsoft Edge
- React + TypeScript + Vite Frontend
- FastAPI Local Agent Service · `127.0.0.1` 동적 포트
- 운영 빌드는 React 정적 UI와 `/api/v1`을 같은 Origin에서 제공
- REST Command·Query + Server-Sent Events 진행 전달
- Launcher가 Local Service 시작·Health Check·브라우저 열기·종료를 조정
- 결정적 LangGraph Supervisor + 1/3/6 전문 Agent Subgraph Profile + 결정적 실행·검증 Engine
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

> **기준일:** 2026-08-08 · **R8.3 Gold·Scoring·Human Readability Patch** · **공식 원본:** Notion · **이 파일:** R8.3 Repository Export Snapshot

| 문서 | 공식 버전 |
|---|---:|
| 00 프로젝트 개요 | v1.4 |
| 01 PRD | v2.6 |
| 01-A 기능 정의 | v2.5 |
| 01-B 정책 정의 | v2.4 |
| 02 UI·UX | v2.3 |
| 03 시스템 아키텍처 | v2.9 |
| 04 Domain·DB | v1.10 |
| Domain DB Schema | v1.3 (`0001` v1.2 + `0002`) |
| 05 Context·Retrieval | v2.3 |
| 06 Agent·Workflow | v5.8 |
| 07 Tool·MCP·Interface | v2.6 |
| 08 Sequence | v2.9 |
| 09 Security·Auth | v2.2 |
| 10 Infrastructure | v2.5 |
| 11 Observability | v2.8 |
| 12 Test | v2.9 |
| 13 Evaluation | v3.0 |
| 14 Operations | v2.3 |
| 15 Agent Capability·Failure·Prompt | v1.4 |
| Domain 상태 전이 계약 | v1.3 |
| 상태 전이 테스트 매트릭스 | v1.3 |

## Agent Graph 결정 원칙

- 최대 6개 전문 Agent Subgraph 구조는 **초기 Baseline**이며 제품 불변조건이 아니다.
- `SINGLE_BASELINE(1 Agent Subgraph)`, `THREE_STAGE(3)`, `SIX_ROLE_BASELINE(6)`을 비교한다. Agent 수와 LLM Call 수는 별도 개념이며 호출·Token·Latency는 결과 지표로 기록한다.
- Agent Subgraph는 호출 단위 Local State만 가지며 Agent별 장기 Memory는 두지 않는다.
- E06-A는 실제 제품 후보의 1/3/6 native 구조·비용을 비교한다.
- E06-B는 `CONTEXT_READY_V1` 이후 B1/B2/B3 post-retrieval 분해 효과만 통제 비교한다.
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

문서 번호가 뒤라고 더 높은 권위를 갖지 않는다. **충돌한 Concern을 소유한 문서가 우선**한다.

```text
제품 목표·범위          → 01 PRD
사용자 기능             → 01-A
안전·금지·승인          → 01-B
시스템 경계             → 03
영속 사실·상태 전이     → 04 + State Contract + SQL Constraint
Retrieval / Workflow / Tool → 05 / 06 / 07
관측·검증·평가          → 11 / 12 / 13
Prompt·Failure 정규화   → 15 (상위 제품 계약을 완화하지 않음)
```

세부 규칙은 `01 PRD §1.1`과 `00-PROJECT-SOURCE-GUIDE.md`를 기준으로 한다.

## 후속 실험·Prompt 산출물 경계

```text
experiments/datasets/google_workspace/
experiments/user_prompts/
prompts/agent/
```

평가 연결 키는 `experiment_id`, `evaluation_item_id`, `case_id`, `fixture_snapshot_id`, `user_prompt_id`, `candidate_config_hash`, `prompt_id`다. Canonical Case에서 Node·Acquisition·Retrieval·Trajectory·E2E Projection을 파생한다. Agent 하나에 Prompt 하나를 고정하지 않고 `agent_role + subgraph_name + node_name + node_state + purpose`로 Prompt를 선택한다.

## Core Runtime 무결성 계약

- 상태 변경 Command는 `command_receipts`에 영속 등록하며 Domain 변경과 같은 Transaction으로 완료한다.
- Google OAuth Credential 원문은 MCP Credential Provider와 OS Keyring 경계를 벗어나지 않는다.
- Google Write는 실행 Claim 후 발급되는 짧은 수명의 1회용 `claim_token`을 MCP가 재검증한다.
- 인증 전 Endpoint는 `/health/live`, `/health/ready`, `/api/v1/session/bootstrap`, 일시적 OAuth Loopback Callback으로 제한한다.
- 평가 연결 단위는 `experiment_id`, `evaluation_item_id`, `case_id`, `user_prompt_id`, `fixture_snapshot_id`, `candidate_config_hash`, `prompt_id`다.
- 현행 DB 기준은 Schema v1.3(`0001_initial.sql` v1.2 baseline + `0002_action_effect_send_delete.sql`), 상태 전이 기준은 v1.3이다.


## 현재 구현 정합성 핵심

- External Google/MCP/LLM I/O 동안 SQLite Write Transaction을 유지하지 않는다.
- Recovery 상태는 Domain Command로만 변경한다.
- SEND·Calendar DELETE·Task 완료·Attendee UPDATE는 승인형 Write다.
- Agent는 invocation-local Subgraph이며 장기 Memory가 없다.
- Canonical Gold는 Profile-neutral semantic milestone + ordered interaction을 사용한다.
- Safety는 Hard Gate이며 Cost·Latency가 실패를 보상하지 않는다.

세부 변경 이력은 Notion `99. 변경 이력 · 아카이브`와 Repository Full Docs의 `99-change-history-archive.md`에서만 관리한다.
