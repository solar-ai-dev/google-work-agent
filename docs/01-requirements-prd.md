# 01. Google Work Agent 요구사항 정의서 · PRD

> **문서 기준:** 2026-08-10 Claim V2·Attachment·Task 날짜 의미 설계 결정을 제품 목표·범위의 기준으로 한다. 문서 간 충돌은 §1.1의 권위·책임 소유 규칙으로 판정하며, PRD가 다른 Concern의 전문 권위 계약을 임의로 덮어쓰지 않는다.
>
> **상태:** Draft v2.8 · **기준일:** 2026-08-10 · **대상:** P0 MVP

## 0. 한눈에 보기

- **사용자 문제:** Gmail·Tasks·Calendar에 흩어진 업무를 한 요청으로 연결하고 실행 가능한 계획으로 만든다.
- **Agent 역할:** 이해·근거 수집·분석·계획.
- **결정적 코드 역할:** Policy·승인·상태전이·Write·검증.
- **실험:** 동일 책임을 SINGLE/THREE/SIX Subgraph에 재배치해 Release Graph를 선택한다.
- **비목표:** SaaS, 무승인 자동 Write, 자유형 Peer-to-Peer Agent 군집.


## 1. 문서 목적

이 문서는 Google Work Agent가 해결할 문제, 사용자, 제품 범위, 기능·비기능 요구사항, 완료 조건과 실험 대상을 정의한다. 세부 기능 동작은 `01-A 기능 정의서`, 허용·승인·차단 규칙은 `01-B 정책 정의서`에서 관리한다.

## 1.1 문서 권위·책임 소유 규칙

- **제품 목표·범위:** `01 PRD`가 소유한다.
- **사용자 기능 동작:** `01-A`가 소유하되 PRD 범위와 `01-B` 안전 정책을 완화할 수 없다.
- **안전·금지·승인:** `01-B`가 소유한다.
- **시스템 경계:** `03`이 소유한다.
- **영속 사실·상태 전이:** `04` + Domain 상태 전이 계약 + SQL Constraint가 소유한다.
- **Retrieval / Workflow / Tool 경계:** 각각 `05 / 06 / 07`이 소유한다.
- **검증과 평가:** `12 / 13`은 제품 계약을 측정하며 이를 재정의하거나 완화하지 않는다.
- **Prompt·Failure 정규화:** `15`는 `01/04/05/06/07`을 실험·Prompt 관점으로 정규화하며 상위 안전·Domain 계약을 완화하지 않는다.

같은 Concern에서 문구가 충돌하면 더 구체적인 권위 계약과 실행 가능한 Constraint를 우선하고, 상위 범위를 바꾸려면 상위 권위 문서를 먼저 수정한다.

## 2. 제품 개요

Google Work Agent는 Gmail, Google Tasks, Google Calendar에 흩어진 업무 정보를 조회하고 연결해 사용자의 목표를 달성할 실행 계획을 만든다. 결정적 LangGraph Supervisor가 최대 6개의 전문 **Agent Subgraph**를 조정한다. 각 Agent Subgraph는 자신의 호출 단위 Local State, Prompt 계약, bounded validation·repair/revision loop를 가지며 완료 시 Versioned Typed Result만 Main Graph에 반환한다. Agent별 장기 Memory는 두지 않는다. 역할 분리 수는 제품 불변조건이 아니며 `SINGLE_BASELINE`, `THREE_STAGE`, `SIX_ROLE_BASELINE` 비교 후 Release Graph를 확정한다. 모든 쓰기는 사용자 승인 후 공통 결정적 실행·검증 Engine이 수행하고 Google API 재조회로 검증한다.

## 2.1 Agent · Role · LLM Call · Subgraph 정의

- **Agent:** Main Supervisor Graph가 호출하는 전문 LangGraph Subgraph다. 자기 책임 범위의 Local State와 Prompt 계약을 가지며 bounded loop를 수행하고 Typed Result를 반환한다.
- **Agent Local State:** 한 Agent 호출 안에서만 유지되는 단편 상태다. candidate output, validation error, repair/revision attempt, local disposition 등을 포함할 수 있으나 장기 Memory가 아니다.
- **Role:** Agent가 담당하는 안정적인 업무 책임 계약이다. 같은 Agent 안에서 `INITIAL`, `CLARIFY`, `SCHEMA_REPAIR`, `SEMANTIC_REVISION`, `RECHECK` PromptRef가 달라도 Agent 수가 늘어나는 것은 아니다.
- **LLM Call:** 모델 추론 1회다. Agent 하나가 내부 bounded loop 때문에 둘 이상의 LLM Call을 사용할 수 있으므로 Agent 수와 LLM Call 수는 같은 개념이 아니다.
- **Main Graph State:** Agent 간 공식 Handoff와 Run 재개에 필요한 Versioned Typed State다. Agent 내부 임시 상태를 모두 복제하지 않는다.
- **Multi-Agent:** P0에서는 자유 대화형 Peer-to-Peer 군집이 아니라, 결정적 Supervisor가 2개 이상의 전문 Agent Subgraph를 조정하는 계층형 구조를 뜻한다.


### 외부 설명 용어

내부 구현에서는 위 operational definition에 따라 `Agent Subgraph`라는 용어를 사용한다. 다만 외부 문서·면접에서는 SIX를 곧바로 **“6 autonomous agents”**라고 과장하지 않고, **“deterministic Supervisor가 전문 Agent Subgraph를 조정하는 hierarchical multi-agent workflow”**라고 설명한다. Agent의 학술·산업 정의가 제품마다 다르므로, 자율성 수준·Local State·Tool 권한·Handoff 방식을 함께 명시한다.

Graph Profile의 독립변수는 **Agent Subgraph 분해 수준**이다. `SINGLE_BASELINE=1`, `THREE_STAGE=3`, `SIX_ROLE_BASELINE=6` Agent Subgraph를 사용한다. 실제 LLM Call·Token·Latency는 결과 지표로 측정한다.

제품은 사용자 PC에서만 실행된다. React Frontend와 Python Agent Runtime은 FastAPI Local Agent Service의 same-origin HTTP 경계로 연결한다. 운영 빌드에서는 FastAPI가 React 정적 산출물과 `/api/v1` REST Command, SSE Event Stream을 함께 제공하며 외부 공개 서버나 원격 제품 Backend를 두지 않는다.

## 3. 목표 사용자

### 3.1 1차 사용자

- 본인의 Google 계정으로 Gmail·Tasks·Calendar를 사용하는 개인 사용자
- 하나의 로컬 PC에서 개인 업무를 관리하는 사용자
- 자연어로 업무 정리와 실행 계획을 요청하고 싶은 사용자

### 3.2 사용자 환경

| 항목 | 기준 |
|---|---|
| 운영체제 | Windows 11 x64 우선 |
| UI 실행 | 최신 Chrome·Microsoft Edge에서 로컬 React UI 실행 |
| 실행 위치 | 사용자 로컬 PC |
| 사용자 수 | 앱 인스턴스당 1명 |
| Google 계정 | 동시에 1개 활성 계정 |
| Frontend | React + TypeScript + Vite |
| Local Agent API | FastAPI · `127.0.0.1` · REST Command + SSE Event |
| 제품 실행 | Launcher가 Local Agent Service를 시작하고 브라우저를 연다 |
| Agent | LangGraph |
| Google 연동 | 로컬 MCP Server, `stdio` |
| 저장 | SQLite + OS Keyring |

## 4. 해결할 문제

1. 메일 요청이 Task로 전환되지 않아 업무가 누락된다.
2. Task 예정일, Gmail·사용자 요청의 업무 마감, Calendar 가용 시간이 분리되어 실제 수행 가능성을 판단하기 어렵다.
3. 같은 업무가 메일, Task, 일정에 중복 생성된다.
4. 일정 충돌을 확인하지 않고 회신 Draft나 작업 Event를 만들 수 있다.
5. 일반 LLM은 사용자가 승인하지 않은 쓰기 동작을 수행하거나 근거 없이 계획을 만들 수 있다.
6. Agent 설계 선택이 실제 성능에 미치는 영향을 비교할 실험 체계가 없다.

## 5. 제품 목표

- 자연어 요청에서 목표와 완료 조건을 추출한다.
- 요청에 필요한 Gmail·Tasks·Calendar Source를 동적으로 선택한다.
- Source-native 검색으로 근거를 수집하고 Evidence를 구성한다.
- 업무 간 관계, 중복, 충돌, Evidence 기반 업무 마감 위험을 판단한다.
- 사용자가 검토할 수 있는 Action Plan을 생성한다.
- 승인된 Action만 MCP Tool로 실행한다.
- 모든 쓰기 결과를 재조회하여 검증한다.
- P0에서 API LLM과 GPU Local LLM 모드를 모두 제공한다.
- Local LLM 제품 Runtime은 Ollama로 고정한다.
- CPU-only 또는 GPU 기준 미달 PC에서는 API LLM으로 고정한다.
- GPU가 없는 팀원도 API 배포 프로필로 전체 Agent 기능을 개발·검증할 수 있어야 한다.
- sLLM 실험 환경과 사용자 배포 환경을 분리한다.
- API 모델 실험은 호출량·Token·비용·동시성 한도를 강제한다.
- 모델·Graph·Retrieval 설계를 고정 평가셋으로 비교한다.
- 동일 Semantic Responsibility를 `SINGLE_BASELINE=1`, `THREE_STAGE=3`, `SIX_ROLE_BASELINE=6` Agent Subgraph에 재배치해 비교하고 Release Graph는 평가 결과로 고정한다.
- 안전·승인·실행·검증 계약은 Graph 후보와 무관하게 동일한 결정적 코드로 유지한다.
- API LLM으로 핵심 수직 흐름과 Evaluation Runner를 먼저 안정화한 뒤 동일 Port에 Ollama Adapter를 연결한다.
- React UI와 Python Agent Core를 명시적 계약으로 분리한다.
- 사용자 Command는 REST로 제출하고 Run 진행 상태는 SSE로 전달한다.
- Launcher가 Local Agent Service 시작, Health Check, 브라우저 열기와 종료를 조정한다.
- Frontend 새로고침·중복 Command·이벤트 재연결이 Google 중복 Write로 이어지지 않게 한다.

## 6. 비목표

- SaaS 또는 원격 멀티 사용자 서비스
- 원격 Backend·외부 공개 REST API·멀티 사용자 API 서비스
- 원격 MCP Server
- CPU 기반 로컬 LLM 추론
- Gmail Message·Thread 원문 삭제
- 승인 없이 외부로 영향을 주는 Google Write
- 반복 Event 전체 일괄 수정
- 실시간 메일 감시 및 백그라운드 자동 실행
- 자유 대화형 Agent 군집·Peer-to-Peer A2A·Agent별 독립 장기 Memory
- 범용 웹 브라우징 Agent

## 7. 제품 원칙

1. **사용자 승인 우선:** 쓰기는 항상 승인 후 실행한다.
2. **근거 우선:** Action은 최소 하나 이상의 Evidence를 가져야 한다.
3. **결정적 안전성:** 권한·차단·검증은 LLM이 아닌 일반 코드가 담당한다.
4. **최소 권한:** 필요한 Google Scope와 Tool만 노출한다.
5. **부분 성공 보존:** 독립 Action은 계속 실행하고 성공 결과를 롤백하지 않는다.
6. **실험과 제품 분리:** 제품에는 실험에서 선정된 설정만 노출한다.
7. **로컬 우선:** 상태·로그·Credential은 가능한 한 사용자 PC에 둔다.

## 8. 대표 사용자 시나리오

### UC-01 메일 요청을 업무로 전환

사용자가 특정 메일이나 기간을 지정하면 Agent가 관련 Thread를 읽고 기존 Task와 Calendar를 확인한다. 중복이 없고 시간이 가능하면 Task, 작업 Event, 회신 Draft를 제안한다.

### UC-02 회의 후 후속 업무 정리

사용자가 회의 또는 후속 메일을 기준으로 해야 할 일을 요청하면 Agent가 관련 Event와 Thread를 연결하고 누락된 Task와 후속 Draft를 제안한다.

### UC-03 이번 주 업무 마감 위험 분석

Agent가 미완료 Task의 예정일, 관련 메일·사용자 요청의 실제 업무 마감, Calendar 가용 시간을 구분해 수행 가능·위험·불가능으로 분석하고 재배치 또는 조정 Draft를 제안한다. Google Task의 예정일만으로 실제 업무 마감을 추정하지 않는다.

### UC-04 읽기 전용 탐색

사용자가 아직 Task나 Event로 연결되지 않은 요청을 찾으면 Agent는 조회와 분석만 수행하고 쓰기 Action 없이 결과를 보여준다.

### UC-05 일부 승인

사용자가 여러 Action 중 일부만 승인하면 승인된 Action과 독립된 Action만 실행하고 종속 Action은 차단하거나 계획을 다시 계산한다.

## 9. 기능 요구사항

### 9.1 초기 설정·인증

| ID | 요구사항 | 완료 조건 |
|---|---|---|
| FR-001 | 앱은 최초 실행 시 설정 Wizard를 제공해야 한다. | 사용자는 OAuth Client JSON을 입력하지 않고 Google 로그인, LLM 모드, API Key, 기본 Calendar·Task List만 설정한다. |
| FR-002 | 앱은 개발팀이 소유한 Desktop OAuth Client로 Google 계정을 연결해야 한다. | 사용자는 `Google로 로그인` 버튼을 누르고 Google 동의 화면에서 필요한 Scope를 승인한다. |
| FR-003 | 앱은 동시에 하나의 Google 계정만 활성화해야 한다. | 계정 변경 시 기존 Credential을 해제하고 재인증한다. |
| FR-004 | OAuth Refresh Token과 API Key를 SQLite나 로그에 저장하지 않아야 한다. | Secret이 OS Keyring 또는 Local Agent Process Memory에만 존재한다. |
| FR-005 | 개발·스테이징·운영 OAuth 프로젝트를 분리해야 한다. | 팀 테스트 계정과 운영 사용자가 서로 다른 Google Cloud 프로젝트와 동의 화면을 사용한다. |
| FR-006 | Launcher는 사용 가능한 동적 포트에서 Local Agent Service를 시작하고 Health Check를 완료한 뒤 React UI를 열어야 한다. | 사용자가 Python·포트·명령어를 직접 설정하지 않고 앱을 시작한다. |
| FR-007 | React Frontend와 Local Agent Service는 호환 가능한 API Contract Version을 확인해야 한다. | Version 불일치 시 Agent 실행을 차단하고 재설치·업데이트 안내를 표시한다. |
| FR-008 | 운영 빌드는 React 정적 파일과 Local API를 같은 `127.0.0.1` Origin에서 제공해야 한다. | 일반 웹사이트가 Local Agent Command를 임의 호출하지 못하도록 Host·Origin·Session 검증을 적용한다. |

### 9.2 추론 Runtime

| ID | 요구사항 | 완료 조건 |
|---|---|---|
| FR-010 | 앱은 시작 시 Ollama 기반 Local LLM 사용 가능 여부를 진단해야 한다. | Ollama 연결, 승인 Model 존재, 최소 하드웨어, 테스트 추론 결과를 기록한다. 앱은 Ollama·Model을 설치·시작·종료·업데이트하지 않는다. |
| FR-011 | CPU-only 또는 GPU 기준 미달 PC는 API LLM으로 고정해야 한다. | Local 옵션과 Ollama·Model 설정·진단 UI가 노출되지 않는다. |
| FR-012 | P0의 검증된 GPU 환경에서는 AUTO, LOCAL_GPU, API_LLM을 제공해야 한다. | 사용자가 모드를 선택하고 현재 실제 실행 모드를 확인할 수 있다. |
| FR-013 | AUTO는 기술적 Local 실패 시 API로 최대 1회 fallback할 수 있어야 한다. | 외부 LLM 전송 동의가 있을 때만 fallback하며 이유와 사용된 Provider가 Trace에 기록된다. |
| FR-014 | 명시적 LOCAL_GPU 선택 시 자동 API 전환을 금지해야 한다. | 오류 화면에서 사용자가 전환을 직접 승인한다. |
| FR-015 | Local LLM 제품 Runtime은 Ollama로 고정해야 한다. | 제품 코드에 Ollama Adapter가 기본 Local Provider로 등록되고 다른 Runtime은 제품 설정에 노출되지 않는다. |
| FR-016 | API 전용 배포와 Local 지원 배포를 분리해야 한다. | API_ONLY는 Ollama 의존성을 포함하지 않는다. LOCAL_CAPABLE은 Adapter·진단·승인 Model Manifest만 포함하며 Ollama·Model 자체는 Bundle하지 않는다. |

### 9.3 요청·Context·Retrieval

| ID | 요구사항 | 완료 조건 |
|---|---|---|
| FR-020 | 앱은 자연어 요청에서 목표와 완료 조건을 구조화해야 한다. | 구조화 결과가 Schema Validation을 통과한다. |
| FR-021 | Agent는 요청별 필요한 Source를 선택해야 한다. | Gmail·Tasks·Calendar 전체를 무조건 조회하지 않는다. |
| FR-022 | 각 Source는 공식 Source-native 검색과 조회를 사용해야 한다. | 검색 Query와 조회 범위가 Trace에 남는다. |
| FR-023 | 검색 결과는 공통 WorkItem·Evidence 형태로 정규화해야 한다. | 원본 Resource ID와 Source가 보존된다. |
| FR-024 | Context가 부족하면 최대 2회까지 재검색해야 한다. | 재검색 이유와 Query 변경이 기록된다. |
| FR-025 | 모호한 인물·기간·업무가 있으면 사용자 확인을 요청해야 한다. | 임의 선택 없이 후보와 차이를 제시한다. |
| FR-026 | 긴 Gmail Thread는 인용·서명 제거와 Chunking을 지원해야 한다. | 핵심 본문과 원본 링크를 함께 유지한다. |

### 9.4 분석·계획

| ID | 요구사항 | 완료 조건 |
|---|---|---|
| FR-030 | Agent는 메일·Task·Event의 관계를 Evidence 기반으로 연결해야 한다. | 각 연결에 근거 Resource가 포함된다. |
| FR-031 | Agent는 Task 중복과 Calendar 충돌을 검사해야 한다. | 차단 또는 경고 사유가 사용자에게 표시된다. |
| FR-032 | Agent는 업무 가능성을 가능·위험·불가능으로 분류해야 한다. | 실제 업무 마감은 Gmail·사용자 요청·Evidence에서, 수행 예정일은 Google Task 예정일에서 구분해 예상 시간·가용 Slot 근거와 함께 제시한다. |
| FR-033 | Agent는 Action을 DAG로 생성해야 한다. | 종속·독립 Action이 구분된다. |
| FR-034 | Action은 Tool, Arguments, Evidence, Risk, Expected Result를 포함해야 한다. | 승인 화면에서 모든 필드를 검토할 수 있다. |

### 9.5 승인·수정

| ID | 요구사항 | 완료 조건 |
|---|---|---|
| FR-040 | 모든 쓰기 Action은 실행 전에 사용자 승인을 받아야 한다. | 승인 기록이 없으면 Tool 호출이 차단된다. |
| FR-041 | 사용자는 전체 승인, 일부 승인, 수정, 거절을 할 수 있어야 한다. | Action별 결정 상태가 저장된다. |
| FR-042 | 사용자가 Arguments를 수정하면 Schema·Policy·중복·충돌을 다시 검사해야 한다. | 재검증 완료 전 실행 버튼이 비활성화된다. |
| FR-043 | 승인된 Arguments는 Canonical JSON Hash로 고정해야 한다. | 실행 직전 Hash 불일치 시 차단된다. |
| FR-044 | 승인은 일정 시간 경과 또는 원본 Resource 변경 시 만료되어야 한다. | 만료 시 재조회와 재승인을 요구한다. |

### 9.6 실행·검증·복구

| ID | 요구사항 | 완료 조건 |
|---|---|---|
| FR-050 | 승인된 Action만 MCP Write Tool로 실행해야 한다. | MCP Server가 Approval Token과 Hash를 검증한다. |
| FR-051 | Gmail Draft, Task, Calendar Event 생성·수정을 지원해야 한다. | 정책상 허용된 필드만 변경된다. |
| FR-052 | 모든 쓰기 Action은 실행 후 Effect별 결정적 검증을 수행해야 한다. | CREATE·UPDATE는 GET 비교, DELETE는 대상 부재/삭제 상태, SEND는 Sent 결과 조회가 저장된다. |
| FR-053 | 정상화 가능한 차이와 실제 불일치를 구분해야 한다. | 공백·Timezone 등은 정규화하고 핵심 필드 차이는 MISMATCH로 처리한다. |
| FR-054 | 부분 실패 시 성공 Action을 보존하고 실패 Action만 재시도해야 한다. | 실행 결과와 종속 Action 차단 상태가 표시된다. |
| FR-055 | 브라우저 새로고침, SSE 재연결 또는 앱 재시작 후 Checkpoint와 Domain Store에서 재개해야 한다. | 동일 Thread ID로 승인·실행 상태를 복원하며 Client State만으로 실행 사실을 판단하지 않는다. |
| FR-056 | Run 진행 상태는 재연결 가능한 SSE Event Stream으로 전달해야 한다. | 연결이 끊기면 마지막 Event Cursor 이후 재구독하거나 현재 Run Snapshot을 다시 조회한다. |
| FR-057 | 모든 변경 Command는 Command ID와 대상 Version을 포함해야 한다. | 네트워크 재시도와 중복 클릭이 같은 Domain Transition을 두 번 적용하지 않는다. |
| FR-058 | 상태 변경 Command는 영속 Command Receipt로 중복 적용을 방지해야 한다. | 같은 `command_id`·같은 요청은 기존 결과를 반환하고, 같은 ID·다른 요청은 차단한다. |
| FR-059 | Google Write는 실행 Claim과 결합된 1회용 실행 증명을 MCP가 검증해야 한다. | 승인·Hash·Attempt·Service Instance가 일치하지 않으면 Tool 호출을 차단한다. |

### 9.7 관측성·실험

| ID | 요구사항 | 완료 조건 |
|---|---|---|
| FR-060 | Run·Node·Tool·Action Trace를 로컬에 기록해야 한다. | 민감정보를 제외한 상태·지연·오류·모델 정보가 조회된다. |
| FR-061 | 제품 Runtime과 Experiment Runner를 분리해야 한다. | 제품 UI에서 실험용 모델·Prompt·Graph 변경 기능이 보이지 않는다. |
| FR-062 | 고정 평가셋으로 API 모델, GPU 모델, Graph, Retrieval을 비교해야 한다. | 동일 Dataset과 Policy로 결과 보고서를 생성한다. |
| FR-063 | 안전 기준 미달 Local 모델은 제품 기본 모델로 채택하지 않아야 한다. | P0 Local 기능은 유지하되 해당 후보는 배포 Config에서 제외된다. |
| FR-064 | API LLM 실험은 호출량·Token·비용·동시성 제한을 가져야 한다. | 한도 초과 전에 Runner가 중단되고 소비량과 중단 사유를 보고한다. |
| FR-065 | sLLM 실험과 제품 배포를 분리해야 한다. | GPU 실험 산출물·후보 모델은 일반 배포에 포함되지 않고 Release Gate를 통과한 모델 Config만 승격된다. |

## 10. 비기능 요구사항

| ID | 분류 | 요구사항 |
|---|---|---|
| NFR-001 | 보안 | Local Agent Service는 `127.0.0.1`에만 바인딩하고 LAN·Public Interface에 노출하지 않는다. |
| NFR-002 | 보안 | OAuth Token·API Key·원문 Credential은 로그와 SQLite에 기록하지 않는다. |
| NFR-003 | 개인정보 | API LLM 전송 전 선택된 Context Source와 범위를 사용자에게 고지한다. |
| NFR-004 | 신뢰성 | 쓰기 Action의 승인 준수율, 금지 작업 차단률, 검증 수행률은 100%여야 한다. |
| NFR-005 | 복구성 | Google API 재시도 중복으로 동일 Resource가 반복 생성되지 않아야 한다. |
| NFR-006 | 성능 | 일반 Run은 사용자에게 단계별 진행 상태와 취소 기능을 제공한다. |
| NFR-007 | 호환성 | P0는 Windows 11 x64와 최신 Chrome·Microsoft Edge를 공식 지원한다. React UI는 FastAPI가 제공하는 로컬 Origin에서 동작한다. |
| NFR-008 | 유지보수 | Tool 입력·출력과 LLM Structured Output은 Pydantic Schema로 관리한다. |
| NFR-009 | 테스트성 | Google Client, LLM Provider, MCP Tool은 Mock 가능한 인터페이스를 제공한다. |
| NFR-010 | 감사 | 승인·실행·검증 이벤트는 append-only Audit Log에 기록한다. |
| NFR-011 | 비용·쿼터 | API 실험 Runner는 Provider별 RPM·TPM·요청 수·비용 한도를 적용하고 429 응답을 제한적으로 처리한다. |
| NFR-012 | 배포성 | GPU가 없는 PC는 Ollama 없이 API_ONLY 프로필을 설치·실행할 수 있어야 한다. |

## 11. 데이터 요구사항

- SQLite에는 Conversation, Message, Run, Checkpoint, 실제 Run에서 사용된 Google Resource 참조, Evidence excerpt, Action, 승인 상태, 실행·검증 결과, Audit을 저장한다.
- Gmail·Tasks·Calendar의 사이드바 목록과 Page Token은 SQLite에 영구 저장하지 않고 React Client Session Cache에만 유지한다.
- 이미 조회한 페이지는 동일 UI 세션에서 재사용하며 UI 세션 종료, Google 계정 변경, 명시적 새로고침 시 폐기한다.
- Gmail 전체 원문, Task·Event 상세 원문, Agent 검색 중간 후보는 기본적으로 현재 Run 메모리에서만 사용한다.
- 실제 판단·승인에 사용된 Resource ID, 원본 링크, 최소 Metadata와 Evidence excerpt만 Run 보존 기간 동안 저장할 수 있다.
- Google Workspace 원본 데이터는 Google API 응답을 기준 데이터로 사용하며 로컬 DB를 원본 시스템으로 취급하지 않는다.
- 쓰기 계획 확정 전, 승인 후 실행 직전, 실행 직후에는 관련 Resource를 Google API로 다시 조회한다.
- Secret은 OS Keyring 또는 현재 프로세스 메모리에서만 다룬다.
- 보존 기간과 삭제 기능은 정책 정의서에 따른다.

## 12. 제품과 실험의 경계

### 제품 고정

- 로컬 단일 사용자 앱
- React + TypeScript + Vite Frontend
- FastAPI Local Agent Service + LangGraph + MCP `stdio`
- 운영 빌드는 FastAPI가 React 정적 산출물과 `/api/v1`을 같은 Origin에서 제공
- 승인 후 쓰기
- Tool Allowlist
- 실행 후 검증
- CPU-only API 고정
- Ollama를 Local 제품 Runtime으로 고정
- P0에 API·Local 모드 모두 포함
- API_ONLY·LOCAL_CAPABLE 배포 프로필 분리
- Secret 비저장

### 실험 후 고정

- API Provider와 모델
- GPU Local Model과 최소 GPU 기준
- Release Graph Profile과 Node 세분화
- LLM 호출 단계 수
- Retrieval·Embedding·Reranker·Vector Index
- Context Budget
- 관련도·중복 임계값
- Prompt와 Tool Description
- AUTO fallback 세부 조건

## 13. 출시 기준

### 안전 Gate

| 지표 | 기준 |
|---|---:|
| Approval Compliance | 100% |
| Forbidden Action Block | 100% |
| Write Verification | 100% |
| Approval Argument Integrity | 100% |
| Credential Leakage | 0건 |

### 품질 Gate

| 지표 | 목표 |
|---|---:|
| Source Selection | 90% 이상 |
| Tool Selection | 90% 이상 |
| Tool Argument Accuracy | 90% 이상 |
| Business Task Success (BTS) | Core 기준 80% 이상 |
| Duplicate Creation | 5% 이하 |
| Calendar Conflict | 3% 이하 |

## 14. 단계별 범위

### P0 MVP

- React + TypeScript + Vite 기반 3열 Agent UI
- FastAPI Local Agent Service와 same-origin 정적 UI 제공
- REST Command API + SSE Event Stream
- Launcher 기반 시작·Health Check·브라우저 열기·정상 종료
- 개발팀 소유 OAuth Client와 팀 Test User를 통한 Google 로그인·통합 검증
- Gmail·Tasks·Calendar 읽기
- LangGraph 요청 분석·검색·계획
- Action 승인·수정·거절
- Draft·Task·Event 생성과 수정
- 실행 후 검증
- API LLM Runtime
- Ollama 기반 LOCAL_GPU Runtime
- AUTO fallback
- API_ONLY·LOCAL_CAPABLE 두 배포 프로필
- GPU가 없는 팀원을 위한 API 기반 개발·테스트 경로
- sLLM 실험 Runner와 배포 Config 분리
- API 실험 호출량·Token·비용 제한
- SQLite Checkpoint·Audit
- 기본 평가셋과 회귀 테스트

### P1

- 필요 시 동일 React UI와 Python Core를 Tauri Desktop Shell로 패키징
- 일반 사용자 공개 배포용 OAuth 검증·브랜드·개인정보 정책 정비
- 평가를 통과한 API·Local 기본 모델 고정
- Embedding·Reranking 실험 결과 반영
- 설치·업데이트 개선
- 추가 OS 지원

### P2

- 첨부파일 본문 처리
- 고급 일정 최적화
- 선택적 추가 Provider
- 사용성·성능 개선


## 15. OAuth 사용자 경험과 배포 단계

### 사용자 경험

사용자는 OAuth Client JSON을 만들거나 입력하지 않는다. 앱의 `Google로 로그인` 버튼을 누르고 Google 계정 선택과 권한 동의만 수행한다. 계정 인증만으로 Gmail·Tasks·Calendar 접근이 허용되는 것은 아니므로 Google 동의 화면에서 필요한 Scope 승인이 반드시 포함된다.

### 개발·팀 테스트

- 개발팀이 Google Cloud OAuth 프로젝트와 Desktop Client를 소유한다.
- Desktop App OAuth와 `127.0.0.1` loopback redirect를 사용한다.
- 개발·스테이징·운영 프로젝트를 분리한다.
- Testing 상태에서는 팀 계정을 Test User로 등록한다.
- External + Testing 상태에서 Workspace Scope를 요청한 Refresh Token은 7일 후 만료되므로 재로그인 UX를 P0에서 처리한다.

### 공개 배포 · P1 Release Gate

- Gmail 읽기와 Draft 관리에 필요한 Scope는 Google의 제한 Scope 검증 대상이다.
- 공개 배포 전 OAuth 브랜드·데이터 액세스 검증을 완료해야 한다.
- API LLM 모드에서 Gmail Context를 외부 Provider로 전송하므로 보안 평가와 Limited Use 준수 가능성을 운영 준비 조건으로 관리한다.

## 16. 배포 프로필

### API_ONLY

- GPU·Ollama·모델 파일이 필요 없다.
- CPU-only 또는 GPU 기준 미달 PC의 기본 배포다.
- GPU가 없는 팀원은 이 프로필로 Agent·Tool·Policy·UI·API 평가를 수행한다.

### LOCAL_CAPABLE

- Ollama가 제품 고정 Local Runtime이다.
- 검증된 GPU에서 LOCAL_GPU와 AUTO를 활성화한다.
- 실험용 모델 파일과 실험 Runner는 사용자 배포 패키지에 포함하지 않는다.

## 17. API 실험 호출 제한 기본안

- Smoke: 5 Case
- Screening: 20 Case
- Full: 60 Case, Screening 통과 후보만 실행
- Full Batch 요청 상한 초기값: 300회
- 동시 호출 초기값: 2
- 429·일시 오류 재시도: 최대 1회
- Full Batch 비용 상한 초기값: USD 15
- Provider별 RPM·TPM은 실제 계정 한도의 80% 이하로 설정
- 동일 Provider·Model·Prompt·Schema·Input Hash 결과만 재사용 가능

위 수치는 제품 정책이 아니라 실험 운영 초기값이며 Provider Quota와 예산에 따라 낮출 수 있다.

## 17-A. Frontend · Local Agent Service 경계

### 운영 실행 구조

```text
Launcher
→ FastAPI Local Agent Service 시작
→ GET /health/live
→ Manifest·Asset·API Contract·SQLite·Migration·Domain·Keyring Adapter·MCP Core Readiness
→ GET /health/ready
→ React 정적 UI와 `/api/v1` 제공
→ Chrome 또는 Microsoft Edge에서 `127.0.0.1:<dynamic-port>` 열기
→ Local Session 수립
→ GET /api/v1/runtime로 Google·API LLM·Ollama·Model 사용 가능 상태 진단
```

### 통신 원칙

- 조회와 Command는 Versioned REST API를 사용한다.
- Run 진행 상태는 Server-Sent Events를 사용한다.
- Frontend는 LangGraph, SQLite, Keyring, MCP를 직접 호출하지 않는다.
- FastAPI Route는 Domain 상태를 직접 수정하지 않고 Application Command를 호출한다.
- Domain Store가 승인·실행 사실의 기준점이며 React Client State는 화면 상태만 소유한다.
- 운영 빌드에서 외부 공개 API, LAN 접속, Reverse Proxy를 지원하지 않는다.

## 17-B. 구현·배포 순서

```text
Domain 상태 전이·SQLite·Command Receipt
→ Fake Google Gateway·Fixture
→ Answer-only
→ READ-only
→ 단일 WRITE 승인·실행·GET 검증
→ UNKNOWN_RESULT 복구
→ API LLM 기반 요청 이해·수집·분석·계획
→ Evaluation Runner
→ Ollama Adapter·Local Model Screening
→ 팀 Test User Google 통합
```

- P0 OAuth 완료 기준은 개발·스테이징 프로젝트의 팀 Test User를 사용한 실제 Gmail·Tasks·Calendar 통합 데모다.
- 일반 사용자 공개 OAuth 검증과 제한 Scope 운영 승격은 P1 Release Gate다.
- Local 기능은 P0에 유지하되 API 수직 흐름이 통과한 후 구현한다.

## 18. 문서 관계

- 본 문서: 제품 목표·범위·요구사항·완료 조건
- `01-A 기능 정의서`: 사용자 기능과 시스템 동작의 상세 사양
- `01-B 정책 정의서`: 허용·승인·차단·데이터·추론·오류 정책

## 19. Google Source 탐색·목록 요구사항

### 19.1 두 가지 요청 진입 방식

1. **Agent 검색형:** 사용자가 Query, 날짜, 사람·이메일, 기간 또는 복합 요구사항을 자연어로 입력하면 Agent가 필요한 Source와 검색 조건을 구조화하고 Google Source-native API를 호출한다.
2. **사용자 선택형:** 사용자가 왼쪽 Gmail·Tasks·Calendar 목록에서 하나 이상의 Resource를 선택하고 요청하면 선택된 Resource를 Context 시작점으로 사용한다.

### 19.2 사이드바 목록

- Gmail은 최근 수신 순, Tasks는 configured/default Task List의 미완료 Task를 기본적으로 Google Tasks Provider 반환 순으로, Calendar Month View의 선택 날짜 Event 목록은 `startTime` 순으로 표시한다. Calendar 월력은 visible grid range 전체를 materialize하며 UI pagination을 사용하지 않는다. Tasks는 Provider batch 최대 100개를 UI 20개 page로 나누고 nextPageToken 기반 lazy continuation을 사용한다. 사용자가 날짜순을 선택한 경우에만 전체 미완료 Task를 materialize하여 `scheduled_date` 오름차순·날짜 없는 Task 후순위로 정렬하며, 이 결과는 별도 React Client Session Cache에 둔다.
- Sidebar의 페이지 단위와 Source별 기본 조회 범위는 `01-A 기능 정의서`와 `07 Interface`의 Canonical Query 계약을 따른다.
- 다음 페이지 이동 시 Google API에서 새 목록을 조회한다.
- 이미 조회한 페이지는 React Client Session Cache에서 재사용하고 SQLite에는 영구 저장하지 않는다.
- 페이지 이동 자체는 이미 조회한 페이지에 대한 반복 API 호출을 발생시키지 않아야 한다.

### 19.3 사용자 선택형 처리

- 하나 또는 여러 Resource를 선택할 수 있어야 한다.
- 선택된 Resource ID를 기준으로 최신 상세 내용을 조회한 뒤 요청을 수행한다.
- 선택된 대상을 다시 검색해 찾도록 요구하지 않는다.
- 관련 Gmail·Task·Calendar 추가 검색은 사용자 요청을 수행하는 데 필요한 경우에만 확장한다.

### 19.4 Agent 검색형 처리

- Agent는 사용자 요청에서 기간, 사람·이메일, Keyword, 대상 Source와 Resource 조건을 추출한다.
- 목록 검색으로 후보를 확보한 뒤 필요한 후보만 상세 조회한다.
- 검색 결과 전체를 LLM에 전달하지 않고 일반 코드와 Metadata로 후보를 줄인 뒤 필요한 Context만 전달한다.
- Context가 부족할 때만 최대 2회 재검색한다.

### 19.5 완료 조건

- 사용자는 사이드바에서 최신 목록을 탐색하고 현재 항목에서 바로 Agent 요청을 시작할 수 있다.
- 동일 세션에서 이미 본 페이지로 돌아갈 때 추가 API 호출 없이 즉시 표시된다.
- 선택형 요청과 Agent 검색형 요청이 동일한 Action Plan·승인·검증 흐름으로 연결된다.
- Google 목록 전체를 SQLite에 복제하지 않고도 대화 재개와 승인 근거를 복구할 수 있다.

## 20. Secure & Resilient 비기능 요구사항

이 절은 일반 SaaS 체크리스트 전체를 적용하는 것이 아니라, 로컬 단일 사용자·React·FastAPI Local Agent Service·SQLite·MCP `stdio` 구조에 실제로 필요한 안전성과 복구성 기준을 정의한다.

| ID | 분류 | 요구사항 |
|---|---|---|
| NFR-013 | 입력 검증 | 사용자 입력, Google API 응답, LLM 출력, Resource ID·Page Token은 비신뢰 데이터로 취급하고 타입·길이·개수·날짜 범위·허용값을 중앙 Schema에서 검증해야 한다. |
| NFR-014 | 출력 안전성 | Google·사용자·LLM 문자열을 Raw HTML로 렌더링하지 않고 안전한 Text·Markdown으로 표시해야 한다. 외부 링크는 허용 Scheme과 목적지를 검증해야 한다. |
| NFR-015 | 오류 격리 | 사용자 오류 메시지와 기술 진단 정보를 분리하고 Stack Trace, SQL, 로컬 경로, Credential 상태 원문을 일반 화면에 노출하지 않아야 한다. |
| NFR-016 | 로컬 노출면 | FastAPI Local Agent Service는 `127.0.0.1`의 동적 포트에만 바인딩한다. Host·Origin·Local Session 검증을 적용하고 원격 접속·Public Bind를 금지한다. |
| NFR-017 | DB 동시성 | SQLite 쓰기는 Application의 단일 Write Coordination 경계를 통과하고, 조건부 상태 전이·UNIQUE Constraint·Idempotency로 중복 실행과 Race Condition을 차단해야 한다. |
| NFR-018 | 트랜잭션 | DB Transaction은 짧게 유지하며 Google API·LLM·MCP 네트워크 호출 중 Transaction과 Write Lock을 유지하지 않아야 한다. |
| NFR-019 | 데이터 무결성 | Foreign Key, UNIQUE, NOT NULL, CHECK Constraint와 허용된 상태 전이를 DB·Repository에서 강제해야 한다. 애플리케이션 검증만으로 무결성을 보장하지 않는다. |
| NFR-020 | Migration·복구 | Schema Version, 순차 Migration, Migration 전 안전한 Backup, 실패 시 Rollback·Write 차단, 시작 시 DB 무결성 검사를 지원해야 한다. |
| NFR-021 | 조회 성능 | 대화·메시지·Run·Audit처럼 증가하는 목록은 안정된 정렬키와 Cursor 기반 Pagination을 지원하고, Repository는 화면·Use Case 단위 Batch 조회로 N+1 호출을 방지해야 한다. |
| NFR-022 | 외부 장애 격리 | Run별 Google·LLM 호출 수, 재검색, Retry, Context 크기, 실행 시간을 제한하고 연속 장애 시 새 호출을 일시 중단하는 Circuit 상태를 지원해야 한다. |
| NFR-023 | 공급망 보안 | Dependency Lock, 취약점·Secret Scan, 배포 Artifact Hash, 지원 Runtime Version과 Ollama·제품 모델 Version 고정을 Release Gate로 관리해야 한다. |
| NFR-024 | Backup 검증 | Backup 생성 성공만 확인하지 않고 테스트 환경에서 실제 Restore와 무결성 검사를 반복 검증해야 한다. |
| NFR-025 | Local API 인증 | Launcher가 생성한 일회성 Bootstrap Secret으로 Local Session을 수립하고 Secret을 URL Query·로그·SQLite에 남기지 않아야 한다. |
| NFR-026 | Same-origin UI | 운영 빌드는 React UI와 Local API를 같은 Origin에서 제공하며 임의 Origin 허용을 금지해야 한다. |
| NFR-027 | Event 전달 | SSE는 UI 진행 상태와 식별자 중심으로 전달하고 OAuth Token·API Key·불필요한 원문을 포함하지 않아야 한다. |
| NFR-028 | API 입력 검증 | REST Path·Body·Header·Cursor·Command ID를 중앙 Schema와 Allowlist로 검증해야 한다. |

### 20.1 P0 적용 범위

- P0 필수: NFR-013~NFR-028
- 복원 자동화와 정기 Restore 훈련 고도화: P1에서 운영 절차 확장
- WAF, VPC, Redis 분산 Lock, Kubernetes, ALB, DDoS 방어는 원격 SaaS 전환 전까지 범위에서 제외

### 20.2 DB 설계 문서로 위임할 상세

다음 항목의 정확한 값과 Schema는 `04. 도메인·데이터베이스 설계서`에서 확정한다.

- Transaction 경계와 상태 전이 SQL
- WAL·`synchronous`·`busy_timeout` 설정
- Table 정규화와 JSON Snapshot 경계
- Foreign Key·UNIQUE·CHECK Constraint
- Index와 Query Plan
- Cursor 구성
- Migration·Backup·Restore 절차
- 보존 기간과 물리 삭제

## 21. Agent Workflow 제품 요구사항

- P0 Agent Runtime은 결정적 Supervisor가 Agent Subgraph를 제어하는 평가 가능 계층형 Workflow를 사용한다.
- 초기 Baseline은 요청 이해, API 탐색·수집, Context Retrieval, 업무 분석, 해결책·계획, 계획 검토의 최대 6개 전문 Agent Subgraph다.
- Agent Subgraph의 병합·분리는 `SINGLE_BASELINE(1)`, `THREE_STAGE(3)`, `SIX_ROLE_BASELINE(6)` 실험 대상이며 Release Graph는 평가 결과로 고정한다.
- Supervisor는 현재 Workflow Phase, Agent Result, Domain Command Result와 호출 예산으로 다음 경로를 결정한다.
- Agent 간 전달은 Versioned Structured Output과 Resource·Evidence ID Reference를 사용한다.
- 자유 대화형 Agent 군집, Peer-to-Peer A2A, Agent별 독립 DB·Credential·장기 Memory는 범위에서 제외한다. Agent Subgraph는 호출 단위 Local State만 가진다.
- 승인 이후 Google Write, 상태 전이, 검증과 복구는 Agent Profile과 독립된 결정적 실행·검증 Engine과 Domain Command가 담당한다.
- 요청별 LLM 호출은 필요한 Agent만 실행하며 호출 수·Token·지연 예산을 강제한다.

## 21-A. Agent Workflow Baseline 계약

- 결정적 Supervisor + 최대 6개 전문 Agent Subgraph를 초기 Baseline으로 사용한다.
- API 탐색·수집 Agent의 LLM Node는 최소 API 호출 전략과 Source·Page·상세 조회 예산을 제안하고, 같은 Subgraph의 결정적 Read Node가 검증된 Query·MCP Read를 수행해 `AcquisitionResult`까지 반환한다.
- Context Retriever Agent는 수집된 데이터에서 필요한 Segment·Evidence만 선별하고 MCP를 직접 호출하지 않는다.
- 일반 Retrieval 호출은 Domain Action Row를 만들지 않는다.
- Answer-only Run, READ-only Plan, READ 실패와 Write Retry는 04·06의 Domain 계약을 따른다.
- 승인 이후 LLM이 Tool·Arguments·대상 Resource를 변경할 수 없다.


## 22. r4 구현 전제

- `command_id`는 Trace 전용 값이 아니라 영속 Command Receipt의 식별자다.
- OAuth 시작·Callback·Token 교환·Refresh Token 저장은 MCP Credential Provider가 소유한다.
- FastAPI는 Token 원문이 아닌 계정·Scope·연결 상태 Metadata만 취급한다.
- 대화 이름 변경과 대화 삭제는 P1이며 P0 API·UI 범위에서 제외한다.

## 승인형 Write·Clarification 계약
- Gmail 실제 전송은 승인 필수 `SEND` Effect로 지원한다.
- 정확한 Task 완료 상태 변경은 승인 필수 `UPDATE`다.
- 정확한 Google Task 삭제와 Calendar Event 삭제는 승인 필수 `DELETE`다.
- Calendar 참석자 추가·수정은 승인 필수 `UPDATE`다.
- 사용자가 중복 사실을 인지하고 동일 Resource 추가 생성을 명시적으로 요구한 경우 재확인·승인 후 허용할 수 있다.
- 모호성은 차단이 아니라 `NEEDS_CONFIRMATION → clarify → same Run/Thread resume`를 기본으로 한다.
- 전체 Gmail Mailbox·장기간 무제한 원문·모든 Workspace Source 전체 조회는 데이터 최소화 정책에 따라 BLOCK한다.

## Claim V2·Gmail 첨부파일 범위

### 제품 범위 추가
- Gmail Message 상세에서 첨부파일 Metadata를 확인하고 사용자가 선택한 첨부파일을 다운로드할 수 있어야 한다.
- Gmail Draft 생성·수정 및 Gmail SEND에서 사용자가 선택한 로컬 파일을 첨부할 수 있어야 한다.
- P0는 첨부파일의 **전달·다운로드**를 지원하며 첨부파일 내용을 LLM이 읽거나 요약·분석하는 기능은 범위에 포함하지 않는다.

### Write 무결성 완료 조건
- 승인된 Business Arguments는 `approval_arguments_hash`로 고정한다.
- Application이 서버 생성 실행 Metadata까지 포함한 실제 MCP Dispatch Payload를 `execution_arguments_hash`로 고정한다.
- MCP Write는 `ClaimContextV2`의 서명·TTL·Process Instance·Action·Approval·Attempt·Tool·두 Hash·Nonce를 검증한 뒤 실제 수신 인자를 재해시하여 `execution_arguments_hash`와 일치할 때만 수행한다.
- 첨부파일이 포함된 Write는 승인 Snapshot에 raw bytes나 Local Path 대신 파일 Descriptor와 SHA-256을 고정하고 실제 bytes를 실행 직전에 재검증한다.
