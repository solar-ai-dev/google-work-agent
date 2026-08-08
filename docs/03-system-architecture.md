# 03. Google Work Agent 시스템 아키텍처 설계서

> **문서 기준:** `01 PRD §1.1`의 Concern Owner 규칙을 따른다. 이 문서는 시스템 경계와 의존성 방향을 소유하며 Policy·Domain·Tool의 전문 계약을 완화하지 않는다.

## 0. 문서 정보

| 항목 | 내용 |
|---|---|
| 문서명 | 03. Google Work Agent 시스템 아키텍처 설계서 |
| 상태 | Draft v2.9 |
| 기준일 | 2026-08-08 |
| 대상 릴리스 | P0 MVP |
| 공식 환경 | Windows 11 x64 · 최신 Chrome·Microsoft Edge |
| 제품 형태 | 단일 사용자용 로컬 Web UI + Python Agent 애플리케이션 |
| 핵심 Runtime | React · TypeScript · Vite · FastAPI · LangGraph · Google Work MCP Server `stdio` · SQLite · OS Keyring |

## 0-A. 한눈에 보는 구조

```text
React UI → FastAPI Local Service → Deterministic Supervisor → Agent Subgraph
                                            ↓
                                   Domain / Policy / Approval
                                            ↓
                                  MCP → Google Workspace
                                            ↓
                                      Verification
```

- **판단은 Agent**, **허용·실행 사실은 Domain**, **외부 효과는 MCP/Google**, **재개 위치는 Checkpoint**가 소유한다.
- 원격 제품 Backend 없이 사용자 PC에서 동작한다.


## 1. 문서 목적

이 문서는 Google Work Agent의 전체 실행 구조, 프로세스 경계, 논리 컴포넌트, 책임 분리, 통신 방식, 상태 소유권, 안전 경계와 배포 프로필을 정의한다.

이 문서가 답해야 하는 핵심 질문은 다음과 같다.

- 제품은 어떤 프로세스로 실행되는가?
- React Frontend, FastAPI Local Agent Service, LangGraph, Domain·Policy, MCP Server의 책임은 무엇인가?
- LLM이 판단하는 영역과 일반 코드가 결정하는 영역은 어디서 나뉘는가?
- 승인·실행·검증 상태의 기준점은 어디인가?
- 브라우저 새로고침, REST Retry, SSE 재연결, 앱 재실행, MCP 종료, OAuth 만료 후 어떻게 안전하게 복구하는가?
- `API_ONLY`와 `LOCAL_CAPABLE`은 어떤 공통 Core와 다른 Runtime을 가지는가?

### 1.1 이 문서의 범위

- System Context와 신뢰 경계
- Runtime·Container 구조
- React Frontend와 FastAPI Local Agent Service의 논리 구조
- LangGraph 기반 Agent 실행 모델
- Google Work MCP Server 연동 경계
- SQLite·Checkpointer·OS Keyring의 상태 소유권
- 승인·Idempotency·실행·검증·복구 구조
- API LLM·Ollama Runtime Router
- 시작·종료·장애 복구 개요
- 배포 프로필과 테스트 경계

### 1.2 이 문서의 비범위

다음 세부사항은 후속 문서에서 정의한다.

- Table, Column, Index, Migration 상세 → `04. 도메인·데이터베이스 설계서`
- 검색 Query, Context Budget, Chunking, Reranking 상세 → `05. Context·Retrieval 설계서`
- LangGraph State, Node, Edge, Interrupt 상세 → `06. Agent·Workflow 설계서`
- MCP Tool별 Pydantic Schema와 오류 코드 상세 → `07. Tool·MCP·내부 인터페이스 명세서`
- 정상·실패·Recovery 단계별 호출 순서 → `08. 시퀀스 설계서`
- OAuth, Scope, Token, Keyring 상세 → `09. 보안·Auth 설계서`
- 설치·패키징·Ollama·환경 변수 상세 → `10. 인프라·환경 설정 설계서`
- Trace·Log·Audit Event Schema 상세 → `11. 관측성·로그·감사 설계서`

## 2. 아키텍처 요약

Google Work Agent는 **로컬 Frontend와 Python Modular Monolith를 분리한 단일 사용자 애플리케이션**으로 구성한다.

> **React Frontend가 사용자 화면을 담당하고, FastAPI Local Agent Service가 Application·LangGraph·Domain·Persistence의 단일 진입 경계를 제공한다. Google Work MCP Server는 Google API 작업을 수행한다. 모든 제품 프로세스는 사용자 PC에서 실행된다.**

주요 실행 단위는 다음 네 가지다.

1. **Launcher** — Local Service 시작, 동적 포트 선택, Health Check, 브라우저 열기와 종료 조정
2. **React Frontend** — React + TypeScript + Vite 기반 UI; 운영에서는 FastAPI가 정적 산출물을 제공
3. **FastAPI Local Agent Service** — REST Command·Query, SSE Event, Application, LangGraph, Policy, LLM Router, Persistence
4. **Google Work MCP Server** — Gmail·Tasks·Calendar Tool과 Google OAuth·API Adapter

검증된 GPU 환경에서는 **Ollama Runtime**이 선택적으로 추가된다. 별도 원격 Backend, SaaS API, Queue, 원격 MCP Server는 두지 않는다.

### 2.1 선택한 아키텍처 스타일

- 제품 외형: Launcher가 여는 localhost React Web UI
- Frontend: React + TypeScript + Vite
- Backend 경계: FastAPI Local Agent Service
- 운영 UI 제공: FastAPI가 React Static Build와 `/api/v1`을 같은 Origin에서 제공
- 내부 구조: Python Layered Modular Monolith
- 의존성 방향: React → Local API → Application → Domain
- Agent 구조: 결정적 Supervisor + 평가 가능한 1/3/6 Agent Subgraph Profile + 결정적 실행·검증 Engine
- 진행 전달: REST Command·Query + SSE Event Stream
- 외부 Tool 연동: MCP `stdio`
- 상태 관리: SQLite Domain Store + LangGraph Checkpointer
- Secret 관리: OS Keyring
- 분산 트랜잭션 방식: Action 단위 상태 전이를 사용하는 Saga형 실행

## 3. 아키텍처 목표와 우선순위

| 우선순위 | 품질 속성 | 아키텍처 의미 |
|---:|---|---|
| 1 | 안전성 | 승인 없는 쓰기, 금지 Tool, 승인 인자 변경을 결정적으로 차단한다. |
| 2 | 복구성 | 브라우저 새로고침·REST Retry·SSE 재연결·앱 종료·OAuth 만료·Tool 응답 유실 후 중복 실행 없이 재개한다. |
| 3 | 개인정보 보호 | Secret과 불필요한 Gmail 원문을 저장·로그·전송하지 않는다. |
| 4 | 예측 가능성 | LLM의 자유 실행이 아니라 정의된 Workflow와 상태 전이를 사용한다. |
| 5 | 단순성 | 단일 사용자 로컬 제품에 불필요한 원격 서버·Queue·Kubernetes를 도입하지 않는다. |
| 6 | 테스트 가능성 | Google Client, LLM Provider, MCP Client, Clock, Keyring을 교체 가능한 Port로 둔다. |
| 7 | 성능 | 단계별 진행 상태를 제공하고 불필요한 Source·LLM 호출을 줄인다. |
| 8 | 확장성 | 수평 확장보다 기능 모듈과 Adapter 교체 가능성을 우선한다. |

## 4. 핵심 아키텍처 결정

| ID | 결정 | 이유 |
|---|---|---|
| ARC-001 | 로컬 단일 사용자 앱 | 제품 목표와 개인정보·운영 범위에 맞춘다. |
| ARC-002 | React + TypeScript + Vite Frontend | 복잡한 3열 UI, Inline Action Card, 편집·반응형·Client State를 명시적으로 구현한다. |
| ARC-003 | FastAPI Local Agent Boundary | React와 Python Core 사이를 Versioned REST·SSE 계약으로 분리하되 외부 공개 서버는 두지 않는다. |
| ARC-011 | Production same-origin | FastAPI가 React 정적 산출물과 `/api/v1`을 같은 `127.0.0.1` Origin에서 제공한다. |
| ARC-012 | REST Command + SSE Event | 상태 변경은 REST Command, 진행 전달은 재연결 가능한 SSE를 사용한다. |
| ARC-013 | Launcher Process Supervision | Launcher가 Port·Service·Browser·MCP 수명주기를 조정한다. |
| ARC-014 | Versioned Prompt Registry | Supervisor는 Node를 Routing하고 선택된 Agent·Application Node가 Node·상태·목적별 PromptRef를 확정한다. |
| ARC-004 | 결정적 LangGraph Supervisor 기반 평가 가능 Workflow | `SINGLE_BASELINE`, `THREE_STAGE`, `SIX_ROLE_BASELINE`을 같은 안전·Tool·Policy 계약으로 비교한다. Agent는 invocation 범위 Local State를 가진 Subgraph이며, 필요한 Google Read는 해당 Agent Subgraph 안의 결정적 Application Node가 수행할 수 있다. 승인·실행·검증·복구는 Graph 후보와 독립된 결정적 Engine이 통제한다. |
| ARC-005 | Agent와 Domain·Policy 분리 | LLM은 제안하고 일반 코드는 허용·차단·검증을 결정한다. |
| ARC-006 | Google 연동은 MCP `stdio` | Google Tool 계약과 실행 경계를 표준화하고 로컬에 유지한다. |
| ARC-007 | Checkpoint와 Domain Store 분리 | Graph 재개 상태와 제품의 승인·실행 사실을 별도로 보존한다. |
| ARC-008 | 모든 쓰기 후 Effect별 결정적 검증 | Tool 응답만 신뢰하지 않는다. CREATE·UPDATE는 GET 비교, DELETE는 대상 부재/삭제 상태, SEND는 Sent 결과 조회를 사용한다. |
| ARC-009 | Local Runtime은 Ollama로 고정 | 제품 Runtime과 실험 Runtime의 범위를 제한한다. |
| ARC-010 | `API_ONLY`·`LOCAL_CAPABLE` 분리 | GPU가 없는 환경에 Ollama·모델 의존성을 강제하지 않는다. |


### 4.1 Local Run Coordinator

FastAPI HTTP 요청 수명과 LangGraph Run 실행 수명을 분리하기 위해 Application 계층에 `LocalRunCoordinator`를 둔다.

```text
FastAPI Route
→ Run Command와 Command Receipt Commit
→ LocalRunCoordinator.enqueue(run_id)
→ Worker Slot 획득
→ LangGraph invoke 또는 resume
→ Domain·Checkpoint 저장
→ Projection Event 발행
```

P0 실행 계약:

- Conversation당 Open Run 최대 1개
- 전체 LLM Run 동시성 1
- Google Read 동시성 최대 3
- Google Write 동시성 1
- Run Queue는 메모리 기반이며 실행 사실의 기준점은 `runs`와 Checkpoint다.
- Service 재시작 시 Open Run과 Checkpoint를 조회해 명시적 Resume 또는 `RECOVERY_REQUIRED`로 전환한다.
- SSE 연결 유무는 Run 실행·성공 여부를 결정하지 않는다.

### 4.2 MCP Trust Boundary

- MCP는 보안 정책의 원본이 아니라 Tool·Process·Transport 계약 경계다.
- MCP Server Binary와 Tool Manifest는 제품 공급망 Artifact다.
- Tool Annotation을 Policy·Effect·Retry 판단의 기준으로 사용하지 않는다.
- Effect Type, Scope, Retryability, Verification, Recovery는 Signed Tool Registry가 소유한다.
- MCP Server는 Claim Token·Tool Name·Arguments Hash·TTL·Nonce를 재검증한다.

### 4.3 SQLite·Checkpointer 운영 계약

- Domain Migration은 LangGraph 관리 Table을 생성·변경하지 않는다.
- LangGraph Checkpointer Package Version과 Schema Compatibility를 Release Manifest에 Pin한다.
- Backup은 SQLite Online Backup API 또는 정상 종료 상태의 일관된 복사를 사용한다.
- Domain Transaction과 Checkpoint Transaction은 하나의 원자 Transaction으로 묶지 않는다.
- Domain과 Checkpoint가 충돌하면 Domain Store를 실행 사실의 기준점으로 사용하고 `RECOVERY_REQUIRED`로 전환한다.
- WAL 크기와 Checkpoint 주기를 운영 설정으로 관리한다.

## 5. 시스템 구성 관계

```mermaid
flowchart LR
    U["개인 사용자"] -->|"Chrome·Edge에서 요청·승인"| FE["React 프런트엔드<br>사용자 로컬 PC"]
    FE -->|"동일 출처 REST + SSE"| API["FastAPI 로컬 에이전트 서비스"]
    API -->|"MCP stdio"| MCP["Google 업무 MCP 서버"]
    MCP -->|"Gmail·Tasks·Calendar API"| GOOGLE["Google 업무 API"]
    API -->|"선택된 최소 문맥"| EXT["API LLM 제공자"]
    API -->|"로컬 추론"| OLLAMA["Ollama<br>선택적 GPU 실행 환경"]
    API -->|"도메인·체크포인트"| DB["SQLite"]
    API -->|"LLM API Key 상태·사용"| KEYRING["운영체제 키 저장소"]
    MCP -->|"Google Refresh Token 상태·사용"| KEYRING
```

### 5.1 외부 Actor와 시스템

| 대상 | 관계 | 신뢰 수준 |
|---|---|---|
| 사용자 | 자연어 요청, 확인 질문 응답, 쓰기 승인·수정·거절 | 인증된 로컬 사용자이나 입력은 Schema 검증 필요 |
| Google APIs | Gmail·Tasks·Calendar 조회·허용된 쓰기·결과 재조회 | 외부 시스템 응답으로 정상화·검증 필요 |
| API LLM Provider | API_LLM 추론 | 외부 처리자, 최소 Context만 전송 |
| Ollama | LOCAL_GPU 추론 | 로컬 프로세스이나 출력은 비신뢰 LLM 결과 |
| OS Keyring | Google Refresh Token은 MCP Credential Provider, LLM API Key는 LLM Adapter가 분리된 Entry로 사용 | Secret 저장의 기준점 |

## 6. 전체 실행 환경·프로세스 구조

```mermaid
flowchart TB
    subgraph PC["사용자 Windows PC"]
        L["실행 관리자<br>Launcher"] --> API
        L --> B["Chrome·Edge"]
        B -->|"127.0.0.1 same-origin"| API

        subgraph API["FastAPI 로컬 에이전트 서비스"]
            WEB["React 정적 파일 제공"]
            HTTP["REST 조회·명령"]
            SSE["SSE 진행 이벤트 발행"]
            APS["애플리케이션 서비스"]
            AG["LangGraph 에이전트 실행 환경"]
            DOM["도메인·정책·검증기"]
            LLM["LLM 실행 모드 라우터"]
            MC["MCP 클라이언트"]
            PER["저장소·체크포인터·감사"]
            RUNMEM["실행 검색 캐시"]

            HTTP --> APS
            SSE --> APS
            APS --> AG
            APS --> DOM
            AG --> DOM
            AG --> LLM
                        APS --> MC
            APS --> PER
            AG --> PER
        end

        subgraph FE["Chrome·Edge의 React 프런트엔드"]
            UI["화면 구성요소·경로"]
            CS["클라이언트 상태"]
            CACHE["사이드바 세션 캐시"]
            CLIENT["형식화 API·SSE 클라이언트"]
            UI --> CS
            UI --> CACHE
            UI --> CLIENT
        end

        B --> FE
        CLIENT --> HTTP
        SSE --> CLIENT
        MC -->|"JSON-RPC over stdio"| MCP["Google 업무 MCP 서버"]
        MCP --> KR2["운영체제 키 저장소<br>Google Token Entry"]
        PER --> DB["SQLite"]
        PER --> KR["운영체제 키 저장소"]
        LLM --> O["선택적 Ollama"]
    end

    MCP -->|"HTTPS"| GOOGLE["Gmail·할 일·캘린더"]
    LLM -->|"HTTPS"| EXT["API LLM 제공자"]
```

### 6.1 프로세스 경계

| 실행 단위 | 형태 | 주요 장애 영향 |
|---|---|---|
| Launcher | 제품 시작·종료 Supervisor | Local Agent Service 시작 실패, Version 불일치와 종료 상태를 사용자에게 표시한다. |
| Chrome·Edge + React Frontend | 로컬 UI Client | 탭이 닫히거나 새로고침되어도 영구 Run 상태는 SQLite에 남는다. |
| FastAPI Local Agent Service | 제품의 중심 Python 프로세스 | REST·SSE·Application·Agent가 중단되며 Checkpoint와 Domain 상태로 복구한다. |
| Google Work MCP Server | Local Agent Service가 관리하는 단일 자식 프로세스 | Google 읽기·쓰기 Tool이 중단된다. 쓰기 중 장애는 결과 재조회 후 상태를 확정한다. |
| Ollama | 선택적 로컬 외부 프로세스 | LOCAL_GPU가 실패하며 명시 모드 또는 AUTO fallback 정책으로 분기한다. |
| Google Workspace APIs | 외부 시스템 | 일시 오류·인증 만료·Quota 오류를 공통 오류로 변환한다. |
| API LLM Provider | 선택적 외부 추론 시스템 | API_LLM 실패 또는 AUTO fallback 실패로 처리한다. |

## 7. 프런트엔드와 로컬 에이전트 서비스 논리 구조

```mermaid
flowchart LR
    FE["React 화면 계층"] --> API["형식화 로컬 API 클라이언트"]
    API --> ROUTE["FastAPI 경로 어댑터"]
    ROUTE --> APP["애플리케이션"]
    APP --> AG["에이전트 작업 흐름"]
    APP --> DOM["도메인·안전 핵심"]
    AG --> DOM
    APP --> PORT
    DOM --> PORT
    PORT --> ADP["연동 어댑터"]
    ADP --> EXT["MCP·LLM·SQLite·키 저장소·운영체제"]
```

### 7.1 React Presentation Layer

책임:

- 시작 검사, 온보딩, 메인 3열 레이아웃, 설정·진단 렌더링
- Gmail·Task·Event 목록과 Page Token을 UI Session Cache에서 관리
- 사용자 메시지, 확인 질문, 승인, 수정, 거절, 취소 Command 수집
- REST Response, Run Snapshot과 SSE Event를 View State로 반영
- Event Cursor·Aggregate Version으로 중복·오래된 화면 Event 제거

제한:

- Google API·MCP·SQLite·OS Keyring 직접 호출 금지
- 승인 Button에서 Write Tool 직접 실행 금지
- Browser Storage와 Client State를 승인·실행 사실의 기준점으로 사용 금지
- API Error·SSE Disconnect만으로 Domain 실패를 추정 금지

### 7.2 FastAPI Route·Event Adapter

책임:

- Host·Origin·Local Session·Content-Type 검증
- Versioned Pydantic Request·Response·Error Schema
- REST Query와 Command를 Application Service에 전달
- SSE 구독, Cursor 재개, 사용자 표시 Event 직렬화
- Request ID·Command ID·Trace Context 생성과 전달

제한:

- Domain 상태 직접 UPDATE 금지
- Policy 결정 복제 금지
- LangGraph Checkpoint Table 직접 조작 금지
- 전체 Gmail 원문과 Secret을 Event로 전달 금지

### 7.3 Application Layer

대표 Service:

- `StartupCoordinator`
- `RunCoordinator`
- `ConversationService`
- `ApprovalService`
- `ExecutionService`
- `VerificationService`
- `RecoveryService`
- `EventProjectionService`

책임:

- API Command를 영구 Domain 상태 전이로 변환
- LangGraph invoke·resume와 사용자 Interrupt 조정
- 승인 후 실행 전 검증 절차 조정
- Action DAG 실행 순서와 부분 성공 조정
- Domain Event를 사용자 표시 Event로 투영

### 7.4 Agent Workflow Layer

- 자연어 목표 구조화, Retrieval Plan, 충분성 평가, 질문, Evidence 기반 Plan 초안을 담당한다.
- 사용자 승인 생략, 금지 Tool 허용, 승인 Arguments 변경, 검증 성공 임의 확정은 금지한다.

### 7.5 Domain·Safety Core

- Tool Allowlist, 상태 전이, Schema·Policy, Evidence, 중복·충돌, Approval Hash, Idempotency, Verification 판정을 소유한다.
- React, FastAPI, LangGraph Runtime, Google SDK에 직접 의존하지 않는다.

### 7.6 Integration Layer

- MCP Client Adapter
- API LLM Adapter
- Ollama Adapter
- SQLite Repository Adapter
- LangGraph Checkpointer Adapter
- LLM API Key용 OS Keyring Adapter
- MCP 내부 Google Credential Provider
- Hardware·Process Diagnostics Adapter
- Clock·UUID Adapter

## 8. 제어형 Agent 실행 모델

Google Work Agent는 자유 대화형 Agent 군집이나 Peer-to-Peer A2A를 사용하지 않는다. 하나의 결정적 LangGraph Supervisor가 6개 전문 Agent Subgraph, 일반 코드 검증, 사용자 Interrupt와 결정적 실행·검증 Engine을 조정한다.

```mermaid
flowchart TB
    S(["시작"]) --> ENTRY{"요청 진입 방식"}
    ENTRY -->|"선택 자원<br>RESOURCE_SELECTED"| SD["선택 자원 최신 상세 조회"]
    ENTRY -->|"에이전트 검색<br>AGENT_SEARCH"| INT["요청 구조화<br>LLM + 스키마"]
    INT --> RP["검색 계획 생성"]
    RP --> RET["원본 서비스 기반 목록 검색"]
    SD --> CTX["문맥 정규화"]
    RET --> REDUCE["메타데이터 기반 후보 축소"]
    REDUCE --> DETAIL["필요 후보 상세 조회"]
    DETAIL --> CTX
    CTX --> ENOUGH{"문맥이 충분한가?"}
    ENOUGH -->|"아니오·재검색 가능"| RP
    ENOUGH -->|"모호함"| Q["사용자 확인 대기<br>Interrupt"]
    Q --> CTX
    ENOUGH -->|"충분"| ANALYZE["관계·중복·충돌·가능성 분석"]
    ANALYZE --> PLAN["실행 계획 초안"]
    PLAN --> POLICY["스키마·정책·근거 검증"]
    POLICY --> APPROVAL["사용자 승인 대기<br>Interrupt"]
    APPROVAL --> PRE["승인·해시·원본·멱등성 재검증"]
    PRE --> TOOL["MCP 쓰기 도구"]
    TOOL --> GET["Google 자원 재조회"]
    GET --> VER{"예상값과 실제값이 일치하는가?"}
    VER -->|"일치"| DONE(["완료"])
    VER -->|"불일치"| REC["복구 선택 대기<br>Interrupt"]
```

### 8.1 LLM 담당 영역

- 자연어 의미와 목표 이해
- 검색 Query·Source 후보 제안
- Gmail Thread에서 업무 의미 추출
- Context 관련도와 추가 검색 후보 제안
- 사용자에게 보여줄 요약
- Gmail Draft 본문 생성
- Action Plan 초안 생성

### 8.2 결정적 코드 담당 영역

- Tool Allowlist와 금지 기능
- 날짜·시간·Timezone 계산
- Task 중복과 Calendar 충돌 최종 판정
- Action Schema와 허용 필드
- Approval Hash와 만료
- Idempotency
- MCP Write 실행 허용
- Google 재조회 결과 정상화·비교
- Secret 접근과 로그 마스킹

### 8.3 요청 진입 방식과 Source 조회

- `RESOURCE_SELECTED`: 사용자가 사이드바에서 선택한 Resource ID를 시작점으로 최신 상세를 조회하고, 요청 수행에 필요할 때만 다른 Source를 확장한다.
- `AGENT_SEARCH`: Query·기간·사람·이메일·Keyword를 구조화해 Google Source-native 목록 검색을 수행하고, Metadata로 후보를 축소한 뒤 필요한 후보만 상세 조회한다.
- 사이드바 목록 페이지와 Page Token은 React Client Session Cache에만 유지하며 SQLite에 영구 저장하지 않는다.
- 두 진입 방식은 Context 구성 이후 동일한 분석·계획·승인·실행·검증 Workflow를 사용한다.

## 9. 컴포넌트 책임

| 컴포넌트 | 핵심 책임 | 소유하지 않는 책임 |
|---|---|---|
| React Frontend | 사용자 입력, View State, REST·SSE 렌더링 | Google Write 실행, 정책 결정, Secret 접근 |
| Typed API Client | Versioned REST·SSE 통신, Cursor·Request ID | Domain 상태 결정 |
| Frontend Session Cache | 사이드바 목록 페이지·Page Token의 UI 세션 재사용 | 영구 승인·실행 상태 |
| FastAPI Adapter | Local Session·Schema·Command·Event 경계 | Policy·Domain 규칙 복제 |
| Application Services | Run 명령, 상태 전이, 승인·실행·복구 조정 | LLM 의미 판단, Google SDK 세부사항 |
| LangGraph Runtime | Workflow, Interrupt, Checkpoint 재개 | 승인·실행 사실의 유일한 저장 |
| Domain·Policy | Allowlist, 정책, 중복·충돌, 무결성, 검증 판정 | UI와 외부 SDK |
| LLM Runtime Router | 요청 모드와 실제 Runtime 선택, fallback 기록 | 정책 우회, Tool 허용 |
| MCP Client | Tool 계약 호출과 Transport 관리 | Google Credential 원문 관리 |
| Google Work MCP Server | Google OAuth·API Adapter, Tool Registry, 실행 경계 검증 | Agent 계획과 사용자 UX |
| Domain Repositories | Conversation·Run·Action·Approval·Execution·Verification 저장 | Graph 중간 Channel 상태 |
| LangGraph Checkpointer | Graph State와 Interrupt 재개 정보 | 감사 사실의 기준점 |
| Audit Writer | 승인·수정·차단·실행·검증 append-only 기록 | 전체 Gmail 원문 저장 |

## 10. 상태와 데이터 소유권

| 데이터 | 기준 저장소 | 설명 |
|---|---|---|
| 패널 열림·너비, 현재 탭, 임시 선택 | React Client State 또는 비밀이 아닌 로컬 설정 | UX 상태이며 실행 사실이 아님 |
| 사이드바 목록 페이지·Page Token | React Client Session Cache | UI 세션 종료·계정 변경·수동 새로고침 시 폐기 |
| Agent 검색 중간 후보와 상세 원문 | 현재 Run 메모리 | 사용되지 않은 후보와 전체 원문은 영구 저장하지 않음 |
| Conversation·Message | SQLite Domain Store | 대화 내역 복원 |
| Run·Action·Approval | SQLite Domain Store | 제품의 제안·승인 사실 기준점 |
| Execution·Verification | SQLite Domain Store | 중복 방지와 실제 결과 기준점 |
| Audit | SQLite append-only 저장 | 안전·책임 추적 |
| Graph State·Interrupt | LangGraph Checkpointer | Workflow 재개 지점 |
| Gmail·Tasks·Calendar 원본 | Google Workspace APIs | 원본 Resource의 기준점 |
| 실제 사용 Resource ID·Evidence excerpt | SQLite Domain Store | Run 보존 기간 동안 최소 근거 보존 |
| OAuth Refresh Token·LLM API Key | OS Keyring | SQLite·Checkpoint·로그 저장 금지 |
| Local Model | Ollama Model Store | 제품이 임의 경로를 직접 관리하지 않음 |

### 10.1 Checkpoint와 Domain Store 분리 원칙

```text
LangGraph Checkpoint = 어디서 Workflow를 재개할 것인가
Domain Store          = 무엇이 제안·승인·실행·검증되었는가
```

Graph Node 구성이 변경되거나 Checkpoint가 정리돼도 승인·실행·Audit 사실은 Domain Store에 남아야 한다. 반대로 Domain Row만으로 LLM 호출 중간 상태를 복원하려 하지 않는다.

### 10.2 Google Source Cache 소유권

- 목록 페이지는 사용자 탐색 속도를 위한 세션 데이터다.
- Cache Key는 Google 계정, Source, 검색·필터, 정렬, Page Token 조합으로 구성한다.
- 동일 세션에서 이미 본 페이지를 재방문할 때만 재사용한다.
- Cache는 승인·중복·충돌·검증 판단의 기준점이 아니다.
- 선택형 요청 시작, 계획 확정, 승인 후 실행 직전, 실행 직후에는 Google API 응답을 우선한다.

## 10-A. Local API와 Event 계약

### REST

- Prefix: `/api/v1`
- Query와 Command Endpoint를 분리한다.
- 상태 변경 Command는 `command_id`, 대상 ID, `expected_version`을 포함한다.
- 응답은 현재 상태, Version, 적용 여부와 공통 Error를 반환한다.
- Timeout 후 UI가 성공·실패를 추정하지 않고 Snapshot을 재조회한다.

### SSE

- Run 단위 Event Stream을 사용한다.
- Event는 증가 Cursor, Run ID, 선택적 Action ID, Type, Projection Version을 포함한다.
- 재연결 시 `Last-Event-ID` 또는 명시 Cursor를 사용한다.
- Cursor를 복원할 수 없으면 Run Snapshot 조회 후 최신 Stream에 연결한다.
- SSE Event는 Domain Event Log의 영구 원본이 아니라 UI Projection이다.

### Local 요청 보호

- `127.0.0.1` 동적 포트만 사용한다.
- 운영 UI와 API는 same-origin이다.
- Launcher 일회성 Bootstrap으로 Local Session을 수립한다.
- Host·Origin·Content-Type·Session을 검증한다.
- Wildcard CORS와 외부 Network Bind를 금지한다.

## 11. 주요 Run·Action 상태

상세 상태 전이와 필드는 04·06 문서에서 정의하되, 아키텍처는 다음 상태군을 지원해야 한다.

### 11.1 Run 상태군

```text
CREATED
ANALYZING
RETRIEVING
WAITING_CONFIRMATION
PLANNING
WAITING_APPROVAL
EXECUTING
VERIFYING
COMPLETED
CANCEL_REQUESTED
CANCELLED
REAUTH_REQUIRED
RECOVERY_REQUIRED
FAILED
BLOCKED
```

### 11.2 Action 상태군

```text
PROPOSED
MODIFIED
APPROVED
REJECTED
EXPIRED
EXECUTING
UNKNOWN_RESULT
EXECUTED
VERIFIED
FAILED
BLOCKED
DEPENDENCY_BLOCKED
MISMATCH
```

허용되지 않은 상태 전이는 Application Service와 Repository에서 차단한다. UI는 상태를 변경하지 않고 명령만 제출한다.

## 12. 승인·실행·검증 안전 경계

### 12.1 승인 정보

Approval Record는 최소한 다음 논리 정보를 가진다.

```text
approval_id
run_id
plan_id
action_id
tool_name
canonical_arguments_hash
policy_version
tool_schema_version
source_snapshot_reference
approved_at
expires_at
```

구체 Schema는 04·07·09 문서에서 확정한다.

### 12.2 실행 전 검증 순서

```mermaid
flowchart TB
    A["승인 정보 조회"] --> B{"승인 상태?"}
    B -->|"아님"| X["차단"]
    B -->|"승인"| C{"만료 여부"}
    C -->|"만료"| X
    C -->|"유효"| D{"정책·스키마 버전 일치"}
    D -->|"불일치"| X
    D -->|"일치"| E["원본 자원 최신 재조회"]
    E --> F{"원본 변경?"}
    F -->|"변경"| X
    F -->|"미변경"| G{"인자 해시 일치"}
    G -->|"불일치"| X
    G -->|"일치"| H["중복·충돌·멱등성 재검증"]
    H --> I["MCP 쓰기 도구 허용"]
```

### 12.3 MCP의 이중 방어

FastAPI Local Agent Service의 Application·Domain에서 승인과 Policy를 검증해도 MCP Server는 다음을 다시 확인한다.

- 등록된 Tool인지
- Input Schema를 통과하는지
- 허용된 필드만 포함하는지
- Approval Token·Action ID·Tool Name이 일치하는지
- Canonical Arguments Hash가 일치하는지
- 현재 Google 계정과 대상 Resource가 일치하는지

금지 Tool은 MCP Server에 등록하지 않는다.

### 12.4 실행 후 검증

```text
Write Tool 실행
→ Resource ID와 실행 Metadata 저장
→ Google GET 재조회
→ 공통 Resource Schema로 정상화
→ expected와 actual 필드 비교
→ VERIFIED 또는 MISMATCH 저장
```

Mismatch는 자동 수정하지 않고 Recovery 선택지를 사용자에게 제공한다.

## 13. Action DAG와 부분 실행

Plan은 Action과 Dependency로 구성한다.

```mermaid
flowchart LR
    T["할 일 생성"] --> E["작업 일정 생성"]
    T --> D["Gmail 임시보관 메일 생성"]
```

- 독립 Action은 다른 Action 실패와 무관하게 실행할 수 있다.
- 종속 Action은 선행 Action의 검증 성공 조건을 확인한다.
- 성공 Action은 자동 롤백하지 않는다.
- 일부 승인 시 승인된 Action과 독립 Action만 실행한다.
- Action 수정으로 종속 Arguments가 바뀌면 관련 Action을 재계획·재검증한다.

SQLite와 Google API를 하나의 ACID Transaction으로 묶을 수 없으므로 Plan 전체가 아닌 Action 단위 상태 전이를 사용하는 Saga형 실행으로 처리한다.

## 14. Idempotency와 결과 불명확 처리

### 14.1 중복 실행 원인

- REST Command Retry
- 승인 버튼 중복 클릭
- 브라우저 새로고침·탭 복제
- SSE Event 중복 수신
- 앱 재시작 후 Run 재개
- MCP 응답 유실
- Google API Timeout 후 Retry

### 14.2 기본 원칙

```text
React UI는 Google 쓰기를 직접 호출하지 않는다.
REST Command는 Application Service를 통해 Approval·Command를 DB에 저장한다.
Execution Service는 영구 Action 상태와 Idempotency 정보를 확인한 뒤 한 번만 실행한다.
```

### 14.3 결과 불명확 상태

Google API 요청을 전달한 뒤 MCP 연결이 끊기면 실패로 단정하지 않는다.

```text
EXECUTING
→ 응답 유실
→ UNKNOWN_RESULT
→ Google에서 대상 Resource 후보 재조회
→ 기존 실행 확인
→ EXECUTED 또는 FAILED 확정
```

`UNKNOWN_RESULT`의 상세 표현과 조회 전략은 08·14 문서에서 확정한다.

## 15. MCP Server 아키텍처

```mermaid
flowchart TB
    STD["MCP 표준 입출력 전송"] --> REG["도구 등록부·허용 목록"]
    REG --> VAL["스키마·승인 검증기"]
    VAL --> AUTH["Google 인증정보 제공자"]
    AUTH --> GML["Gmail 어댑터"]
    AUTH --> TSK["할 일 어댑터"]
    AUTH --> CAL["캘린더 어댑터"]
    GML --> API["Google API"]
    TSK --> API
    CAL --> API
    API --> NORM["Google 응답 정규화기"]
```

### 15.1 MCP Server 책임

- MCP Protocol 처리
- Tool Registry와 금지 Tool 미등록
- Pydantic Input·Output Schema 검증
- Approval 무결성의 실행 경계 검증
- OS Keyring에서 Google Credential 사용
- Access Token 갱신
- Gmail·Tasks·Calendar API 호출
- Google 오류를 공통 오류 형태로 변환
- 생성·수정 Resource GET 재조회 지원

### 15.2 프로세스 수명주기

- Launcher와 Local Agent Service 시작 검사에서 MCP 실행 가능 여부를 확인한다.
- 한 앱 Runtime에서 공유하는 단일 MCP 자식 프로세스를 기본으로 한다.
- REST 요청·SSE 재연결·브라우저 새로고침마다 새 MCP 프로세스를 만들지 않는다.
- `stdout`은 MCP Protocol 전용으로 사용하고 기술 로그는 `stderr` 또는 로컬 로그 Sink로 보낸다.
- 비정상 종료 시 제한된 횟수로 재시작한다.
- Write Tool 중 종료되면 Google 재조회로 결과를 확정하기 전 새 쓰기를 실행하지 않는다.
- 앱 정상 종료 시 자식 프로세스를 정리한다.

재시작 횟수·Backoff 값은 10·14 문서에서 결정한다.

## 16. LLM Runtime Router

### 16.1 입력과 출력

Router는 다음 값을 분리해 기록한다.

```text
requested_mode
actual_runtime
provider
model
fallback_reason
latency
token_usage
estimated_cost
structured_output_attempts
```

### 16.2 모드 규칙

| 환경·선택 | 동작 |
|---|---|
| CPU-only 또는 GPU 기준 미달 | `API_LLM` 고정 |
| `API_ONLY` 배포 | `API_LLM`만 사용 |
| `LOCAL_CAPABLE` + `LOCAL_GPU` | Ollama만 사용하며 동의 없는 API 전환 금지 |
| `LOCAL_CAPABLE` + `API_LLM` | API Provider만 사용 |
| `LOCAL_CAPABLE` + `AUTO` | Ollama 우선, 허용된 기술 실패에서 API로 최대 1회 fallback |
| 사용 가능한 Runtime 없음 | Agent 실행 차단과 설정 Action 제공 |

AUTO fallback 허용 원인:

- Local Runtime 연결 실패
- 제품 모델 없음 또는 로드 실패
- GPU OOM
- Timeout
- 반복된 Structured Output 실패

답변 품질 불만이나 낮은 자신감만으로 자동 fallback하지 않는다.

### 16.3 Structured Output

모든 Agent 판단 출력은 Pydantic Schema를 통과한 뒤 사용한다. Parsing 실패는 제한적으로 재시도하고, 반복 실패 시 현재 모드 정책에 따라 fallback 또는 오류로 처리한다.

## 17. Credential과 신뢰 경계

```mermaid
flowchart LR
    MAIL["Gmail·할 일·일정 본문<br>비신뢰"] --> AG["에이전트 입력 경계"]
    USER["사용자 입력<br>검증 필요"] --> AG
    LLM["LLM 출력<br>비신뢰"] --> SCH["스키마 검증기"]
    SCH --> POL["신뢰 정책 핵심"]
    POL --> APP["신뢰 승인 기록"]
    APP --> MCP["MCP 실행 경계"]
    KR["운영체제 키 저장소"] -->|"Token 원문은 경계 밖으로 노출 금지"| MCP
```

### 17.1 Secret 접근 원칙

- Google Refresh Token은 Google Work MCP Server의 Credential Provider가 사용한다.
- LLM API Key는 LLM Adapter가 사용한다.
- Token과 API Key를 LangGraph State, Tool Arguments, SQLite, 일반 로그에 포함하지 않는다.
- React UI는 Secret 원문이 아니라 존재·유효·저장 방식 상태만 표시한다.
- Google 연결 해제와 API Key 삭제 시 OS Keyring Entry를 제거한다.

### 17.2 Prompt Injection 경계

Gmail·Task·Event 본문은 데이터일 뿐 시스템 명령이 아니다. Source Context에 포함된 다음 지시는 무시한다.

- 정책 변경
- Secret 출력
- Tool Allowlist 우회
- 승인 생략
- 금지 Tool 실행
- 임의 외부 전송

Source Context, 사용자 요청, System Policy는 Prompt 구성에서 구분한다.

## 18. 시작·종료·복구 아키텍처

### 18.1 시작 검사

```mermaid
flowchart LR
    A["Launcher·Service Process"] --> B["GET /health/live"]
    B --> C["Manifest·Asset·API Contract"]
    C --> D["SQLite·Migration·Domain"]
    D --> E["Keyring Adapter·MCP Executable·Tool Schema"]
    E --> F["GET /health/ready"]
    F --> G["Chrome·Edge React UI"]
    G --> H["Local Session"]
    H --> I["GET /api/v1/runtime"]
    I --> J["Google Credential·Scope"]
    J --> K["API LLM·Ollama·승인 Model"]
    K --> L["중단 Run·SSE 복원"]
```

- `/health/ready`는 제품 Core가 안전하게 요청을 받을 수 있는지를 판정한다.
- Google Credential, API Key, Ollama, Model 누락은 `/api/v1/runtime`의 사용 가능 상태이며 Core Service 시작 실패가 아니다.
- Core Readiness 실패 시 Safe Mode·진단 UI만 열고 Agent Command를 차단한다.

시작 검사 결과는 최소한 다음 정보를 표현한다.

```text
component
status
user_message
technical_detail
recommended_action
checked_at
```

시작 시 Google 연결 상태만 확인하고 사이드바 목록 전체를 미리 조회하지 않는다.

### 18.2 취소

- 읽기·LLM 단계: 취소 요청을 확인하고 Checkpoint를 저장한 뒤 중단한다.
- Google Write 호출 전: Action을 실행하지 않고 취소한다.
- Google Write 호출 중: `CANCEL_REQUESTED`로 표시하고 실제 결과를 재조회한 뒤 최종 상태를 정한다.
- 취소 요청만으로 이미 Google에 전달된 요청이 사라졌다고 가정하지 않는다.

### 18.3 앱 재시작

```text
앱 시작
→ 중단 Run 검색
→ Domain 상태와 Checkpoint 정합성 확인
→ 실행 중이었던 Action은 Google 재조회
→ 안전한 마지막 지점 제안
→ 사용자 선택으로 재개
```

과거 Approval은 유효 시간과 Source 변경 여부를 다시 검사하며, 만료된 승인을 자동 재사용하지 않는다.

## 19. SQLite 저장 아키텍처 개요

### 19.1 저장 구성

권장 기본 구조:

- 하나의 앱 전용 SQLite 파일
- Domain Table과 LangGraph Checkpoint Table은 논리적으로 분리
- Repository와 Checkpointer 외에는 SQL 직접 사용 금지
- 앱 시작 시 Migration 실행
- 쓰기 동시성은 로컬 단일 프로세스 기준으로 제한
- Secret 저장 금지

P0는 Domain Table과 LangGraph Checkpoint Table을 하나의 앱 전용 SQLite 파일에 두고 논리적으로 분리한다. 모든 Connection은 `foreign_keys=ON`, WAL, `synchronous=FULL`, `busy_timeout=5000ms`를 사용한다. 암호화와 패키징 상세는 09·10 문서에서 다룬다.

### 19.2 보존 원칙

- Gmail·Tasks·Calendar의 사이드바 목록 페이지와 Page Token은 React Client Session Cache에, 사용되지 않은 검색 후보는 현재 Python Run 메모리에만 유지한다.
- Gmail 전체 원문과 Task·Event 상세 원문은 기본적으로 장기 저장하지 않는다.
- 실제 Run에서 판단·승인에 사용된 Resource ID, Source, 원본 링크, 최소 Metadata, 필요한 Evidence excerpt만 저장한다.
- Google Workspace 원본 데이터는 Google API를 기준점으로 사용하고 SQLite를 Google 데이터의 원본 저장소로 취급하지 않는다.
- 선택형 요청 시작 시 선택 Resource의 상세를 다시 조회하고, 쓰기 계획 확정 전·승인 후 실행 직전·실행 직후 관련 Resource를 재조회한다.
- Run·Checkpoint 기본 30일, Audit 기본 90일 정책을 지원한다.
- 보존 기간 정리는 앱 시작 또는 명시적 유지보수 시점에 수행할 수 있다.

## 20. 관측성 구조

관측성은 세 층으로 분리한다.

| 층 | 대상 | 목적 |
|---|---|---|
| 사용자 진행 상태 | 현재 단계와 다음 행동 | 기술 로그 없이 작업 진행 이해 |
| Run Trace | Node, Tool, Provider, 모델, Latency, Token, 오류 | 개발·진단·성능 분석 |
| Audit | 승인, 수정, 거절, Policy 차단, 실행, 검증 | 안전·책임 추적 |

Audit는 append-only로 취급하고 사용자 UI에서 수정하지 못하게 한다. Trace와 Audit 모두 Secret, Authorization Header, 불필요한 Gmail 원문을 기록하지 않는다.

## 21. 배포 프로필

### 21.1 API_ONLY

```mermaid
flowchart TB
    L["실행 관리자<br>Launcher"] --> S["FastAPI 로컬 에이전트 서비스"]
    L --> CH["Chrome·Edge·React 화면"]
    CH -->|"REST + SSE"| S
    S --> MCP["Google 업무 MCP 서버"]
    S --> DB["SQLite"]
    S --> KR["운영체제 키 저장소"]
    S --> API["API LLM 제공자"]
```

제외:

- Ollama 의존성
- GPU 진단과 Ollama·Local Model 설정 UI
- Local 모델 파일
- sLLM Experiment Runner

### 21.2 LOCAL_CAPABLE

```mermaid
flowchart TB
    BASE["API_ONLY 공통 구성"] --> O["Ollama 어댑터"]
    O --> GPU["검증된 GPU"]
    O --> MODEL["제품 고정 로컬 모델"]
```

추가:

- Ollama Adapter
- GPU·VRAM·Runtime 진단
- 승인 Local Model 존재·ID·Version 검증과 외부 설치 안내
- `AUTO`, `LOCAL_GPU`, `API_LLM` 선택

두 프로필은 같은 Domain·Policy, Tool Schema, LangGraph, Repository Interface와 Test Suite를 사용한다.

## 22. 권장 소스 구조

```text
frontend/
├─ src/
│  ├─ app/
│  ├─ pages/
│  ├─ components/
│  ├─ features/
│  │  ├─ conversations/
│  │  ├─ resources/
│  │  ├─ runs/
│  │  ├─ approvals/
│  │  └─ settings/
│  ├─ api/
│  ├─ events/
│  ├─ state/
│  └─ types/
├─ package.json
├─ tsconfig.json
└─ vite.config.ts

src/
├─ api/
│  ├─ app.py
│  ├─ middleware/
│  ├─ routes/
│  ├─ schemas/
│  ├─ events/
│  └─ errors/
├─ application/
├─ agent/
├─ domain/
├─ ports/
├─ adapters/
├─ contracts/
├─ diagnostics/
└─ launcher/

mcp_server/
├─ transport/
├─ registry/
├─ validation/
├─ auth/
├─ gmail/
├─ tasks/
├─ calendar/
└─ normalization/
```

의존성 원칙:

```text
React UI → Typed Local API Client
FastAPI Route → Application
Application → Domain + Agent + Ports
Agent → Domain + Ports
Adapters → Ports 구현
Domain → React·FastAPI·LangGraph Runtime·외부 SDK 비의존
```

## 23. 테스트와 Mock 경계

| 경계 | 대체 구현 | 주요 검증 |
|---|---|---|
| LLM Port | Fixed Response·Fixture LLM | Graph 흐름과 Structured Output 오류 |
| MCP Port | In-process Mock MCP | Tool 선택, Arguments, Timeout, 결과 유실 |
| Google Adapter | Fake Gmail·Tasks·Calendar | 중복, 충돌, 재조회, 부분 실패 |
| Repository | Temporary SQLite | Migration, 상태 전이, Idempotency |
| OS Keyring | In-memory Fake Keyring | Secret 비저장, 연결 해제, 삭제 |
| Clock | Fixed Clock | 승인 만료, 보존 기간, 재시도 시간 |
| Ollama Adapter | Mock Local Runtime | OOM, Timeout, Structured Output 실패, fallback |

GPU가 없는 팀원은 `API_ONLY`, Mock, 고정 Fixture로 공통 UI·Graph·Policy·MCP Contract를 개발하고 검증할 수 있어야 한다.

## 24. 금지 아키텍처

- React Event Handler 또는 FastAPI Route에서 Google Write API 직접 호출
- LangGraph Checkpoint만으로 Approval·Execution·Audit 관리
- Gmail 전송·삭제 Tool을 등록한 뒤 Prompt로만 사용 금지
- LLM이 Policy 결과나 승인 유효성을 최종 결정
- React Client State·Browser Storage를 영구 Run 상태로 사용
- 모델·Prompt·Graph 실험 기능을 제품 UI에 노출
- 전체 Plan 실패 시 이미 성공한 Google Resource 자동 롤백
- Tool 응답만 믿고 Google GET 검증 생략
- Token·API Key를 SQLite, Checkpoint, Trace에 저장
- 단일 사용자 로컬 제품에 Queue·Kubernetes·원격 Backend를 근거 없이 추가

## 25. 주요 ADR 목록

| ADR | 주제 | 상태 |
|---|---|---|
| ADR-001 | React + TypeScript + Vite Presentation 선택 | Accepted |
| ADR-002 | FastAPI Local Agent Boundary 선택 | Accepted |
| ADR-011 | Production same-origin Static UI + `/api/v1` | Accepted |
| ADR-012 | REST Command + SSE Event Stream | Accepted |
| ADR-013 | Launcher 기반 Local Process Supervision | Accepted |
| ADR-003 | Supervisor 제어형 계층적 Multi-Agent Workflow 사용 | Accepted |
| ADR-004 | Google 연동을 로컬 MCP `stdio`로 제한 | Accepted |
| ADR-005 | Domain Policy와 Agent 판단 분리 | Accepted |
| ADR-006 | Checkpoint와 Domain Store 분리 | Accepted |
| ADR-007 | 모든 쓰기 후 Effect별 결정적 Verification | Accepted |
| ADR-008 | Action Saga·부분 성공 보존 | Accepted |
| ADR-009 | Ollama를 제품 Local Runtime으로 고정 | Accepted |
| ADR-010 | `API_ONLY`·`LOCAL_CAPABLE` Artifact 분리 | Accepted |

## 26. 세부값 소유 문서

아키텍처는 다음 값을 중복 정의하지 않고 Concern Owner의 최신 계약을 참조한다.

- MCP 재시작·Timeout·Runtime 제한 → `10 Infrastructure`, `14 Operations`
- Approval Source Snapshot·Version Token → `04 Domain·DB`, `07 Interface`
- AUTO fallback 오류 분류 → `07 Interface`, `14 Operations`
- Launcher 패키징·업데이트·비정상 종료 → `10 Infrastructure`
- 보존 기간·Purge → `04 Domain·DB`, `11 Observability`
- Local Log Rotation·최대 크기 → `11 Observability`

## 27. P0 아키텍처 완료 조건

- Launcher가 Local Agent Service를 시작하고 React UI를 자동으로 연다.
- React Static UI와 `/api/v1`이 같은 `127.0.0.1` Origin에서 동작한다.
- REST Retry·중복 클릭·브라우저 새로고침·SSE 재연결로 동일 Write Action이 중복 실행되지 않는다.
- LangGraph Interrupt로 확인 질문·승인·Recovery 후 같은 Thread를 재개한다.
- Approval 없는 Write Tool 호출이 Application과 MCP 양쪽에서 차단된다.
- 금지 Tool이 MCP Registry에 존재하지 않는다.
- 모든 허용 Write Action이 Effect별 결정적 Verification으로 검증된다.
- MCP 응답 유실과 앱 재시작 후 `UNKNOWN_RESULT`를 확인하고 중복 생성 없이 상태를 확정한다.
- API_ONLY 환경에서 Ollama 없이 전체 Core 흐름과 정책 테스트가 동작한다.
- LOCAL_CAPABLE 환경에서 Ollama 기반 `AUTO`, `LOCAL_GPU`, `API_LLM` 모드가 정책대로 동작한다.
- OAuth Token과 LLM API Key가 SQLite·Checkpoint·Trace에 저장되지 않는다.

# 28. 보안·복구 아키텍처

이 절은 일반 웹 서비스 보안 체크리스트를 그대로 이식하지 않고, 로컬 단일 사용자·React·FastAPI·SQLite·MCP `stdio` 구조에서 실제로 필요한 안전성과 복구성을 아키텍처 수준으로 고정한다.

## 28.1 추가 논리 컴포넌트

```mermaid
flowchart LR
    UI["React 화면"] --> IN["입력 검증기·안전 렌더러"]
    IN --> APP["애플리케이션 서비스"]
    APP --> TX["트랜잭션 관리자"]
    APP --> WC["쓰기 조정기"]
    APP --> CB["외부 제공자 장애 회로 등록부"]
    TX --> REP["저장소"]
    WC --> REP
    REP --> DB["SQLite"]
    APP --> MIG["마이그레이션 실행기"]
    APP --> HC["데이터베이스 상태 검사기"]
    APP --> BK["백업·복원 서비스"]
    REL["배포물 무결성 검증기"] --> APP
```

| 컴포넌트 | 책임 | 금지 책임 |
|---|---|---|
| Input Validator | 사용자·Google·LLM·MCP 입력의 Schema, 길이, 개수, 허용값 검증 | 업무 의미 판단 |
| Safe Renderer | 비신뢰 문자열의 Text·Markdown 출력과 URL Scheme 검증 | Raw HTML 실행 |
| Transaction Manager | 짧은 SQLite Transaction 경계와 Commit·Rollback | 외부 API 호출 중 Lock 유지 |
| Write Coordinator | 조건부 상태 전이, 실행권 Claim, Idempotency와 단일 쓰기 조정 | Google 결과를 성공으로 추정 |
| Database Health Checker | Schema Version, 빠른 무결성 검사, Foreign Key 검사, 잠김 상태 진단 | 손상 상태에서 Write 허용 |
| Migration Runner | 순차 Migration, 사전 Backup, 실패 Rollback과 호환성 판단 | 임의 Schema 자동 수정 |
| Backup·Restore Service | 일관된 Backup 생성, 명시적 Restore, 복원 후 재검사 | 실행 중 DB 파일 단순 복사 |
| Provider Circuit Registry | Google·LLM·Ollama·MCP 연속 장애 상태와 재호출 제한 | Policy 오류 자동 Retry |
| Release Integrity Verifier | Dependency·Runtime·Model Version과 Artifact Hash 확인 | 검증되지 않은 자동 업그레이드 |

## 28.2 실행 트랜잭션 경계

Google Write를 포함한 실행은 다음 단계로 분리한다.

```mermaid
flowchart TB
    A["승인된 작업"] --> T1["트랜잭션 A<br>실행권 확보 · APPROVED → EXECUTING<br>멱등성 예약"]
    T1 --> C1["커밋"]
    C1 --> G["Google API 쓰기<br>DB 트랜잭션 없음"]
    G --> T2["트랜잭션 B<br>자원 ID·실행 결과 저장"]
    T2 --> C2["커밋"]
    C2 --> GET["Google 자원 재조회 검증<br>DB 트랜잭션 없음"]
    GET --> T3["트랜잭션 C<br>VERIFIED 또는 MISMATCH 저장<br>감사 기록"]
    T3 --> C3["커밋"]
```

핵심 원칙:

- Google API·LLM·MCP 응답을 기다리는 동안 SQLite Write Transaction을 열어두지 않는다.
- 실행권은 `status`, `version`, `idempotency_key` 조건이 일치할 때 Row 하나만 갱신하는 방식으로 획득한다.
- 상태 갱신 Row 수가 1개가 아니면 Google Write를 호출하지 않는다.
- 외부 호출 성공 후 DB 저장이 실패하면 성공 Resource를 자동 삭제하지 않고 Recovery 대상으로 기록한다.
- Audit 저장 실패가 실제 Google 결과를 뒤집지 않으며 복구 가능한 Pending Audit 상태로 처리한다.

## 28.3 SQLite 연결·동시성 경계

- Domain Repository와 LangGraph Checkpointer는 Connection 책임을 명확히 분리한다.
- 모든 Connection에서 Foreign Key 검사를 활성화한다.
- `busy_timeout=5000ms`, WAL, `synchronous=FULL`, 최대 Transaction 시간, `SQLITE_BUSY` Retry는 `04`의 중앙 Config로 관리한다.
- SQLite가 한 번에 하나의 Writer만 Commit한다는 전제로 Write 경로를 설계한다.
- Python Process Lock은 보조 수단이며 정합성의 최종 기준은 조건부 UPDATE와 DB Constraint다.
- `SQLITE_BUSY` 반복 실패 시 Run을 대기 또는 실패 상태로 전환하고 Busy Loop를 금지한다.
- REST Retry와 브라우저 중복 탭이 같은 Action을 실행해도 한 요청만 실행권을 획득해야 한다.

정확한 PRAGMA 값과 Connection 전략은 `04. 도메인·데이터베이스 설계서`에서 성능·복구 테스트 후 확정한다.

## 28.4 데이터 모델링 경계

### 정규화 대상

- Conversation·Message
- Run·Plan·Action
- Action Dependency
- Evidence와 Action·Evidence 관계
- Approval
- Execution Attempt
- Verification
- Audit Event

### JSON Snapshot 허용 대상

- Action Arguments
- 승인 당시 Arguments Snapshot
- expected·actual 비교 값
- Provider별 Response Metadata
- 버전이 명시된 가변 오류 Detail
- LangGraph Checkpoint Payload

JSON Snapshot은 관계·검색·상태 전이의 기준점으로 사용하지 않는다. Snapshot에는 최소한 `schema_version` 또는 이를 식별할 수 있는 Version 정보가 있어야 한다.

## 28.5 조회·N+1·Pagination 경계

- UI Component가 Row별 Repository 호출을 반복하지 않는다.
- Repository는 `Run + Action + Evidence + Execution`처럼 Use Case에 필요한 Aggregate를 Batch Query 또는 Join으로 제공한다.
- Conversation, Message, Run, Audit은 시간값과 고유 ID를 결합한 Keyset Cursor를 사용한다.
- 작은 고정 설정 목록에는 OFFSET을 허용할 수 있다.
- Google 목록은 Google Page Token을 사용하고 SQLite Cursor와 분리한다.
- Index는 실제 Query의 `WHERE`, `JOIN`, `ORDER BY` 조합과 Query Plan을 기준으로 추가한다.
- 추적 편의만을 이유로 Column과 Index를 과도하게 생성하지 않는다.

## 28.6 마이그레이션·백업·안전 모드

```mermaid
flowchart LR
    START["앱 시작"] --> VER["스키마 버전 확인"]
    VER --> NEED{"마이그레이션이 필요한가?"}
    NEED -->|"예"| BK["일관된 백업 생성"]
    BK --> MIG["마이그레이션 트랜잭션"]
    NEED -->|"아니오"| CHECK["데이터베이스 상태 검사"]
    MIG --> CHECK
    CHECK --> OK{"검사를 통과했는가?"}
    OK -->|"예"| NORMAL["정상 모드"]
    OK -->|"아니오"| SAFE["안전 모드<br>Google 쓰기·도메인 쓰기 차단"]
    SAFE --> REC["진단·백업 복원"]
```

Safe Mode에서 허용:

- DB 진단 결과 확인
- Backup 목록 확인
- 현재 DB 별도 보존
- 사용자가 선택한 Backup Restore
- Restore 후 Schema·무결성 재검사
- Google 연결과 Runtime 진단

Safe Mode에서 금지:

- Google Write Action 실행
- 승인 상태 변경
- 신규 Run의 영구 저장
- 손상 DB에 대한 자동 수정 또는 자동 삭제

## 28.7 외부 제공자 복원력

각 Run은 Config 기반 Budget을 가진다.

- Google 목록 페이지 수
- 상세 Resource 조회 수
- LLM 호출 수
- Context Token
- 재검색 횟수
- Google·LLM Retry 횟수
- MCP 재시작 횟수
- 최대 Run 시간

Component별 Circuit 상태:

```text
CLOSED
OPEN
HALF_OPEN
```

- 기술적 연속 실패만 Circuit 실패로 집계한다.
- Policy·Schema·승인 오류는 Circuit 실패로 집계하지 않는다.
- Circuit이 열리면 새로운 호출을 중단하고 기존 성공 결과를 유지한다.
- Google Source 일부 실패 시 의미 있는 부분 결과가 가능하면 Degraded Mode를 제공한다.
- DB 무결성 실패와 승인 무결성 실패는 Degraded Mode 대상이 아니다.

## 28.8 공급망·배포 경계

Release Pipeline은 다음 Gate를 통과해야 한다.

1. Lockfile 기반 재현 가능한 Dependency 설치
2. Unit·Integration·Policy·Migration Test
3. Dependency 취약점 Scan
4. Secret·Credential Pattern Scan
5. 금지 Tool Registry Test
6. Installer·ZIP·Model Artifact SHA-256 생성
7. Runtime·Ollama·Model ID·Model Hash 기록
8. 지원 종료 Runtime 차단
9. Release Manifest 생성

P0 로컬 제품에는 WAF, VPC, Redis 분산 Lock, Kubernetes, ALB, 자체 JWT·비밀번호 인증을 추가하지 않는다. 제품이 원격 SaaS로 전환될 경우 현재 문서를 확장하는 대신 별도 Threat Model과 원격 서비스 아키텍처를 작성한다.

## 28.9 추가 ADR

| ADR | 주제 | 상태 |
|---|---|---|
| ADR-011 | Google·LLM 외부 호출과 SQLite Transaction 분리 | Accepted |
| ADR-012 | 조건부 상태 전이와 DB Constraint를 실행 동시성 기준점으로 사용 | Accepted |
| ADR-013 | 핵심 Domain 정규화와 Versioned JSON Snapshot 병행 | Accepted |
| ADR-014 | 증가 목록에 Keyset Pagination 사용 | Accepted |
| ADR-015 | Migration 전 일관된 Backup과 DB 실패 Safe Mode 적용 | Accepted |
| ADR-016 | Run Budget과 Component별 Circuit 상태 도입 | Accepted |
| ADR-017 | Dependency·Artifact·Model 무결성을 Release Gate로 관리 | Accepted |

## 28.10 DB 설계 문서로 넘기는 결정

다음 물리값은 아키텍처가 중복 소유하지 않는다. 현재 값은 `04. 도메인·데이터베이스 설계서`와 관련 Concern Owner를 기준으로 한다.

- Domain Table 목록과 Column
- Approval·ExecutionAttempt·Verification Table 구조
- SQLite 파일 분리 여부
- WAL·`synchronous`·`busy_timeout`
- Optimistic Version Column과 상태 전이 SQL
- Idempotency Key 구성
- Index와 Query Plan
- Cursor Encoding
- Backup 보존 개수와 위치
- Integrity Check 실행 주기
- 물리 삭제와 Audit 최소 보존 Schema

# 29. Agent Subgraph 아키텍처

```mermaid
flowchart TD
    SUP["결정적 Supervisor"] --> REQ["요청 이해 Agent"]
    SUP --> ACQ["API 탐색·수집 Agent"]
    SUP --> RET["Context Retriever Agent"]
    SUP --> ANA["업무 분석 Agent"]
    SUP --> PLAN["해결책·계획 Agent"]
    SUP --> REVIEW["계획 검토 Agent"]
    SUP --> EXEC["결정적 실행 Engine"]
    SUP --> VERIFY["결정적 검증·복구 Engine"]
```

- API 수집과 Context 선별은 별도 Agent다.
- Agent는 하나의 Run·Thread를 공유한다.
- 중간 결과는 Checkpoint·Run Retrieval Cache, 승인·실행 사실은 Domain Store가 소유한다.


## 29.1 계층형 Agent Subgraph 계약

P0의 Multi-Agent는 자유 대화형 군집이 아니라 **결정적 Supervisor가 전문 LangGraph Subgraph를 호출하는 계층형 구조**다.

```mermaid
flowchart TD
    SUP["Main Supervisor Graph"] --> A["Agent Subgraph"]
    A --> S["Agent Local State"]
    S --> L["LLM Node"]
    L --> V["Schema / Semantic Validation"]
    V -->|"repair / revision 허용"| L
    V -->|"complete"| R["Versioned Typed Result"]
    R --> SUP
    SUP --> D["Domain Validation"]
    D --> X["Approval / Execution / Verification"]
```

### Agent 정의

Agent는 다음 조건을 함께 만족하는 실행 단위다.

1. Main Supervisor가 하나의 Subgraph로 호출한다.
2. 안정적인 책임 범위와 Prompt 계약을 가진다.
3. Parent State와 분리된 호출 단위 Local State를 가질 수 있다.
4. LLM 출력 검증과 허용된 bounded repair/revision loop를 내부에서 수행한다.
5. 종료 시 Parent Graph에는 Versioned Typed Result와 disposition만 반환한다.
6. 다른 Agent를 직접 호출하지 않는다. Agent 간 이동은 Supervisor가 결정한다.
7. Agent Local State는 장기 Memory가 아니며 Domain Store·Approval·ExecutionAttempt·Verification의 기준점이 아니다.

### Profile 토폴로지

```text
SINGLE_BASELINE  = Unified Agent Subgraph 1개
THREE_STAGE      = Stage Agent Subgraph 3개
SIX_ROLE_BASELINE= Specialized Agent Subgraph 6개
```

Agent 수와 LLM Call 수를 동일시하지 않는다. 한 Agent Subgraph가 acquisition 전후 판단이나 Schema Repair 때문에 둘 이상의 LLM Call을 사용할 수 있다. 실제 호출 수·Token·Latency는 Trace와 Evaluation에서 별도 측정한다.


---

## 29.2 문서 권위 규칙

문서 번호 순서가 아니라 `01 PRD §1.1`의 **Concern Owner 규칙**을 따른다. 이 문서는 자신의 책임 범위만 구체화하며 01-B 안전 정책, 04 Domain·상태 전이, 07 Tool 계약 같은 전문 권위 계약을 완화하지 않는다.


# 30. Prompt Registry와 Ollama 소유권

- 제품 소유 실행 단위는 Launcher, React Frontend, FastAPI Local Agent Service, Google Work MCP Server다.
- Ollama는 사용자가 별도 설치한 외부 Runtime이며 제품이 설치·시작·종료·업데이트하지 않는다.
- FastAPI 내부에 Versioned Prompt Registry를 둔다.
- Prompt Runtime Slot 선택 Key는 `agent_role + subgraph_name + node_name + node_state + purpose + input_schema_version + output_schema_version`다. `failure_reason_code`는 Base Prompt 선택 Key가 아니라 Failure-specific Instruction Block 조립 metadata다.
- `ARC-014`: Supervisor는 Node만 Routing하고 선택된 Agent·Application Node가 PromptRef를 확정한다. Prompt Bundle Manifest로 Version·Hash·Schema를 고정한다.

# 31. 무결성·Credential 아키텍처

## 31.1 Command Receipt

```text
FastAPI Route
→ Application Command Dispatcher
→ command_receipts 예약
→ Domain Guard·조건부 UPDATE·Audit
→ command_receipts 완료
→ 같은 Transaction Commit
```

`command_id`는 재시작 후에도 중복 Command를 식별하는 영속 Key다. Receipt와 Domain 변경 중 하나만 Commit되는 상태를 허용하지 않는다.

## 31.2 OAuth Credential 경계

```text
React
→ FastAPI Connection Adapter
→ Application ConnectionService
→ MCP Credential Port
→ MCP Credential Provider
→ Google OAuth·OS Keyring
```

- MCP Credential Provider만 Authorization Code를 Token으로 교환하고 Refresh Token을 읽고 쓴다.
- FastAPI는 `account_id`, `email`, `granted_scopes`, `connection_status`, `reauth_required`만 받는다.
- Access Token은 MCP Process Memory에만 둔다.

## 31.3 Agent·MCP 호출 경계

```text
Agent Node → Structured Output → Supervisor → Application Node
→ Query Builder·Validator → MCP Port
```

Agent Workflow Layer는 LLM Adapter와 LangGraph Checkpointer에는 접근할 수 있지만 MCP Client·Google API·Domain Repository를 직접 호출하지 않는다.

## 31.4 Write Claim Token

- `ExecutionClaimService`는 Domain Claim Commit 후 Process Memory의 Service–MCP Session Key로 HMAC Token을 생성한다.
- Token Payload는 `service_instance_id`, `action_id`, `approval_id`, `execution_attempt_id`, `tool_name`, `arguments_hash`, `expires_at_ms`, `nonce`다.
- MCP는 Signature·TTL·Binding·Nonce를 검증하고 Nonce를 Process Memory에서 1회 소비한다.
- Service·MCP 중 하나가 재시작하면 기존 Token은 무효다.

# 32. 실행·Recovery 정합성 불변조건
### External I/O ↔ SQLite Transaction
```text
Transaction A: 상태·Version·Snapshot 확보 → COMMIT
External I/O: Google/MCP/LLM 호출 (DB Write Transaction 없음)
Transaction B: expected_version·현재 상태 재검사 → 결과 저장 → COMMIT
```
### Recovery 진입 경계
`RECOVERY_REQUIRED` 진입·해제는 Application → Domain Command(`RequireRecovery`·`ResolveRecovery`) → Repository conditional update 경로만 허용한다. Repository 직접 상태 setter는 금지한다.
### 승인형 Effect
`READ | CREATE | UPDATE | SEND | DELETE`를 사용하고 SEND·DELETE도 동일한 Approval Hash·Claim·UNKNOWN_RESULT 무재실행 원칙을 적용한다.
