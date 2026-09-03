# 01-A. 기능 정의서

> **Authority:** 사용자 기능 동작. 제품 범위는 `01 PRD`, 정책은 `01-B`, 전문 runtime/domain/repository 의미는 `00 Project Source Guide`의 Concern Owner를 따른다.  
> **상태:** Draft v2.21 · **기준일:** 2026-09-03

## 1. 문서 목적

이 문서는 사용자가 사용할 수 있는 기능과 시스템 내부 기능을 식별 가능한 단위로 정의한다. 각 기능은 기능 ID, 사용자 목적, 선행 조건, 입력, 처리, 출력, 예외, 완료 조건을 가진다.

### 1.1 Functional authority 경계

`01-A`는 **어떤 사용자/제품 기능이 존재해야 하는가**와 기능별 선행 조건·입력·처리·출력·예외·완료 조건을 소유한다. Detailed Concern ownership은 `00 Project Source Guide`를 그대로 소비하며 여기서 owner 목록을 다시 유지하지 않는다.

기능 추적은 `FUNCTIONAL REQUIREMENT → applicable CONCERN OWNER CONTRACT → REPOSITORY MAPPING`으로 연결한다. Runtime operation·PromptRef·Domain transition·repository symbol을 언급할 수는 있지만 정의 authority는 각각의 owner에 남는다. 따라서 downstream identifier의 이름이나 세부 semantics가 바뀌어도 해당 기능의 사용자 의미가 변하지 않았다면 이 문서를 기계적으로 동시 수정하지 않는다.

## 2. 기능 상태

| 상태 | 의미 |
| --- | --- |
| P0 | MVP 필수 |
| P1 | P0 안정화 후 추가 |
| EXP | 제품 기본값 채택 전 평가 Gate가 필요한 구성 후보 (`13`이 평가·채택 근거를 소유) |
| OUT | 제품 범위 제외 |

## 3. 기능 목록 요약

| 영역 | 기능 |
| --- | --- |
| 설정 | 첫 실행, Google 로그인, OAuth 환경, Runtime 진단, 배포 프로필, 기본 Resource 선택 |
| 요청 | 자연어 입력, 범위 지정, 실행 취소, Run 재개 |
| Context | Retrieval Source 범위 확정, 검색, 정규화, Evidence, 재검색, Gmail 첨부파일 Metadata 조회·사용자 요청 시 다운로드 |
| 분석 | 관계 연결, 중복, 충돌, 업무 가능성 |
| 계획 | Action Plan, DAG, Draft 생성, 위험 표시 |
| 승인 | 전체·부분 승인, 수정, 거절, 승인 만료 |
| 실행 | MCP Tool 호출, Idempotency, 부분 실행, Gmail Draft·Send 첨부파일 전달 |
| 검증 | Connector Verification Read, 필드 비교, Recovery |
| 관측 | Trace, Audit, 오류 진단 |

## 4. 초기 설정·Local Runtime 기능

### FN-001 첫 실행 Wizard

- **상태:** P0
- **사용자 목적:** 앱을 실행 가능한 상태로 만든다.
- **선행 조건:** 앱 최초 실행 또는 설정 초기화.
- **입력:** Google 로그인 선택, API Key 저장 방식, 기본 Calendar, 기본 Task List.
- **처리:** 환경 진단 → Google 로그인 → Runtime 선택 → 기본 Resource 저장 → 연결 테스트.
- **출력:** 설정 완료 상태, OAuth 환경, Runtime·배포 프로필 진단 결과.
- **예외:** OAuth 실패, Scope 동의 거절, API Key 검증 실패, Local Runtime 미설치.
- **완료 조건:** 사용자가 테스트 조회를 성공하고 요청 화면으로 이동한다.

### FN-002 Google 계정 연결

- **상태:** P0
- **사용자 목적:** 별도 OAuth Client 파일 입력 없이 Google 계정을 연결한다.
- **입력:** `Google로 로그인` 사용자 행동, Google 계정 선택, 필요한 Scope 동의.
- **처리:** 제품이 승인된 OAuth 설정과 안전한 Credential boundary를 사용해 Google 연결을 수행하고, UI/Core에는 계정·연결 서비스·승인 Scope·연결 상태 같은 bounded metadata만 제공한다. OAuth Secret/Token 원문은 UI/API/SQLite가 소유하지 않는다.
- **예외:** 동의 취소, 필수 Scope 일부 거절, 허용되지 않은 테스트/운영 계정 상태, Credential 갱신 실패.
- **Scope 규칙:** P0 필수 Scope 하나라도 거절되면 연결을 완료 처리하지 않고 Google Workspace 기능 실행을 차단한다.
- **완료 조건:** 모든 P0 필수 Scope가 승인되고 Gmail·Tasks·Calendar 최소 연결 확인이 성공한다.
- **Security/Interface authority reference:** exact OAuth flow, PKCE/state/loopback, Token exchange/storage, `OAuthCredentialPort`/MCP Credential Provider wire contract는 `07 Interface`와 `09 Security`가 소유한다.
- **Infrastructure authority reference:** OAuth client/environment/runtime setup은 `10 Infrastructure`가 소유한다.
- **Repository mapping reference:** credential connection Port/Adapter/use-case placement·naming은 `16 Repository Architecture`가 소유한다.

### FN-003 Google 계정 연결 해제

- **상태:** P0
- **기능:** 사용자가 현재 Google 계정 연결을 해제하면 저장된 Credential 권위가 제거되고 제품의 활성 계정 상태가 초기화되어야 한다.
- **출력:** 다시 Google 기능을 사용하려면 새 연결/재인증이 필요한 상태.
- **완료 조건:** 해제된 Credential로 이후 Google Workspace 접근을 승인할 수 없다.
- **Security/Interface authority reference:** exact Credential revocation/deletion과 Keyring boundary는 `07 Interface`와 `09 Security`가 소유한다.
- **Operational authority reference:** Google connection/disconnect 자체는 Domain lifecycle이 아니라 `07 Interface`의 non-Domain `OperationalCommandReplayPort + OAuthCredentialPort` 경계와 `09 Security`의 Credential/Keyring 규칙이 소유한다. `04 Domain · DB` + State Transition Contract는 해당 Credential 상태 때문에 Run이 `REAUTH_REQUIRED`로 들어가거나 복귀하는 Run lifecycle만 소유하며 connection row/state를 별도 Domain Aggregate로 발명하지 않는다.
- **Repository mapping reference:** disconnect/revoke Port·Adapter/use-case placement·naming은 `16 Repository Architecture`가 소유한다.

### FN-004 LLM Runtime 진단

- **상태:** P0
- **입력:** 하드웨어, Ollama 상태, 설치 모델, API Key.
- **처리:** CPU-only 여부, GPU 기준 충족, Ollama 연결, Local 테스트 추론, API 연결을 확인한다.
- **출력:** 사용 가능한 모드, 배포 프로필, 고정된 실행 모드.
- **규칙:** CPU-only 또는 GPU 기준 미달은 API_LLM 고정. Local 제품 Runtime은 Ollama만 지원한다. `LOCAL_CAPABLE` 최초 설정은 Release-approved Ollama와 Signed Local Model Profile을 자동 준비하고, 이후 실행은 Version·모델 digest·Structured Output 상태를 다시 검증한다. Ollama는 별도 Process로 유지하며 제품 종료 시 공유 Runtime을 강제 종료하지 않는다.

### FN-005 LLM 모드 선택

- **상태:** P0
- **선행 조건:** Runtime 진단 완료.
- **처리:** API_ONLY에서는 API_LLM만 표시한다. LOCAL_CAPABLE과 검증된 GPU에서는 AUTO, LOCAL_GPU, API_LLM을 표시한다.
- **출력:** 사용자 선택 모드와 실제 실행 모드.
- **완료 조건:** P0에서 API와 Local 모드를 모두 사용할 수 있다.
- **Runtime authority reference:** `POST /api/v1/runtime/mode`의 process-local mutable requested-mode authority는 `07 Interface`의 `RuntimeModePort`, runtime/deployment semantics는 `10 Infrastructure`, concrete placement는 `16 Repository Architecture`가 소유한다. 이 operational mode는 persisted Settings `preferred_llm_mode`나 이미 시작된 Run의 immutable `requested_mode`를 바꾸지 않는다.

### FN-006 배포 프로필 선택

- **상태:** P0 배포 기능
- **프로필:** `API_ONLY`, `LOCAL_CAPABLE`.
- **API_ONLY:** Ollama 의존성 없이 실행하며 GPU가 없는 팀원과 CPU-only 사용자에게 제공한다.
- **LOCAL_CAPABLE:** Local Runtime 진단과 자동 provisioning UI를 제공한다. Windows Installer 본체에는 Ollama 실행 파일·모델 weight·실험 Runner·미승인 후보를 포함하지 않지만, 최초 설정에서 verified Artifact를 다운로드·설치·검증해 사용자가 별도 터미널 작업 없이 Local Runtime을 사용할 수 있게 한다.
- **완료 조건:** 동일 제품 Core/Policy 의미를 유지하면서 배포 Artifact 의존성과 Runtime capability가 프로필별로 분리된다.
- **Infrastructure authority reference:** profile별 bundle/dependency/runtime composition은 `10 Infrastructure`가 소유한다.
- **Repository mapping reference:** Local runtime adapter/diagnostic placement·naming은 `16 Repository Architecture`가 소유한다.

### FN-006A Local Runtime 자동 준비

- **상태:** P0 배포 기능
- **사용자 목적:** Ollama와 제품 Local Model을 직접 설치하지 않고 `LOCAL_CAPABLE` 제품을 사용할 수 있게 한다.
- **입력:** `로컬 AI 준비` 사용자 행동 또는 최초 설정의 자동 시작, 현재 Hardware/디스크/네트워크 진단 결과.
- **처리:** 기존 호환 Ollama 탐지 → Release-approved Ollama Artifact 필요 시 설치 → Signed Local Model Profile의 model artifact 다운로드 → digest/identity 검증 → tier별 Structured Output Smoke Test → Runtime readiness 반영.
- **출력:** 단계별 진행률, 남은 용량, 현재 준비 항목, 재시도 가능한 typed 오류, 최종 `READY | API_ONLY_FALLBACK | REPAIR_REQUIRED` 상태.
- **규칙:** Browser·LLM이 URL·installer path·model name을 제출하지 않는다. `OperationalCommandReplayPort`와 provisioning Port가 crash-safe operation identity를 유지한다.
- **모델 Profile:** Product LLM caller는 `WORKER | REASONING` tier만 요청한다. 초기 후보는 `WORKER=qwen3.5:4b`, `REASONING=qwen3.5:9b`이며 13 Evaluation과 signed Release activation 전에는 제품 기본값으로 확정하지 않는다.
- **완료 조건:** 사용자가 CLI를 실행하지 않고 승인된 Runtime과 모델이 검증되어 `LOCAL_GPU`가 선택 가능하거나, 실패 원인과 API 대체 경로가 안전하게 표시된다.

### FN-007 OAuth 배포 환경 관리

- **상태:** P0 개발·운영 기능
- **처리:** 개발·스테이징·운영 Google Cloud 프로젝트와 OAuth Client를 분리한다.
- **팀 테스트:** Test User 등록, External + Testing Refresh Token 7일 만료 재로그인 안내.
- **운영:** 검증된 OAuth Client와 동의 화면만 사용한다.

### FN-008 Local Agent Service 시작

- **상태:** P0
- **사용자 목적:** 별도 개발 명령이나 서버 설정 없이 앱을 실행한다.
- **입력:** Launcher 실행.
- **처리:** 로컬 서비스 실행에 필요한 loopback binding, 제품 Asset/API/DB/Migration/Domain/Connector/Credential readiness를 확인하고, 사용 가능한 경우 같은 로컬 Origin에서 UI를 열어 Runtime 연결 상태와 진단을 제공한다.
- **출력:** Local Service 사용 가능 상태, UI 진입 정보, 진단 결과.
- **예외:** local binding 실패, Service 시작 실패, DB Safe Mode, 필수 Asset/contract/readiness 실패.
- **완료 조건:** 사용자가 별도 서버 설정 없이 인증된 same-origin UI/API 제품 경계를 사용할 수 있다.
- **Infrastructure authority reference:** process startup, port selection, concrete health/readiness checks와 deployment composition은 `10 Infrastructure`가 소유한다.
- **Interface/Security authority reference:** exact health/runtime endpoints, Local Session, Host/Origin contract는 `07 Interface`와 `09 Security`가 소유한다.
- **Repository mapping reference:** launcher/service/readiness component placement·naming은 `16 Repository Architecture`가 소유한다.

### FN-009 Frontend·API 세션과 버전 확인

- **상태:** P0
- **기능:** 로컬 UI는 현재 Local Service와 안전하게 인증된 세션을 수립하고 Frontend/API 계약이 호환되는지 확인한 뒤에만 상태 변경 요청과 진행 Event 기능을 사용할 수 있어야 한다.
- **예외:** bootstrap/session 검증 실패, 허용되지 않은 Origin/Host, Frontend/API 계약 비호환.
- **완료 조건:** 인증되지 않았거나 호환되지 않는 UI가 상태 변경 기능이나 보호된 Event Stream을 사용할 수 없다.
- **Interface/Security authority reference:** exact bootstrap secret, Local Session, Host/Origin, version negotiation과 REST/SSE access contract는 `07 Interface`와 `09 Security`가 소유한다.
- **Infrastructure authority reference:** build/runtime compatibility packaging은 `10 Infrastructure`가 소유한다.
- **Repository mapping reference:** session/version-check component placement·naming은 `16 Repository Architecture`가 소유한다.

## 5. 요청 기능

### FN-010 자연어 요청 입력

- **상태:** P0
- **입력:** 한국어 또는 영어 자연어, 선택적 Query·기간·사람·이메일·Keyword, 이번 요청에서 명시적으로 선택한 Gmail·Task·Event Resource.
- **처리:** Resource를 먼저 선택하지 않은 Agent 검색형 요청과, 사용자가 Resource를 명시적으로 선택한 요청을 모두 시작할 수 있어야 하며 각각 새 current-run 처리 단위로 시작한다.
- **출력:** 요청 진입 유형, 처리 단계, 현재 Source, 진행 상태.
- **예외:** Runtime 미설정, 필요한 Connector 연결 없음.
- **완료 조건:** 같은 Conversation에는 여러 USER 요청과 대응 Run이 순차적으로 존재할 수 있지만 동시에 Active Run이 둘 이상 생기지 않는다. 새 사용자 요청은 이전 Run의 Message·Agent Artifact·Evidence·Plan·Confirmation·Checkpoint를 숨은 업무 Context로 자동 승계하지 않고, 사용자가 이번 요청에서 명시적으로 선택한 Resource만 Entry Context로 사용할 수 있다.
- **Runtime authority reference:** exact RunInput/thread/checkpoint artifact와 Agent-search/resource-selected entry identifiers, one-open-run routing semantics는 `06 Agent · Workflow`가 소유한다.
- **Domain authority reference:** Run 생성·active/terminal lifecycle과 Conversation-Run 불변조건은 `04 Domain · DB` + State Transition Contract가 소유한다.
- **Interface authority reference:** StartRun request/response wire contract는 `07 Interface`가 소유한다.
- **Repository mapping reference:** run/start-request use-case path·symbol naming은 `16 Repository Architecture`가 소유한다.

### FN-011 요청 범위 제한

- **상태:** P0
- **입력:** 기간, Source 선택, 특정 Resource.
- **처리:** 사용자가 지정한 범위를 검색 계획의 상한으로 적용한다.
- **완료 조건:** 범위 밖 자료가 필요하면 조회 전에 추가 Source·기간과 이유를 제안하고 사용자 확인을 받는다. 사용자 확인 없이 지정 범위를 확대하지 않는다.

### FN-012 실행 취소

- **상태:** P0
- **기능:** 사용자는 진행 중 Run의 아직 시작되지 않은 작업을 취소할 수 있어야 하며, 이미 완료된 외부 Write를 가짜 rollback하지 않아야 한다.
- **처리:** 중단 가능한 읽기/LLM 작업은 더 진행하지 않고, 외부 Write가 이미 dispatch되었거나 결과가 불명확하면 같은 Write를 재전송하지 않은 채 실제 외부 결과를 Verification/Recovery로 먼저 확정한 뒤 취소를 마무리한다.
- **출력:** 취소된 범위, 이미 완료된 Action, 아직 결과 확인이 필요한 Action을 구분한 결과.
- **완료 조건:** 취소 요청 이후 새 외부 Write가 임의로 시작되지 않고, in-flight Write 사실이 CANCELLED로 덮어써지지 않는다.
- **Domain authority reference:** cancel intent/status/Command/Guard/finalization transition은 `04 Domain · DB` + State Transition Contract가 소유한다.
- **Runtime authority reference:** interruptible 단계 중단, in-flight Verification/Recovery와 cancel routing은 `06 Agent · Workflow`가 소유한다.
- **Repository mapping reference:** cancel operation placement·naming은 `16 Repository Architecture`가 소유한다.

### FN-013 Run 재개

- **상태:** P0
- **기능:** 확인 질문·재인증·복구·일시 중단 등으로 멈춘 현재 비Terminal Run은 보존된 안전 진행 상태에서 이어서 처리할 수 있어야 한다.
- **처리:** 재개 전에 이미 승인·실행·완료된 Action 사실을 조정해 중복 실행을 막고, Terminal이 된 이전 Run은 새 사용자 요청의 숨은 Context나 resume 대상으로 사용하지 않는다.
- **완료 조건:** same-run resume와 new-run start가 구분되고, 재개 때문에 완료 Action이나 승인된 Effect가 중복 적용되지 않는다.
- **Domain authority reference:** resumable/terminal 상태와 durable checkpoint facts/Command/transition은 `04 Domain · DB` + State Transition Contract가 소유한다.
- **Runtime authority reference:** thread/checkpoint/resume target/phase semantics는 `06 Agent · Workflow`가 소유한다.
- **Repository mapping reference:** resume/checkpoint operation placement·naming은 `16 Repository Architecture`가 소유한다.

### FN-014 사이드바 목록 조회

- **상태:** P0
- **사용자 목적:** Gmail·Tasks·Calendar의 현재 항목을 목록으로 탐색한다.
- **입력:** Source, 검색·필터·정렬 조건, opaque Local API continuation token.
- **공통:** Gmail·Tasks의 UI 표시 단위는 configured `SIDEBAR_PAGE_SIZE`이며 Agent Retrieval의 configured `RETRIEVAL_PAGE_SIZE`와 별도다. Local API `next_page_token`은 Frontend가 해석하지 않고 다음 요청에 그대로 전달하며 Provider Page Token이나 UI page number로 간주하지 않는다.
- **Gmail:** 기본 Sidebar 범위는 `INBOX + PRIMARY` Thread이며 최근 수신 순이다. Browse visible page 크기는 configured `SIDEBAR_PAGE_SIZE`를 사용하고, 아직 방문하지 않은 intermediate page는 ID·다음 continuation만 얻고 visible target page에서만 Sidebar metadata를 hydrate할 수 있다. 검색은 Primary 제한을 해제해 일반 mailbox를 검색하되 Spam·Trash는 제외하고 기본 badge count는 유지한다.
- **Tasks:** configured/default Task List의 미완료 전체를 기본 범위로 하고 `show_completed=false`, `show_hidden=false`, `show_deleted=false`를 사용한다. Provider metadata batch는 Provider 허용 범위 안에서 React Client Session Cache에 누적하고 UI는 configured `SIDEBAR_PAGE_SIZE`로 slice한다. continuation이 있으면 현재 materialized batch에서 계산되는 page 범위만 알고, 알려진 마지막 page를 요청할 때만 다음 batch를 append한다. 기본 정렬은 Provider 반환 순이며 사용자가 `날짜순`을 명시한 경우에만 전체 결과를 materialize해 `scheduled_date` 오름차순·날짜 없음 후순위로 정렬한다. 목록 행은 list metadata를 사용하고 detail Read는 focus/선택 때만 수행한다.
- **Tasks 완료 영역:** 미완료 목록과 별개로 `완료됨(N)` section을 제공한다. completed scope는 `show_completed=true`, `show_hidden=true`, `show_deleted=false`로 terminal까지 background materialize하고 실제 `task_status=completed`만 `resource_id` 기준 dedupe한다. `N`은 exact completed count이며 section 펼침/`더 보기`는 이미 받은 cache를 configured `SIDEBAR_PAGE_SIZE` 단위로 보여줄 뿐 Provider Read를 추가하지 않는다. Provider `completed` timestamp는 유효할 때만 `completed_at`으로 보존해 완료일 표시의 근거로 사용한다.
- **Calendar:** Sidebar는 Month View를 기본으로 하고 선택 월의 Sunday-start 실제 5/6주 visible grid `[gridStart, gridEnd)` Event instance를 `singleEvents=true`로 terminal까지 materialize한다. UI numeric pagination과 Calendar numeric badge는 사용하지 않는다. time range가 생략된 일반 Upcoming Browse는 configured user timezone 기준 현재부터 90일 기본 window를 유지한다.
- **Count:** Gmail badge는 기본 `INBOX + PRIMARY` Thread의 exact total만 표시한다. Tasks badge는 첫 incomplete batch가 terminal이면 exact 수, continuation이 있으면 확인된 최소 수에 `+`를 붙이고 terminal 도달 뒤 exact total을 확정한다. Calendar tab에는 numeric badge를 표시하지 않는다. partial·estimate·loaded/visible count를 exact total처럼 표시하지 않는다.
- **완료 조건:** 사용자가 Google 원본 전체를 SQLite에 저장하지 않고 최신 목록을 탐색하며, 이미 받은 page/batch는 세션 범위에서 재사용할 수 있다.

### FN-015 Frontend 페이지 메모리 캐시

- **상태:** P0
- **기능:** 같은 UI 세션에서 이미 조회한 Sidebar 목록/page/batch/month를 불필요하게 다시 외부 조회하지 않고 재사용할 수 있어야 한다.
- **폐기:** 계정·Source container·검색/filter/sort/scope 변경, 명시적 새로고침, UI 세션 종료처럼 결과 의미가 바뀌는 조건에서는 관련 cache를 폐기해야 한다.
- **제한:** UI cache는 승인·중복·충돌·검증의 제품 사실 기준점이 아니며 Secret/OAuth/Local Session 원문을 cache identity로 저장하지 않는다. 장기 Semantic Memory나 Source 원본 복제 저장소로 승격하지 않는다.
- **완료 조건:** 동일 UI 범위 재탐색은 이미 받은 결과를 재사용하면서도 scope/account 변경 뒤 stale 목록을 재사용하지 않는다.
- **UI authority reference:** exact cache key/generation/page presentation와 invalidation interaction은 `02 UI · UX`가 소유한다.
- **Interface authority reference:** opaque continuation/batch semantics는 `07 Interface`가 소유한다.
- **Repository mapping reference:** frontend cache implementation placement·naming은 `16 Repository Architecture`가 소유한다.

### FN-016 사용자 선택형 요청

- **상태:** P0
- **입력:** Sidebar에서 사용자가 명시적으로 선택한 하나 이상의 Gmail·Task·Event Resource와 자연어 요청 또는 빠른 Action.
- **기능:** 선택된 Resource를 이번 Run의 명시적 Entry Context로 사용하고 최신 상세를 확인해 사용자가 사람·날짜·제목을 다시 입력하지 않아도 요청을 수행할 수 있어야 한다.
- **처리:** 선택 범위 밖 Source/Connector가 필요하면 이 기능이 임의 확장하지 않고 route/scope 재검토 기능으로 넘기며, 사용자 지정 범위를 넘는 확장은 확인을 요구한다. 선택 Resource에 연결된 과거 Run Evidence/Approval을 새 Run으로 자동 승계하지 않는다.
- **출력:** 선택 Resource 기반 current-run Context와 요청 결과/Action Plan.
- **Runtime authority reference:** exact Entry Context projection, route reconsideration/scope-expansion semantics는 `06 Agent · Workflow`가 소유한다.
- **Retrieval/Interface authority reference:** latest-detail Read와 Connector operation은 `05 Retrieval`과 `07 Interface`가 소유한다.
- **Repository mapping reference:** selected-resource request mapping은 `16 Repository Architecture`가 소유한다.

### FN-017 Agent 검색형 요청

- **상태:** P0
- **입력:** Query, 날짜·기간, 사람·이메일, Keyword 또는 복합 자연어 요구사항.
- **기능:** 사용자가 Resource를 먼저 선택하지 않아도 현재 요청 의미에 필요한 Source 범위를 정하고, Source-native 검색/조회로 후보를 줄여 필요한 상세와 Evidence만 사용해 요청을 수행할 수 있어야 한다.
- **제한:** 이 기능이 이미 확정된 Source/Tool 범위를 downstream에서 재선택하지 않고, LLM이 Provider-native Query·raw continuation·MCP arguments를 직접 실행하지 않으며, 검색 결과 전체를 무제한 LLM Context로 전달하지 않는다.
- **출력:** 검색 근거와 관련 Resource, 분석 결과 또는 Action Plan.
- **완료 조건:** 직접 Resource 선택 없이도 요청 조건에 맞는 자료를 bounded하게 찾을 수 있고, 범위 확대가 필요하면 사용자/route 재검토 경계를 따른다.
- **Runtime/Retrieval authority reference:** Request Understanding·Tool Route·Retrieval의 exact artifact/operation/constraint planning은 `05 Retrieval`과 `06 Agent · Workflow`가 소유한다.
- **Interface authority reference:** Connector-native query/continuation/read contract는 `07 Interface`가 소유한다.
- **Repository mapping reference:** agent-search operation mapping은 `16 Repository Architecture`가 소유한다.

### FN-018 Run 진행 Event 구독·복구

- **상태:** P0
- **기능:** UI는 현재 Run의 진행·질문·계획·실행·검증 상태 변화를 실시간 또는 재연결 가능한 방식으로 받아 사용자에게 반영할 수 있어야 한다.
- **예외:** Event 연결 단절, 재개 지점 만료, Local Session 만료, Service 재시작.
- **처리:** 연결이 끊겨도 서버의 현재 Run 상태/Projection을 다시 받아 화면을 복원하며 Client가 승인·실행·검증 사실을 추측해 만들지 않는다.
- **완료 조건:** 브라우저 새로고침이나 일시적 연결 단절 뒤에도 사용자 화면이 서버의 최신 제품 사실과 다시 일치한다.
- **Interface/Security authority reference:** exact SSE event envelope/cursor/replay/snapshot/session contract는 `07 Interface`와 `09 Security`가 소유한다.
- **UI authority reference:** Event rendering/reconnect interaction은 `02 UI · UX`가 소유한다.
- **Repository mapping reference:** event-stream operation placement·naming은 `16 Repository Architecture`가 소유한다.

### Resource Browser·Sidebar 공통 요구

이 절은 FN-014~FN-018의 사용자 기능을 보조하는 Functional 요구만 정리한다. **구체 UI layout·row/card 표현·페이지 control·Empty State 문구는 `02 UI·UX`, Local API continuation·Connector operation 계약은 `07 Interface`, repository naming은 `16 Repository Architecture`가 소유한다.**

- 사용자는 Gmail·Tasks·Calendar 목록을 탐색하고, 이미 조회한 세션 범위 결과를 재사용하며, 명시적 새로고침·scope/account/container 변경 시 관련 cache를 폐기할 수 있어야 한다.
- 목록 탐색은 Provider continuation을 사용자에게 노출하거나 Frontend가 해석하지 않는 opaque continuation 경계를 가져야 하며, 정확한 source별 page/batch/window 규칙은 FN-014와 02/07의 current contract를 따른다.
- Focus Resource와 Agent 요청에 명시적으로 선택한 Resource 집합은 기능적으로 구분되어야 하며, Focus 변경이 선택 Context를 암묵적으로 바꾸지 않아야 한다.
- `RESOURCE_SELECTED` 진입은 선택 Resource를 current-run Entry Context로 보존하고 최신 상세를 조회한다. 추가 Source/Tool 범위가 필요하면 FN-102에 연결된 runtime route 경계를 통해 재판단하며 사용자 지정 범위를 자동 확장하지 않는다.
- Quick Action은 선택 Resource + 사용자 의도를 Agent 요청으로 제출하는 진입 기능일 뿐 외부 Write를 직접 실행하지 않는다.
- Conversation 선택은 저장 Timeline을 복원하는 기능이며 새 Run의 implicit semantic memory를 만들지 않는다.
- Frontend는 서버가 제공한 projection을 표시하며 실행·승인·검증 사실이나 숨은 count/history를 추정해 만들지 않는다.


### Tasks·Calendar Sidebar/Viewer 공통 요구

이 절은 Source별 사용자 기능 의미만 정의한다. **구체 row 순서·날짜 포맷·label·색상·Empty State 문구·선택 styling은 `02 UI·UX`, Connector operation 이름과 request field는 `07 Interface`, repository operation/path/symbol은 `16 Repository Architecture`가 소유한다.**

- Tasks Sidebar/Viewer는 실제 Task의 제목·메모·`scheduled_date`·Task List·완료 상태를 사용자에게 탐색 가능한 형태로 제공해야 하며, Provider 내부 ID·continuation 같은 구현 세부를 사용자 의미로 노출하거나 임의 priority/category를 생성하지 않는다.
- Calendar Sidebar/Viewer는 Event 제목·시간 범위·all-day 여부·Calendar Context를 사용자에게 식별 가능하게 제공해야 하며, 사용자 지정 기간이 있으면 그 범위를 우선하고 일반 Upcoming 조회 범위는 FN-014/07의 current functional/interface contract와 일치해야 한다.
- Source 전환과 Focus 변경은 다른 Source의 상세나 Agent 선택 Context를 암묵적으로 유지·혼합하지 않아야 한다.
- Task 날짜·상태 의미는 아래 `Google Tasks 날짜·상태 의미`를, 구체 UI 표현은 `02 UI·UX`를 따른다.


### Google Tasks 날짜·상태 의미

#### 예정일과 업무 마감

- `scheduled_date`는 사용자가 Task를 수행할 예정인 날짜다. Google Tasks API Adapter의 `due`와 대응하며 READ/WRITE 가능하다. 시간 정보를 생성·추론하지 않는다.
- `business_deadline`은 업무 자체가 완료되어야 하는 실제 마감이다. Gmail 본문, 사용자 요청, Evidence에서 인식할 수 있으나 Google Tasks API의 `due`와 동일시하지 않는다.
- 업무 마감만 있는 요청은 `scheduled_date`를 만들거나 Google `due`를 채우지 않는다. 필요한 경우 `notes`에 `업무 마감: YYYY년 M월 D일`처럼 의미를 보존하고 Evidence·Approval Summary에도 근거를 남긴다.
- 수행 예정일과 업무 마감이 모두 명시되면 각각 보존한다. 예를 들어 11일 수행·12일 제출은 `scheduled_date=11일`, `business_deadline=12일`이며 Google `due`에는 11일만 사용한다.
- 시간대가 지정된 Task 요청은 현재 Google Tasks API가 정확한 시간 구간을 구조화해 설정했다고 성공 처리하지 않는다. 날짜 예정일만 제안하거나, 정확한 시간 예약이 필요하면 승인형 Calendar Event 대안을 사용자에게 제시한다. 사용자 동의 없이 Event를 추가하지 않는다.

#### 상태와 사용자 Projection

- Provider raw `needsAction`은 제품 상태 `NEEDS_ACTION`, UI 문구 `미완료`로 정규화한다. raw `completed`는 `COMPLETED`, UI 문구 `완료`로 정규화한다.
- 예정일 경과는 상태 전이가 아니다. `scheduled_date`가 지났고 상태가 미완료이면 UI 보조 문구 `예정일 지남`만 사용할 수 있으며, `기한 초과`·`마감 초과` 또는 자동 완료로 표현하지 않는다.
- 완료는 Google Task 실제 status가 `completed`일 때만 표시한다. Provider가 완료 날짜를 제공하면 사용자 친화적인 `완료일`로 표시할 수 있다.
- 목록·상세에는 raw enum, RFC3339 raw `due`, 내부 `due` 필드명, API에 없는 작업 시간·업무 마감을 표시하지 않는다. React는 사용자용 Local API Projection을 소비하며 Provider 의미의 최종 정규화를 담당하지 않는다.

## 6. Context·Retrieval 기능

### FN-020 Retrieval Source 범위 확정

- **상태:** P0
- **입력:** `RequestIntent`, 요청 진입 방식, 이번 Run에 명시적으로 선택된 Resource, FN-011 사용자 범위 제약.
- **처리:** 현재 Run의 Retrieval이 사용할 Connector·Resource·Read capability 범위는 Retrieval 시작 전에 확정되어야 한다. `RESOURCE_SELECTED`에서는 사용자가 이번 Run에 명시적으로 선택한 Resource/Source를 Entry Context로 보존하고, `AGENT_SEARCH`에서는 요청 수행에 필요한 범위만 사용한다. 추가 Source가 사용자 지정 범위를 벗어나면 사용자 확인 없이 자동 확장하지 않는다.
- **출력:** downstream Retrieval이 재선택 없이 소비할 수 있는 frozen input-route 범위.
- **Runtime authority reference:** 정확한 Tool Route artifact·route-selection semantics·scope-expansion disposition은 `06 Agent · Workflow`와 `07 Interface`가 소유한다. FN-102는 이 기능 요구와 runtime Tool Route capability를 연결하는 Functional reference다.
- **Repository mapping reference:** canonical `tool_routing.*` repository operation/path/symbol mapping은 `16 Repository Architecture`가 소유한다.
- **예외:** 선택된 Resource를 근거 없이 재검색해 대체하거나, 모든 Source를 기본 선택하거나, Retrieval이 Source/Tool을 재선택하지 않는다.
- **완료 조건:** Retrieval은 확정된 IN Route만 read-only로 소비한다.

### FN-021 Gmail 검색·조회

- **상태:** P0
- **입력:** current-run에 확정된 Gmail Read 범위, 사용자/요청의 의미 제약, 또는 이번 Run에서 검증된 Gmail Resource reference.
- **처리:** Gmail의 Source-native 검색/조회로 필요한 Thread·Message 후보와 상세만 가져오고, 업무 분석에 사용할 수 있도록 HTML·인용·서명 등 비업무 요소를 정리한 뒤 정규화된 Context/Evidence 후보를 만든다. LLM이 raw Provider query·continuation·API arguments를 직접 작성하거나 실행하지 않는다.
- **출력:** 현재 Run에 귀속된 정규화 Gmail Context와 Evidence 후보.
- **Retrieval/Interface authority reference:** exact route schema, query planning/builder, pagination/continuation, Connector MCP Read와 normalization pipeline은 `05 Retrieval`, `06 Agent · Workflow`, `07 Interface`가 소유한다.
- **Repository mapping reference:** Gmail/retrieval operation path·file·symbol naming은 `16 Repository Architecture`가 소유한다.

### FN-021A Gmail 첨부파일 조회·다운로드

- **상태:** P0
- **사용자 목적:** Gmail Message의 첨부파일 Metadata를 확인하고, 명시적으로 선택한 원본 파일을 다운로드할 수 있다.
- **처리:** Message 상세에서 사용자가 식별할 수 있는 파일명·MIME Type·크기 Metadata를 제공하고, 다운로드 요청 시 해당 첨부파일 원본 bytes만 안전한 Connector/Local API download 경계를 통해 전달한다.
- **출력:** 검증된 파일 Metadata와 사용자 선택 파일의 원본 bytes.
- **제한:** 첨부파일 bytes·내용을 LLM Prompt·Context·Evidence로 전달하지 않는다.
- **완료 조건:** LLM 호출 없이 선택한 파일을 받을 수 있고, 다른 Message/Attachment bytes가 혼동·노출되지 않는다.
- **Interface/Security authority reference:** exact message/attachment identifiers, Attachment Read operation, download stream/schema와 bounded/fail-closed 보안 요구는 `07 Interface`와 `09 Security`가 소유한다. exact numeric byte limit은 architecture/functional contract가 아니라 runtime configuration의 implementation choice다.
- **Repository mapping reference:** Gmail attachment/provider/download implementation placement·naming은 `16 Repository Architecture`가 소유한다.

### FN-022 Tasks 검색·조회

- **상태:** P0
- **입력:** current-run에 확정된 Tasks Read 범위, 상태·예정일·Keyword·Task List 제약, 또는 검증된 Task Resource reference.
- **처리:** 필요한 Task 후보·상세만 Source-native Read로 조회하고 제품의 Task 상태와 `scheduled_date` 의미로 정규화한다. Provider의 raw `due/status`를 실제 업무 마감(`business_deadline`)이나 다른 사용자 의미로 임의 변환하지 않는다.
- **출력:** 현재 Run에 귀속된 정규화 Task Context와 Evidence 후보.
- **Retrieval/Interface authority reference:** exact route/query/Connector arguments·pagination과 provider-to-product normalization contract는 `05 Retrieval`, `07 Interface`가 소유한다.
- **Repository mapping reference:** Tasks/retrieval operation path·file·symbol naming은 `16 Repository Architecture`가 소유한다.

### FN-023 Calendar 조회·FreeBusy

- **상태:** P0
- **입력:** current-run에 확정된 Calendar Read 범위, 기간·Calendar·Resource 제약, 또는 검증된 Calendar/Event Resource reference.
- **처리:** 필요한 Event와 FreeBusy 정보를 Source-native Read로 조회하고, 사용자 Timezone과 정책상 Busy/Tentative/Free 의미를 일관되게 적용해 일정 충돌·가용성 판단에 사용할 수 있는 Context를 만든다. LLM이 Provider-native 시간 표현이나 raw API arguments를 직접 작성·실행하지 않는다.
- **출력:** 현재 Run에 귀속된 Event Context, Busy Interval, 가용 Slot 후보와 Evidence.
- **Policy authority reference:** Busy/Tentative/Free 및 충돌 정책은 `01-B 정책`이 소유한다.
- **Retrieval/Interface authority reference:** exact query/range materialization, Connector Event/FreeBusy Read와 Provider normalization은 `05 Retrieval`과 `07 Interface`가 소유한다.
- **Repository mapping reference:** Calendar/retrieval operation path·file·symbol naming은 `16 Repository Architecture`가 소유한다.

### FN-024 Context 정규화

- **상태:** P0
- **기능:** Gmail·Tasks·Calendar처럼 형태가 다른 Source 결과를 후속 분석/계획이 일관되게 소비할 수 있는 공통 제품 의미로 정규화해야 한다.
- **완료 조건:** Source/Resource identity, 제목·시간·사람·상태, Evidence가 참조할 원본 위치/서비스 navigation 정보가 손실되지 않고, Provider 표현 차이가 제품 의미를 왜곡하지 않는다. Provider가 direct permalink를 제공하지 않는 경우 찾기/search navigation으로 연결할 수 있다.
- **Retrieval/Interface authority reference:** exact WorkItem/Evidence schema, Provider normalization과 source-reference contract는 `05 Retrieval`과 `07 Interface`가 소유한다.
- **Repository mapping reference:** normalization/schema implementation placement·naming은 `16 Repository Architecture`가 소유한다.

### FN-025 Chunking

- **상태:** P0
- **기능:** 긴 Gmail Thread를 LLM/RAG가 bounded하게 처리할 수 있도록 분할하되 Message 경계를 우선하고, 필요할 때만 길이 기준으로 더 나눈다.
- **완료 조건:** 분할 뒤에도 각 Segment가 어느 Message/원본 위치에서 왔는지 추적할 수 있어 Evidence grounding이 깨지지 않는다.
- **Retrieval authority reference:** exact chunk/segment schema, token budget, splitting algorithm과 identity semantics는 `05 Retrieval`이 소유한다.
- **Repository mapping reference:** chunking/segmentation operation placement·naming은 `16 Repository Architecture`가 소유한다.

### FN-026 추가 Retrieval

- **상태:** P0
- **기능:** 현재 Evidence가 부족하면 같은 확정 입력 범위 안에서 새 정보 획득 가능성이 있는 다음 page·추가 detail·검색 조건 조정을 사용해 **최대 2회** 추가 Retrieval할 수 있어야 한다.
- **처리:** 동일 Query/continuation처럼 실질적으로 같은 조회 반복은 새 round로 인정하지 않는다. 새 Source/Connector/Read capability가 필요하면 Retrieval이 범위를 직접 바꾸지 않고 route 재검토 기능으로 넘기며, 사용자 지정 범위를 넘으면 FN-027 확인을 요구한다.
- **출력:** 추가 조회 이유/진행 상태와 새 Evidence 또는 재검토·확인 필요 결과.
- **완료 조건:** bounded budget을 넘지 않고, 추가 Retrieval이 route authority나 사용자 범위를 암묵적으로 확장하지 않는다.
- **Retrieval/Runtime authority reference:** exact query-delta/page/detail planning, round accounting, disposition/signal semantics는 `05 Retrieval`과 `06 Agent · Workflow`가 소유한다.
- **Prompt authority reference:** sufficiency/additional-retrieval Prompt behavior는 `15 Prompt · Failure`가 소유한다.
- **Repository mapping reference:** additional-retrieval operation placement·naming은 `16 Repository Architecture`가 소유한다.

### FN-027 사용자 확인 질문

- **상태:** P0
- **조건:** 동일 이름 후보, 불명확한 기간, 예상 시간 누락, 의미가 다른 후보가 복수인 경우, 또는 FN-011의 사용자 범위를 넓혀야 하는 경우.
- **처리:** 현재 Run을 안전하게 계속하기 위해 꼭 필요한 의미·대상·범위를 사용자가 결정할 수 있도록 최소 질문과 구분 가능한 선택지/차이/이유를 제공한다. 시스템은 사용자의 결정을 임의 추정하지 않으며, 검증된 응답 뒤에는 새 Run을 만들거나 전체 흐름을 무조건 처음부터 반복하지 않고 동일 Run의 적절한 기능 지점에서 계속할 수 있어야 한다.
- **출력:** 사용자에게 필요한 최소 질문/선택지와 검증된 confirmation 결과.
- **완료 조건:** 확인 응답이 해당 모호성·범위 결정에만 사용되고 Approval/Claim 권위로 오용되지 않으며, 이전 Run의 숨은 Context를 가져와 질문을 우회하지 않는다.
- **Runtime authority reference:** exact confirmation disposition, interrupt owner, resume target, checkpoint/back-edge semantics는 `06 Agent · Workflow`가 소유한다.
- **Domain authority reference:** confirmation 관련 Command·Guard·상태 전이·durable receipt/decision 사실은 `04 Domain · DB` + State Transition Contract가 소유한다.
- **Prompt authority reference:** confirmation 질문 생성이 Product Prompt를 사용하는 경우 PromptRef·input projection·failure/repair contract는 `15 Prompt · Failure`가 소유한다.
- **Repository mapping reference:** confirmation/runtime/domain operation의 path·file·symbol naming은 `16 Repository Architecture`가 소유한다.

### Clarification 공통 요구

- 요청만으로 모호하면 Request Understanding에서 확인한다.
- 검색 후 복수 후보·저신뢰가 드러나면 Retrieval 이후 확인한다.
- 분석 후 관계·충돌이 불명확하면 Work Analysis 이후 확인한다.
- 후보가 있으면 후보 라벨·차이·Resource Ref를 선택지로 제공한다.
- `처리/진행/시작/정리/마무리`처럼 축약된 표현은 **현재 Run의 사용자 요청과 현재 Run에서 명시적으로 선택한 Resource**만으로 의미가 단일할 때 추가 질문하지 않는다. 과거 Conversation History나 previous-run Artifact를 암묵적으로 해석 근거로 사용하지 않는다.

### FN-028 Embedding·Reranking

- **상태:** EXP
- **설명:** Source-native 결과의 재정렬 방식은 `13 Evaluation`의 품질 비교와 Release decision을 통과한 configured capability만 제품 Runtime에 적용한다.

## 7. 분석 기능

### FN-030 Resource 관계 연결

- **상태:** P0
- **기능:** 제목·참여자·Thread·시간·명시적 Resource reference·Evidence를 사용해 Mail·Task·Event 사이의 업무 관계 후보를 찾고, 검증된 관계만 후속 분석/계획에 사용할 수 있어야 한다.
- **출력:** 관계 의미, 신뢰도/근거, Evidence reference.
- **완료 조건:** LLM이 제안한 관계 후보가 검증 없이 durable 사실이나 Action 근거로 확정되지 않는다.
- **Runtime authority reference:** relation candidate/normalization/validator의 exact operation/result semantics는 `06 Agent · Workflow`가 소유한다.
- **Prompt authority reference:** relation-analysis PromptRef/projection은 `15 Prompt · Failure`가 소유한다.
- **Repository mapping reference:** `work_analysis.*` relation operation mapping은 `16 Repository Architecture`가 소유한다.

### FN-031 Task 중복 검사

- **상태:** P0
- **기능:** Task CREATE 제안 전에 제목·사람·Thread·`scheduled_date`·현재 상태와 Evidence-backed `business_deadline`을 사용해 기존 Task와의 중복 가능성을 검사해야 한다.
- **처리:** LLM은 중복 후보를 제안할 수 있지만 최종 중복 판정과 생성 허용/차단은 실제 Source 사실과 정책을 재검증하는 결정적 책임을 가져야 한다.
- **출력:** 정확 중복이면 기본 새 생성 중단, 유사 후보면 경고/확인 필요, 중복이 아니면 신규 제안 가능 및 근거.
- **완료 조건:** LLM 단독 중복 판정이 새 Task 생성 허용/차단의 최종 근거가 되지 않으며, 정확 중복 override는 명시적 사용자 확인 없이 진행하지 않는다.
- **Policy authority reference:** duplicate/override 정책은 `01-B 정책`이 소유한다.
- **Runtime authority reference:** exact duplicate candidate/result enum과 validator semantics는 `06 Agent · Workflow`가 소유한다.
- **Repository mapping reference:** duplicate-check operation mapping은 `16 Repository Architecture`가 소유한다.

### FN-032 Calendar 충돌 검사

- **상태:** P0
- **기능:** Calendar CREATE/시간 변경 제안 전에 실제 조회한 Busy Interval·사용자 작업 시간·Buffer·기존 Event를 사용해 일정 충돌을 검사해야 한다.
- **처리:** LLM은 위험/interval 후보를 제안할 수 있지만 최종 충돌 판정과 차단/override 가능 여부는 검증된 외부 일정 사실과 정책을 사용하는 결정적 책임을 가져야 한다.
- **출력:** 충돌 없음, 경고/확인 필요, 차단과 근거.
- **완료 조건:** LLM 단독 판단으로 검증된 충돌을 우회하지 않으며, override가 허용되는 경우에도 필요한 사용자 확인/승인 없이 진행하지 않는다.
- **Policy authority reference:** Busy/Free/Tentative, Buffer, conflict override 정책은 `01-B 정책`이 소유한다.
- **Runtime authority reference:** exact conflict candidate/result/validator semantics는 `06 Agent · Workflow`가 소유한다.
- **Repository mapping reference:** conflict-check operation mapping은 `16 Repository Architecture`가 소유한다.

### FN-033 업무 가능성 판단

- **상태:** P0
- **기능:** Evidence/사용자 요청에서 확인된 업무 마감, 예상 소요시간, Calendar 가용성, 사용자 업무 시간을 함께 고려해 현재 업무가 가능·위험·불가능한지 근거와 함께 판단할 수 있어야 한다.
- **예외:** 필요한 예상 소요시간이나 일정 제약이 없으면 값을 만들어내거나 timed Event를 자동 제안하지 않고 사용자 확인으로 연결한다.
- **완료 조건:** feasibility 결과가 실제 Evidence/검증된 일정 정보에 근거하고, 불충분한 입력을 추측으로 메우지 않는다.
- **Runtime authority reference:** exact Work Analysis operation/result semantics는 `06 Agent · Workflow`가 소유한다.
- **Prompt authority reference:** feasibility/gap PromptRef와 failure handling은 `15 Prompt · Failure`가 소유한다.
- **Repository mapping reference:** feasibility operation mapping은 `16 Repository Architecture`가 소유한다.

## 8. 계획 기능

### FN-040 Action Plan 생성

- **상태:** P0
- **기능:** 사용자가 검토할 수 있도록 하나 이상의 제안 Action에 대상 capability, 변경 내용/Arguments, 근거, Risk, Dependency, Expected Result를 포함한 Action Plan을 생성한다.
- **처리:** 계획은 FN-102에서 이미 확정된 OUT Resource·Effect·Tool capability를 임의로 바꾸지 않고 사용자 목표와 Evidence를 반영해야 한다. 최종 실행 가능한 Action 구조는 Schema와 결정적 검증을 통과해야 한다.
- **완료 조건:** 모든 외부 Write Action에 승인 판단에 충분한 Evidence가 있고, Planning 단계가 Tool identity/effect를 재선택하지 않는다.
- **Runtime authority reference:** exact Planning typed artifact, per-route argument generation, deterministic assembly/validation과 output-route consumption semantics는 `06 Agent · Workflow`가 소유한다.
- **Prompt authority reference:** Planning PromptRef와 input projection은 `15 Prompt · Failure`가 소유한다.
- **Repository mapping reference:** planning operation/path/file/symbol mapping은 `16 Repository Architecture`가 소유한다.

### FN-041 Action Dependency DAG 생성

- **상태:** P0
- **기능:** 여러 Action이 있는 계획은 선행·후행 관계와 서로 독립적으로 실행 가능한 Action을 구분하는 유효한 Dependency DAG를 가져야 한다.
- **구현 책임:** 최종 dependency 관계는 자유형 LLM 판단만으로 확정하지 않고 결정적 검증·구성 책임을 가져야 한다.
- **완료 조건:** cycle, 존재하지 않는 Action 참조, 지원되지 않는 dependency가 있는 계획은 실행 가능 계획으로 확정되지 않으며, 각 Action의 선행 조건과 독립 실행 가능 여부가 모호하지 않다.
- **Runtime authority reference:** exact dependency derivation/validation semantics와 Planning runtime operation은 `06 Agent · Workflow`가 소유한다.
- **Domain authority reference:** 영속 ActionDependency와 Plan/Action 무결성 constraint는 `04 Domain · DB`가 소유한다.
- **Repository mapping reference:** `planning.build_dependencies` 등 dependency repository mapping은 `16 Repository Architecture`가 소유한다.

### FN-042 Gmail Draft 제안

- **상태:** P0
- **기능:** 사용자의 Gmail 관련 요청이 Write 제안을 필요로 하면 기존 Thread/Evidence·사용자 목표·업무 가능성을 근거로 수신자·CC·제목·본문·Thread 관계를 포함한 Draft 또는 SEND Action을 제안할 수 있어야 한다.
- **규칙:** `초안`, `문구`, `작성만`, `검토용`은 Draft 의미이고, 실제 전송을 요구하는 표현은 SEND 의미로 취급해 최종 수신자·CC·제목·본문·Thread를 사용자가 검토·승인할 수 있어야 한다.
- **완료 조건:** 제안이 이미 확정된 Gmail OUT capability를 임의 변경하지 않고, 승인 화면의 내용과 후속 승인 무결성 대상이 동일하다.
- **Runtime authority reference:** exact OUT route/tool/effect binding, argument generation과 Planning artifact semantics는 `06 Agent · Workflow`가 소유한다.
- **Prompt authority reference:** Draft/SEND content-generation PromptRef와 schema repair는 `15 Prompt · Failure`가 소유한다.
- **Policy authority reference:** 외부 주소·SEND 승인·허용 Effect 규칙은 `01-B 정책`이 소유한다.
- **Repository mapping reference:** Gmail planning operation mapping은 `16 Repository Architecture`가 소유한다.

### FN-042A Gmail Draft·Send 첨부파일

- **상태:** P0
- **입력:** 사용자가 명시적으로 선택한 로컬 파일.
- **기능:** Gmail Draft/SEND Action은 사용자가 승인 시 확인한 첨부파일 identity/Metadata와 실제 실행 bytes가 동일하다는 무결성 검증을 가져야 하며, 파일 원문 bytes 자체를 LLM이나 Approval 표시 데이터로 복제하지 않는다.
- **출력:** 승인된 첨부파일이 포함된 Gmail Draft 또는 SEND 결과.
- **예외:** 임시 파일 만료·누락·무결성 불일치가 발생하면 기존 승인을 사용해 실행하지 않고 파일 재선택·Action 재검토·새 승인으로 돌아간다.
- **완료 조건:** 승인되지 않았거나 승인 뒤 변경된 파일 bytes가 전송되지 않으며, 동일 파일 무결성은 실행 직전까지 검증 가능하다.
- **Interface/Security authority reference:** exact staging identifier/descriptor/hash algorithm, bounded staging requirement, MIME assembly와 attachment claim binding은 `07 Interface`와 `09 Security`가 소유한다. exact numeric upload limit은 runtime configuration의 implementation choice다.
- **Domain authority reference:** attachment descriptor가 Action/Approval lifecycle에 결합되는 exact schema/state는 `04 Domain · DB`가 소유한다.
- **Repository mapping reference:** staging/attachment/write implementation placement·naming은 `16 Repository Architecture`가 소유한다.
- **완료 조건:** 승인된 파일과 실제 전송 파일이 동일하고 기존 SEND Verification 계약을 그대로 수행한다.
### FN-043 Task 제안

- **상태:** P0
- **기능:** Task Write 제안은 사용자 목표·Evidence·중복 검사 결과에 근거해 제목·메모·`scheduled_date`·Task List 등 사용자가 검토할 수 있는 변경 내용을 제시해야 한다.
- **날짜 의미:** 실제 업무 마감(`business_deadline`)을 Google Task 예정일(`scheduled_date`)로 자동 변환하지 않으며 두 의미를 필요에 따라 별도로 보존한다.
- **제한:** Task CREATE는 필요한 중복 검사를 통과해야 하고, 완료 상태 변경·UPDATE·DELETE도 각각 해당 사용자 의도와 새 승인을 요구한다. DELETE 성공은 후속 Verification으로 확인해야 한다.
- **완료 조건:** 제안이 이미 확정된 Task OUT capability를 임의 변경하지 않고, 사용자에게 표시된 변경 내용·Evidence가 승인 대상과 일치한다.
- **Runtime authority reference:** exact route/tool/effect binding, argument generation과 Planning artifact semantics는 `06 Agent · Workflow`가 소유한다.
- **Policy authority reference:** duplicate/delete/update/approval 규칙은 `01-B 정책`이 소유한다.
- **Interface authority reference:** Task provider-field mapping과 delete verification procedure는 `07 Interface`가 소유한다.
- **Repository mapping reference:** Task planning operation mapping은 `16 Repository Architecture`가 소유한다.

### FN-044 작업 Event 제안

- **상태:** P0
- **기능:** Calendar Write 제안은 사용자 목표·Evidence·예상 소요시간·대상 Calendar·검증된 충돌 정보에 근거해 제목·시작/종료·설명·Calendar·허용 참석자 변경을 사용자가 검토할 수 있게 제시해야 한다.
- **제한:** 필요한 duration/배치 근거/대상 Calendar가 없으면 임의로 채우지 않고 확인을 요구한다. Event DELETE와 참석자 UPDATE는 각각 명시적 사용자 의도·승인을 요구하며 반복 Event 전체 일괄 수정은 지원하지 않는다.
- **완료 조건:** 제안이 이미 확정된 Calendar OUT capability를 임의 변경하지 않고, conflict/evidence/risk와 예상 결과가 승인 판단에 함께 제시된다.
- **Runtime authority reference:** exact route/tool/effect binding, argument generation과 Planning artifact semantics는 `06 Agent · Workflow`가 소유한다.
- **Policy authority reference:** conflict/attendee/delete/recurrence/approval 규칙은 `01-B 정책`이 소유한다.
- **Repository mapping reference:** Calendar planning operation mapping은 `16 Repository Architecture`가 소유한다.

## 9. 승인 기능

### FN-050 Context Preview

- **상태:** P0
- **기능:** 사용자는 승인 전에 현재 Run에서 실제 선택된 핵심 Context/Evidence의 출처와 범위를 확인하고, 아직 어떤 Action도 승인·실행되지 않은 경우 **일부 Evidence 제외** 또는 **추가 검색 요청**으로 Context를 조정할 수 있어야 한다.
- **Preview 처리:** Preview는 current `RetrievalResultV1`/Evidence selection의 deterministic projection이며 raw Provider payload·secret·checkpoint metadata를 노출하지 않는다.
- **조정 가능 시점:** `Run=WAITING_APPROVAL`, current Plan 존재, 모든 current Action이 `PROPOSED | MODIFIED`, ACTIVE Approval=0, in-flight/unknown/unverified execution fact=0일 때만 조정 Control을 노출한다. 그 외 상태에서는 Preview가 read-only다.
- **일부 제외:** 사용자가 current Preview의 `segment_id`를 선택하면 `run.adjust_context`가 current retrieval revision과 segment membership을 검증하고 `EXCLUDE_EVIDENCE` Context Adjustment를 같은 Run의 Retrieval owner에 전달한다. Retrieval은 새 `RetrievalResultV1` revision에서 해당 segment를 제외하고 Evidence selection/sufficiency를 다시 계산한다. Preview의 `retrieval_revision`과 mutation CAS는 동일한 durable typed `RetrievalHeadV1`에서 읽으며 Application이 opaque checkpoint를 해석하지 않는다.
- **추가 검색:** 사용자의 bounded `requested_information`은 `RetrievalNeedV1(required_information=..., reason_codes=[USER_CONTEXT_ADJUSTMENT])`로 deterministic projection된다. current frozen IN Route에서 해결 가능하면 Retrieval back-edge를 사용하고, 새 Route가 필요하면 기존 `RouteReconsiderationRequiredV1` 규칙으로 Tool Route를 재검토한다.
- **Plan 재계산:** `WAITING_APPROVAL`에서 Context Adjustment가 수락되면 기존 lifecycle command `BeginPlanning`의 `USER_CONTEXT_ADJUSTMENT` branch로 current Plan을 `SUPERSEDED`하고 Run을 `PLANNING`으로 되돌린다. 새 Retrieval revision 때문에 `meta.based_on`이 맞지 않는 Analysis/Planning/Review artifact는 stale이며 재사용하지 않는다.
- **금지:** 승인·Claim·ExecutionAttempt·Verification이 시작된 뒤 Context Adjustment로 이미 승인/실행된 의미를 소급 변경하지 않는다. 새 lifecycle command, 새 semantic owner, Browser-local Evidence mutation, DB 직접 수정은 만들지 않는다.
- **UI authority reference:** preview/expand/exclude/retrieve-more interaction은 `02 UI · UX`가 소유한다.
- **Retrieval authority reference:** Evidence selection·additional retrieval·sufficiency semantics는 `05 Retrieval`이 소유한다.
- **Interface/Repository mapping reference:** `GET /api/v1/runs/{run_id}`의 `ContextPreviewResponseV1`, `POST /api/v1/runs/{run_id}/context-adjustments`, `run.project_context_preview`, `run.adjust_context`의 wire/placement는 `07 Interface`와 `16 Repository Architecture`가 소유한다.

### FN-051 Action 승인

- **상태:** P0
- **기능:** 사용자는 여러 Action을 전체·Connector/시스템별·Action별로 검토하고 승인할 수 있어야 한다. 일괄 승인 UI를 사용하더라도 각 Action은 승인 당시 사용자가 본 대상·변경 내용·근거와 무결하게 결합되어야 한다.
- **완료 조건:** 승인하지 않은 Action이나 거절/차단된 종속 Action이 외부 Write로 실행되지 않으며, 일괄 승인 때문에 개별 Action의 승인 범위·내용이 확장되거나 섞이지 않는다.
- **Policy authority reference:** 어떤 Write가 승인을 요구하고 어떤 승인 범위가 허용되는지는 `01-B 정책`이 소유한다.
- **Domain authority reference:** Approval entity/snapshot/version/state/Command·Guard·Claim precondition은 `04 Domain · DB` + State Transition Contract가 소유한다.
- **UI authority reference:** 전체/그룹/Action별 승인 interaction과 표시 방식은 `02 UI · UX`가 소유한다.
- **Interface/Security authority reference:** browser/server 실행권 값과 claim validation 계약은 `07 Interface`와 `09 Security`가 소유한다.
- **Repository mapping reference:** approval operation/path/symbol naming은 `16 Repository Architecture`가 소유한다.

### FN-052 Action 수정

- **상태:** P0
- **수정 가능:** Draft 수신자·CC·제목·본문, Task 제목·메모·예정일, Event 제목·시간·설명처럼 정책과 Tool capability가 허용한 사용자 편집 필드.
- **처리:** 사용자가 Action 내용을 수정하면 수정된 내용에 대해 Schema·Policy·Evidence/Source·필요한 중복/충돌 조건을 다시 검증하고, 변경된 내용에 맞는 Review/승인을 다시 받아야 한다. Tool/Effect 자체가 달라져야 하는 수정은 기존 Action의 단순 field edit로 숨기지 않고 route capability 재검토로 연결한다.
- **완료 조건:** 수정 전 승인 권위를 수정 후 Action 실행에 재사용할 수 없고, 사용자가 실제로 수정·재검토한 내용만 새 승인 대상이 된다.
- **Policy authority reference:** 수정 가능 필드·재승인 조건은 `01-B 정책`이 소유한다.
- **Domain authority reference:** Action versioning, Approval invalidate/expire, modify Command·Guard·transition은 `04 Domain · DB` + State Transition Contract가 소유한다.
- **Runtime authority reference:** route reconsideration·review/reapproval 경로는 `06 Agent · Workflow`가 소유한다.
- **Repository mapping reference:** modify/review/approval operation mapping은 `16 Repository Architecture`가 소유한다.

### FN-053 Action 거절

- **상태:** P0
- **처리:** 사용자가 거절한 Action은 외부 Write로 실행되지 않아야 하고, 그 Action에 의존하는 후속 Action도 실행 가능 여부를 다시 판단해야 한다. 독립 Action은 별도 승인·정책 조건을 만족하면 계속될 수 있다. 사용자가 대안을 원하면 거절된 Action을 몰래 되살리지 않고 새 계획/검토 결과로 제안한다.
- **완료 조건:** 거절 Action과 실행 불가능해진 종속 Action은 Write로 진행하지 않으며, 후속 대안이 기존 승인 권위를 재사용하지 않는다.
- **Policy authority reference:** 거절 이후 허용/차단 규칙은 `01-B 정책`이 소유한다.
- **Domain authority reference:** Reject Command·상태 전이·Approval/Action lifecycle은 `04 Domain · DB` + State Transition Contract가 소유한다.
- **Runtime authority reference:** dependency 재평가와 새 Planning/Review 경로는 `06 Agent · Workflow`가 소유한다.
- **Repository mapping reference:** reject/replan operation mapping은 `16 Repository Architecture`가 소유한다.

### FN-054 승인 무결성 Snapshot·만료

- **상태:** P0
- **기능:** 사용자의 승인은 승인 당시 검토한 Action 대상·Tool/Effect·Arguments·근거/Source·적용 정책/Schema 조건과 무결하게 결합되어야 하며 제한된 유효 기간을 가져야 한다.
- **처리:** 승인 이후 유효시간 경과, 원본 Resource 변경, Action 내용 수정, 적용 Tool Schema/Policy 변경처럼 승인 의미를 stale하게 만드는 조건이 생기면 기존 승인을 실행에 사용할 수 없고 재검토·새 승인으로 돌아가야 한다.
- **완료 조건:** 사용자가 보지 않았거나 승인 뒤 의미가 달라진 Action, 만료된 승인으로 외부 Write를 시작할 수 없다.
- **Policy authority reference:** 승인 만료·staleness 조건과 기본 유효시간 정책은 `01-B 정책`이 소유한다.
- **Domain authority reference:** Approval Snapshot의 exact field set/hash/version/state, Preflight/Claim Guard·Command·transition은 `04 Domain · DB` + State Transition Contract가 소유한다.
- **Interface/Security authority reference:** approval/claim payload binding, one-time execution authority와 validation은 `07 Interface`와 `09 Security`가 소유한다.
- **Repository mapping reference:** approval/preflight/claim operation mapping은 `16 Repository Architecture`가 소유한다.

### 승인형 Write 공통 요구

- `SEND`: Gmail 실제 전송.
- `UPDATE`: Task 완료, Calendar 참석자 변경 포함.
- `DELETE`: 정확한 Google Task 삭제와 Calendar Event 삭제.
- Gmail Message·Thread 원문 삭제는 OUT을 유지한다.

## 10. 실행 기능

### FN-060 승인된 외부 Write 실행

- **상태:** P0
- **기능:** 외부 Write는 사용자가 승인한 현재 Action만 대상으로, 실행 직전에도 승인·정책·dependency·Source 최신성·Tool/Arguments 무결성이 유효한지 확인한 뒤 Connector 경계를 통해 실행되어야 한다.
- **처리:** 실행에 사용되는 Tool/Effect/Arguments가 사용자가 승인한 의미와 달라지지 않아야 하고, Connector/MCP 경계가 실제 실행 요청을 다시 검증해야 한다. Core/Application이 Provider API를 직접 호출하지 않는다.
- **출력:** 외부 Resource 식별자 또는 bounded 실행 결과 Metadata와 실제 실행 상태.
- **완료 조건:** 유효하지 않거나 stale한 승인, 승인 내용과 다른 Arguments, 허용되지 않은 Tool/Effect로 Write를 실행할 수 없고, 실행 결과는 후속 Verification/Recovery가 소비할 수 있어야 한다.
- **Policy authority reference:** 실행 허용/차단·승인 요구 조건은 `01-B 정책`이 소유한다.
- **Domain authority reference:** Preflight/Claim Command·Guard·Action/Approval/Attempt 상태 전이는 `04 Domain · DB` + State Transition Contract가 소유한다.
- **Interface/Security authority reference:** one-time execution authority, arguments binding, Connector/MCP validation과 Provider boundary는 `07 Interface`와 `09 Security`가 소유한다.
- **Runtime authority reference:** Approval→Preflight→Execution→Verification/Recovery routing은 `06 Agent · Workflow`가 소유한다.
- **Repository mapping reference:** execution/preflight/claim/connector operation placement·naming은 `16 Repository Architecture`가 소유한다.

### FN-061 Write Idempotency·기존 결과 조정

- **상태:** P0
- **기능:** UI/네트워크 재시도, 응답 유실, Service 재시작이 같은 승인된 외부 Effect를 중복 적용하지 않아야 한다.
- **처리:** 중복 실행 가능성이 있으면 새 Write를 먼저 보내지 않고 현재 제품 실행 사실과 이미 관측 가능한 외부 결과를 조정해야 한다. 외부 결과가 불명확하면 동일 Write를 자동 재전송하지 않고 기존 결과 확인/Recovery로 전환한다.
- **완료 조건:** 하나의 승인된 실행 의도가 외부 시스템에 중복 생성·수정·전송·삭제를 만들지 않는다.
- **Domain authority reference:** Action/Attempt/Command Receipt/idempotency state와 Guard/transition은 `04 Domain · DB` + State Transition Contract가 소유한다.
- **Runtime/Interface authority reference:** existing-result/Verification/Recovery routing과 Connector result-read strategy는 `06 Agent · Workflow`와 `07 Interface`가 소유한다.
- **Repository mapping reference:** idempotency/reconciliation operation placement·naming은 `16 Repository Architecture`가 소유한다.

### FN-062 부분 실행

- **상태:** P0
- **기능:** 여러 Action 중 일부가 실패·거절·중단되어도 dependency가 없는 독립 Action은 별도 승인·정책 조건을 만족하면 계속 실행할 수 있고, 실패한 선행 Action에 의존하는 Action은 실행되지 않아야 한다.
- **출력:** 사용자에게 완료·미실행·실패·복구 필요 Action이 구분된 부분 실행 결과를 제공한다.
- **완료 조건:** 성공한 외부 Write를 가짜 rollback으로 지우지 않고, dependency가 깨진 Action을 실행하지 않으며, partial outcome을 전체 성공처럼 표시하지 않는다.
- **Domain authority reference:** per-Action execution/terminal state와 dependency persistence는 `04 Domain · DB`가 소유한다.
- **Runtime authority reference:** 다음 executable Action 선택, block/recovery routing은 `06 Agent · Workflow`가 소유한다.
- **UI authority reference:** partial-result 사용자 표시 방식은 `02 UI · UX`가 소유한다.
- **Repository mapping reference:** execution scheduler/dependency operation placement·naming은 `16 Repository Architecture`가 소유한다.

## 11. 검증·복구 기능

### FN-070 실행 결과 검증

- **상태:** P0
- **기능:** 모든 외부 Write 결과는 해당 Effect에 맞는 독립적인 외부 상태 재조회/검증을 거쳐 실제 결과와 승인·실행 시 기대한 결과를 비교해야 한다.
- **완료 조건:** CREATE/UPDATE/SEND/DELETE 각각의 성공이 Write 응답만으로 확정되지 않고, 검증 가능한 외부 사실을 기준으로 VERIFIED/MISMATCH/불명확 결과를 구분할 수 있다.
- **Interface/Verification authority reference:** exact Verification Read procedure/strategy identifier와 Connector operation contract는 `07 Interface`가 소유하고, expected/actual persistent fact 및 lifecycle meaning은 `04 Domain·DB` + `Domain State Transition Contract`가 소유한다. `12 Test`는 이를 검증하고 `14 Operations`는 운영 절차로 투영할 뿐 production behavior를 공동 소유하지 않는다. `GET_TARGET`/`GET_COMPARE`류 이름을 01-A가 production operation으로 정의하지 않는다.
- **Domain authority reference:** Verification entity/status/Command/transition은 `04 Domain · DB` + State Transition Contract가 소유한다.
- **Runtime authority reference:** Verification/Recovery routing은 `06 Agent · Workflow`가 소유한다.
- **Repository mapping reference:** verification operation/path/symbol naming은 `16 Repository Architecture`가 소유한다.

### FN-071 정상화 비교

- **상태:** P0
- **기능:** 외부 Write 검증 비교는 표현 차이만 있는 값과 실제 의미 불일치를 구분해야 한다.
- **정상화 대상:** 공백, 줄바꿈, Timezone 표현, 초 단위 정밀도, Connector/Provider가 합법적으로 채우는 기본값처럼 의미를 바꾸지 않는 차이.
- **완료 조건:** 허용된 표현 차이는 false mismatch를 만들지 않고, 사용자 의미를 바꾸는 핵심 필드 차이는 normalization으로 숨기지 않는다.
- **Interface authority reference:** `07 Interface`는 Verification typed result/comparison boundary와 FN-071의 representation-preserving normalization category를 소비한다. Connector별 private canonicalization algorithm/data structure는 `00`의 implementation choice이며, semantic field 차이를 숨기지 않는다는 기능 계약은 본 FN-071이 소유한다.
- **Repository mapping reference:** normalization/comparison implementation placement·naming은 `16 Repository Architecture`가 소유한다.

### FN-072 Mismatch Recovery

- **상태:** P0
- **기능:** 검증 결과 핵심 의미가 기대와 다르면 성공으로 숨기거나 자동으로 추가 Write를 수행하지 않고, 실제 차이와 안전하게 선택 가능한 Recovery 경로를 사용자에게 제시해야 한다.
- **완료 조건:** MISMATCH/불명확 외부 결과가 자동 성공·자동 재전송·자동 corrective Write로 바뀌지 않으며, 사용자의 선택 또는 안전한 결정적 복구 절차를 거쳐 해결된다.
- **Policy authority reference:** 자동 실행 금지·추가 승인 조건은 `01-B 정책`이 소유한다.
- **Domain authority reference:** RECOVERY_REQUIRED와 Resolve/Fail/Cancel/partial 관련 상태·Command·Guard·transition은 `04 Domain · DB` + State Transition Contract가 소유한다.
- **Runtime authority reference:** reverify/corrective-plan/confirmation/recovery routing은 `06 Agent · Workflow`가 소유한다.
- **UI authority reference:** 차이와 Recovery 선택지의 사용자 표시 방식은 `02 UI · UX`가 소유한다.
- **Repository mapping reference:** recovery operation placement·naming은 `16 Repository Architecture`가 소유한다.

### FN-073 OAuth 재인증 후 재개

- **상태:** P0
- **기능:** Connector Credential이 만료·취소되거나 갱신에 실패하면 현재 Run의 안전한 진행 사실을 잃지 않고 사용자에게 재인증을 요청한 뒤, 성공 시 동일 Run을 안전하게 계속할 수 있어야 한다.
- **처리:** 이미 외부 Write가 dispatch되었는지 불명확한 상황에서는 재인증 후 같은 Write를 단순 재전송하지 않고 저장된 실행 사실과 Verification/Recovery 결과를 우선 확인한다.
- **완료 조건:** 재인증이 새 Run이나 새 승인으로 오인되지 않고, 같은 Run의 이미 완료·in-flight Action이 중복 실행되지 않는다.
- **Domain authority reference:** REAUTH 관련 상태·Command·Guard·허용 resume transition은 `04 Domain · DB` + State Transition Contract가 소유한다.
- **Runtime authority reference:** checkpoint/thread/resume target과 안전한 복귀 Phase는 `06 Agent · Workflow`가 소유한다.
- **Credential/Security authority reference:** OAuth refresh/reauth/token storage boundary는 `07 Interface`, `09 Security`, `10 Infrastructure`가 소유한다.
- **Repository mapping reference:** reauth/resume operation placement·naming은 `16 Repository Architecture`가 소유한다.

## 12. 관측성 기능

### FN-080 Run Trace

- **상태:** P0
- **내용:** Run/Node/Agent/Tool/Connector/Provider correlation, Source·candidate·retrieval 수량, 모델·fallback, Latency, Token/비용, 상태, Command ID, Event Cursor, bounded failure/validator/retry metadata.
- **원칙:** Trace는 판단·호출 설명과 성능 관측용이며 Domain 실행 사실의 기준점이 아니다. 원문 대신 allowlisted ID·Hash·수량·상태·지연을 기록한다.
- **제외:** OAuth/API/Bootstrap/Session/PKCE/Claim Token과 비밀값, Connector Source·Draft 전체 본문, Gmail attachment bytes/Staging 파일 원문·로컬 경로, LLM Prompt/Completion, MCP 전체 Request/Response, Approval Snapshot 전체와 실행 hash/nonce/signature 원문.

### FN-081 Audit Log

- **상태:** P0
- **내용:** Policy Confirmation, Action 제안/수정/승인/거절/만료, Approval consume, Policy 차단, Execution Claim/성공/실패/UNKNOWN_RESULT/복구, Verification, Recovery 및 필수 운영 안전 사건.
- **특성:** Application-level append-only 안전 기록이며 UI에서 수정할 수 없다. 필수 안전 Command의 Audit 저장이 실패하면 해당 Command도 성공으로 확정하지 않는다. 질문/응답·Connector 원문·Token/Claim 원문 등 비허용 payload는 Audit에 저장하지 않는다.

### FN-082 사용자 진단 화면

- **상태:** P0
- **내용:** Launcher/Manifest, React Build, Local Agent API/Session, Google Workspace Connector·MCP/Credential 상태, LLM Runtime, SQLite/Migration, SSE, 최근 오류와 복구 Action의 **sanitized bounded projection**.
- **제한:** 진단 화면/Bundle은 DB·Backup·Keyring 원본, Connector 원문, Prompt/Completion, Approval Snapshot/Claim Token, Credential/Secret을 노출하지 않으며 자동 외부 업로드하지 않는다.

## 13. 범위 제외 기능

| ID | 기능 | 상태 |
| --- | --- | --- |
| P0-WRITE-001 | Gmail 승인형 전송 | P0 |
| OUT-002 | Gmail Message·Thread 원문 삭제 | OUT |
| P0-WRITE-002 | Google Task·Calendar Event 승인형 삭제 | P0 |
| P0-WRITE-003 | Calendar 참석자 승인형 추가·수정 | P0 |
| OUT-004 | CPU Local LLM | OUT |
| OUT-005 | 원격 SaaS·멀티 사용자·외부 공개 API | OUT |
| OUT-006 | 백그라운드 자동 실행 | OUT |
| OUT-007 | Gmail·Tasks·Calendar 전체 데이터의 로컬 상시 복제 | OUT |
| OUT-008 | 페이지 이동마다 이미 조회한 목록을 다시 호출하는 동작 | OUT |

## 14. Google Source 데이터 수명주기 Functional 요구

1. **목록:** 사용자가 Sidebar에서 탐색하는 목록은 필요한 범위만 조회하고 UI 세션 범위 cache로 재사용하며, Google 원본 전체를 제품 DB에 상시 복제하지 않는다.
2. **상세:** 사용자가 Resource를 focus/선택하거나 현재 Run에서 실제 후보가 확정됐을 때 필요한 상세만 조회한다.
3. **LLM Context:** 현재 Run 수행에 필요한 최소 상세만 LLM Context로 사용할 수 있으며, Source 원문 전체를 장기 Semantic Memory로 축적하지 않는다.
4. **영구 기록:** 실제 판단·승인에 사용된 Resource reference, 최소 Metadata, Evidence excerpt처럼 제품 사실 추적에 필요한 최소 정보만 보존한다.
5. **최신성:** 계획 확정 전, 승인된 Write 실행 직전, 실행 이후에는 관련 외부 Resource 최신성을 다시 확인할 수 있어야 한다.
- **Retrieval/Interface authority reference:** exact Browse/Count/Detail/Verification Read Tool, pagination/cache/Provider invocation semantics는 `05 Retrieval`과 `07 Interface`가 소유한다.
- **Persistence authority reference:** 어떤 Source/Evidence reference가 durable DB 사실인지와 보존 구조는 `04 Domain · DB`가 소유한다.
- **Repository mapping reference:** Connector/Provider Adapter, query/cache/verification implementation placement·naming은 `16 Repository Architecture`가 소유한다.

## 15. Frontend · Local Service Functional 경계

1. 사용자는 로컬 UI에서 요청·선택·승인·수정·복구 행동을 수행하고 현재 상태/진행 Projection을 볼 수 있어야 한다.
2. UI는 서버가 검증한 API 경계를 통해서만 제품 상태를 읽거나 변경하며 Domain/Connector/Workflow 구현에 직접 접근하지 않는다.
3. 화면 cache와 Event/SSE Projection은 사용자 경험을 위한 상태일 뿐 승인·실행·검증의 최종 제품 사실을 대신하지 않는다.
4. UI/네트워크 재시도는 동일한 상태 변경을 두 번 적용하지 않아야 한다.
5. Workflow/Agent 기능은 제품 상태를 임의로 직접 영속 수정하는 별도 authority가 아니며, 상태 변경은 owning Domain/Application 경계를 따라야 한다.
- **System authority reference:** concrete Frontend/API/Application/Workflow/Domain dependency direction은 `03 System Architecture`가 소유한다.
- **Interface/Security authority reference:** exact REST/SSE schema, Local Session, Host/Origin, Command identity/version contract는 `07 Interface`와 `09 Security`가 소유한다.
- **Domain authority reference:** state-changing Command/Guard/transaction/idempotency semantics는 `04 Domain · DB` + State Transition Contract가 소유한다.
- **Repository mapping reference:** concrete layer path/file/symbol naming은 `16 Repository Architecture`가 소유한다.

## 16. Multi-Agent 기능

### FN-100 Supervisor Routing

- **상태:** P0

현재 Run의 처리를 전문 기능 단계 사이에서 안전하게 조정하고, 필요한 경우 사용자 확인·중단·종료 경로로 전환할 수 있어야 한다. 기능 요구상 전문 Agent 기능은 서로 직접 호출하지 않고 중앙 조정 경계를 통해 연결된다.

- **Runtime authority reference:** 정확한 Supervisor State·Edge·Disposition·Interrupt·Budget semantics는 `06 Agent · Workflow`가 소유한다.
- **Repository mapping reference:** Supervisor/routing repository placement·operation·symbol naming은 `16 Repository Architecture`가 소유한다.

### FN-101 요청 이해 Agent

- **상태:** P0

사용자 요청에서 목표·완료 조건·제약·모호성과 추가 업무 분석 필요 여부를 구조화할 수 있어야 한다. 이 기능은 Tool identity, Provider-native Query, Action Arguments를 직접 정하지 않으며, 모호성이 해결되지 않으면 사용자 확인 기능으로 연결한다. 특정 Write가 정책상 중복·충돌 사전 검사를 요구하면 그 정책 의존성을 보존해야 한다.

- **Runtime authority reference:** Request Understanding의 exact typed artifact, runtime operation 분해, analysis-requirement 표현과 disposition은 `06 Agent · Workflow`가 소유한다.
- **Prompt authority reference:** PromptRef·input projection·repair/revision 계약은 `15 Prompt · Failure`가 소유한다.
- **Repository mapping reference:** `request_understanding.*` mapping은 `16 Repository Architecture`가 소유한다.

### FN-102 Tool Route Agent

- **상태:** P0

요청을 수행하기 위해 필요한 IN Connector·Resource·Read capability 범위와 OUT Resource·Effect capability를 계획 전에 확정할 수 있어야 한다. 정책상 필요한 사전 중복·충돌 검사는 입력 범위에 포함되어야 하며, 사용자가 제한한 Source·기간·Resource 범위를 넘어야 하면 명시적 확인 없이 확장하지 않는다. 확정된 route capability는 downstream Retrieval/Planning이 재선택하지 않고 소비해야 한다.

- **Runtime authority reference:** Tool Registry 결합·candidate selection·route artifact·IN/OUT revision·scope-expansion disposition·downstream routing semantics는 `06 Agent · Workflow`와 `07 Interface`가 소유한다.
- **Prompt authority reference:** Tool Route Prompt/repair contract는 `15 Prompt · Failure`가 소유한다.
- **Repository mapping reference:** canonical `tool_routing.*` mapping은 `16 Repository Architecture`가 소유한다.

### FN-103 Retrieval Agent

- **상태:** P0

확정된 current-run input scope 안에서 필요한 자료를 조회·정규화하고 Evidence를 선택하며 Context 충분성을 판단할 수 있어야 한다. Retrieval은 입력 범위를 임의 확대하거나 OUT capability를 선택하지 않고, 부족한 경우 bounded additional retrieval 또는 route/confirmation 재판단으로 연결해야 한다. FN-109/FN-111은 이 기능을 실제 runtime에서 수행하기 위한 구현 책임 요구이며 별도 Functional capability를 새로 만들지 않는다.

- **Runtime authority reference:** Retrieval의 exact runtime responsibility·typed artifact·Local State·bounded loop·WorkflowSignal semantics는 `05 Retrieval`과 `06 Agent · Workflow`가 소유한다.
- **Prompt authority reference:** Retrieval Prompt input/repair/revision contract는 `15 Prompt · Failure`가 소유한다.
- **Repository mapping reference:** canonical `retrieval.*` mapping은 `16 Repository Architecture`가 소유한다.

### FN-104 업무 분석 Agent

- **상태:** P0

FN-030~FN-033의 Functional capability로서 현재 요청과 허용 Evidence에서 업무 사실·관계·정보 누락·중복/충돌 후보·일정 제약·업무 가능성·운영 위험을 분석할 수 있어야 한다. 관계·중복·충돌 후보가 LLM 결과만으로 최종 확정되어서는 안 되며, 결정적 검증을 거친 결과만 후속 Planning에 사용할 수 있다. 정확 중복/검증된 충돌을 사용자가 명시적으로 override하려는 경우에는 필요한 사용자 확인을 거쳐야 한다. Tool 선택·Tool Arguments·최종 정책 allow/deny는 이 Functional capability의 책임이 아니다.

- **Runtime authority reference:** Work Analysis의 atomic runtime responsibilities, typed result, validator/assembler, confirmation/back-edge semantics는 `06 Agent · Workflow`가 소유한다.
- **Prompt authority reference:** Work Analysis PromptRef·projection·repair/revision은 `15 Prompt · Failure`가 소유한다.
- **Repository mapping reference:** canonical `work_analysis.*` mapping은 `16 Repository Architecture`가 소유한다.

### FN-105 Planning Agent

- **상태:** P0

FN-040~FN-044의 Functional capability로서 현재 요청·확정된 OUT capability·허용 Evidence·선택적 업무 분석을 사용해 답변 또는 실행 가능한 Action Plan을 제안할 수 있어야 한다. ACTION 경로에서는 확정된 Tool capability를 바꾸지 않고 필요한 Business Arguments·Evidence·Risk·Expected Result를 준비하며, Action dependency와 최종 Plan 조립·검증은 결정적 구현 책임으로 보장되어야 한다.

- **Runtime authority reference:** ANSWER/ACTION 분기, atomic Planning responsibilities, dependency construction, plan assembly/validation, revision/back-edge semantics는 `06 Agent · Workflow`가 소유한다.
- **Prompt authority reference:** Planning PromptRef·input projection·repair/revision은 `15 Prompt · Failure`가 소유한다.
- **Repository mapping reference:** `planning.choose_answer_or_action_from_route`, `planning.outline_answer`, `planning.compose_answer` 등 canonical repository mapping은 `16 Repository Architecture`가 소유하며, 01-A의 언급은 구현 관계 reference다.

### FN-106 계획 검토 Agent

- **상태:** P0

제안된 답변/Action Plan이 사용자 목표를 충족하는지, Evidence가 충분한지, 과잉 작업·모순·Dependency 문제·지원 불가 Action이 없는지 독립적으로 검토할 수 있어야 한다. 검토 결과는 승인 가능한 상태, 수정 필요, 추가 Retrieval, route 재검토, 사용자 확인, 차단 중 필요한 후속 기능으로 연결될 수 있어야 한다.

- **Runtime authority reference:** exact Review disposition identifiers, affected-dimension recheck, aggregation/validation, Supervisor back-edge semantics는 `06 Agent · Workflow`가 소유한다.
- **Prompt authority reference:** Review PromptRef와 failure/revision contract는 `15 Prompt · Failure`가 소유한다.
- **Repository mapping reference:** canonical `review.*` mapping은 `16 Repository Architecture`가 소유한다.

### FN-107 Typed Handoff·Checkpoint

- **상태:** P0

전문 기능 단계 사이의 Handoff는 current-run 공식 typed 결과와 안정적 Ref/Handle을 사용해야 하며 자유 텍스트 Agent 대화나 Agent별 장기 Semantic Memory에 의존하지 않아야 한다. 중단·확인·재개가 필요한 경우에는 동일 Run의 안전한 진행 정보를 보존하면서 이전 Run 결과를 새 Run에 암묵적으로 승계하지 않아야 한다.

- **Runtime authority reference:** Main/Subgraph State, projection, WorkflowSignal, interrupt/back-edge/checkpoint semantics는 `06 Agent · Workflow`가 소유한다.
- **Domain authority reference:** durable Run/Checkpoint/confirmation 관련 사실과 허용 상태 전이는 `04 Domain · DB` + State Transition Contract가 소유한다.
- **Repository mapping reference:** state/projection/graph placement와 naming은 `16 Repository Architecture`가 소유한다.

### FN-108 응답 조립

- **상태:** P0

최종 사용자 응답은 현재 Run에서 검증된 답변/계획·업무 분석·실행·검증·복구 결과 중 사용자에게 허용된 정보만 사용해 조립되어야 한다. 응답 조립 단계가 새 사실·Tool·Action·Policy 결정을 만들거나 내부 Agent Local State·비공개 추론을 노출해서는 안 된다.

- **Runtime authority reference:** response synthesis phase와 Supervisor routing 경계는 `06 Agent · Workflow`가 소유한다.
- **UI authority reference:** 실제 사용자 표시와 interaction 표현은 `02 UI · UX`가 소유한다.
- **Repository mapping reference:** response/routing placement·operation naming은 `16 Repository Architecture`가 소유한다.

## 17. Agent 실행 기능

### FN-109 Retrieval Subgraph 실행

- **상태:** P0

FN-103 Retrieval capability가 실제 current-run runtime에서 bounded하게 수행되고 공식 결과만 downstream에 전달될 수 있어야 한다. Retrieval 실행 중간 후보·raw continuation·RAG intermediate·Provider payload가 장기 Main State나 별도 제품 사실로 승격되어서는 안 된다.

- **Runtime authority reference:** Subgraph topology·Local State·Node 순서·bounded loop·typed result merge는 `05 Retrieval`과 `06 Agent · Workflow`가 소유한다.
- **Prompt authority reference:** Retrieval node별 PromptRef·repair/revision은 `15 Prompt · Failure`가 소유한다.
- **Repository mapping reference:** Retrieval graph/node/application operation placement는 `16 Repository Architecture`가 소유한다.

### FN-110 Answer-only Run 완료

- **상태:** P0

사용자 요청이 조회·분석·답변만으로 충족되고 외부 Write Action이 필요하지 않으면 Action/Approval/Execution artifact를 억지로 만들지 않고 Answer-only로 Run을 완료할 수 있어야 한다.

- **Domain authority reference:** 실제 terminal Command·Guard·상태 전이와 허용 source state는 `04 Domain · DB` + State Transition Contract가 소유한다.
- **Runtime authority reference:** Answer-only terminal path와 FINALIZE 연결은 `06 Agent · Workflow`가 소유한다.
- **Repository mapping reference:** completion operation/path/symbol은 `16 Repository Architecture`가 소유한다.

### FN-111 Retrieval 결정적 READ 실행

- **상태:** P0
- **입력:** 확정된 current-run input-route 범위와 검증된 Retrieval query/fetch intent.
- **처리:** Retrieval Read는 허용된 Connector Read 경계만 사용해야 하며 Provider-native Query·raw continuation·MCP Arguments를 LLM이 직접 생성·실행해서는 안 된다. 일반 Retrieval Read가 Write용 Action·Approval lifecycle을 만들지 않아야 한다.
- **출력:** 현재 Run에 귀속된 bounded Read 결과 참조와 retrieval metadata.
- **완료 조건:** frozen input 범위 밖 Read 없이 후속 Normalize/Evidence 기능이 소비할 수 있는 결과가 제공되고 raw Provider continuation/원문이 불필요한 제품 상태로 복제되지 않는다.
- **Runtime/Interface authority reference:** query builder·read-result handle/cache·Connector Read invocation·continuation semantics는 `05 Retrieval`, `06 Agent · Workflow`, `07 Interface`가 소유한다.
- **Repository mapping reference:** `retrieval.build_query` / `retrieval.execute_read` 등 repository operation mapping은 `16 Repository Architecture`가 소유한다.

### FN-112 Retrieval READ 실패 처리

- **상태:** P0
- **처리:** Retrieval query/route/binding/schema/Connector Read 검증 실패는 성공으로 위장하지 않고 fail-closed해야 한다. 같은 요청을 무의미하게 반복하지 않으며, 같은 input 범위 안에서 새 정보 획득 가능성이 있을 때만 bounded 추가 Retrieval을 허용한다. 새 Source/Tool 범위·재인증·사용자 확인이 필요하면 해당 기능 경계로 넘겨야 한다.
- **출력:** 복구 가능한 다음 기능 또는 안전한 실행 불가 결과.
- **완료 조건:** 실패 처리 때문에 허용 범위가 자동 확대되거나 Write가 실행되거나 과거 Run 결과가 재사용되지 않는다.
- **Runtime/Failure authority reference:** exact failure codes·retry/reconsideration/confirmation/reauth disposition은 `06 Agent · Workflow`와 `15 Prompt · Failure`가 소유한다.
- **Domain authority reference:** REAUTH/RECOVERY 등 durable state/transition은 `04 Domain · DB` + State Transition Contract가 소유한다.
- **Repository mapping reference:** failure-handling operation naming/placement는 `16 Repository Architecture`가 소유한다.

### FN-113 Write 재시도 준비

- **상태:** P0

외부 Write가 **실제로 전송되지 않은 실패**로 확인된 경우에만 재시도 준비가 가능해야 하며, 수정/재검토·새 승인과 새 실행 시도를 거쳐야 한다. 외부 결과가 불명확한 `UNKNOWN_RESULT`에서는 같은 Write를 재전송하지 않고 Recovery/Verification으로 실제 결과를 먼저 확정해야 한다.

- **Domain authority reference:** FAILED/UNKNOWN_RESULT의 정확한 상태, retry-preparation Command·Guard·transition은 `04 Domain · DB` + State Transition Contract가 소유한다.
- **Runtime authority reference:** retry/review/reapproval/recovery routing은 `06 Agent · Workflow`가 소유한다.
- **Repository mapping reference:** retry operation/path/symbol naming은 `16 Repository Architecture`가 소유한다.

### FN-114 Supervisor Routing 결정성 보장

- **상태:** P0

FN-100의 중앙 조정 기능은 같은 공식 runtime 조건에서 일관된 다음 단계가 선택되는 결정성을 가져야 한다. LLM 자유 텍스트나 임시 Agent 내부 상태가 임의로 다음 기능을 선택해서는 안 되며, 해석할 수 없는 runtime 결과는 추측하지 않고 fail-closed 또는 안전한 Recovery 기능으로 연결되어야 한다.

- **완료 조건:** 제품 기능 관점에서 동일한 공식 입력 조건이 임의의 서로 다른 다음 단계로 갈라지지 않는다. FN-114는 FN-100과 별개의 routing capability가 아니라 그 결정성 요구다.
- **Runtime authority reference:** exact Edge·Disposition·resume target·Budget/Registry semantics는 `06 Agent · Workflow`가 소유한다.
- **Repository mapping reference:** routing operation/path/symbol은 `16 Repository Architecture`가 소유한다.

---

### FN-115 Agent Subgraph 실행 계약

- **상태:** P0
- **처리:** 각 전문 Agent 기능은 현재 Run에서 필요한 입력만 받아 bounded invocation으로 수행되고, 결과는 downstream이 검증 가능하게 전달되어야 한다. Agent 기능끼리 자유 대화형 peer-to-peer 호출을 하거나 invocation-local 임시 상태를 장기 Semantic Memory/Domain 사실로 승격해서는 안 된다.
- **출력:** 후속 기능이 소비할 수 있는 versioned typed 결과와 필요한 진행 신호.
- **상태 수명:** invocation-local 작업 상태는 해당 invocation 범위를 넘는 제품 사실이 아니다. 동일 Run 재개에 필요한 공식 정보만 owning runtime/domain contract에 따라 보존한다.
- **완료 조건:** 전문 Agent 기능 간 직접 호출 없이 bounded execution과 current-run state isolation이 유지된다.
- **Runtime authority reference:** Subgraph/Profile Registry·Local State·projection·Node·repair/revision·result/disposition semantics는 `06 Agent · Workflow`가 소유한다.
- **Prompt authority reference:** LLM call/PromptRef/failure-repair 책임은 `15 Prompt · Failure`가 소유한다.
- **Repository mapping reference:** subgraph/agent operation placement·naming은 `16 Repository Architecture`가 소유한다.

## 18. Local Command·Connection 기능

> 문서 권위는 `01 PRD §1.1`의 Concern Owner 규칙을 따른다. 이 절은 기능 동작만 정의하며 안전·Domain·Tool 계약을 완화하지 않는다.
### FN-019 상태 변경 요청 중복 적용 방지

- **상태:** P0
- **기능:** 브라우저 재시도, 응답 유실, Service 재시작, 중복 클릭처럼 동일한 상태 변경 요청이 다시 도착해도 같은 변경을 두 번 적용하지 않아야 한다.
- **처리:** 동일한 요청 identity와 동일한 요청 내용의 재전송은 이미 확정된 결과를 안전하게 재사용할 수 있어야 하고, 같은 identity에 다른 요청 내용이 결합되면 충돌로 거절해야 한다.
- **완료 조건:** 네트워크·UI 재시도로 동일한 제품 상태 변경이 중복 적용되지 않고, 서로 다른 요청이 같은 identity로 합쳐지지 않는다.
- **Domain authority reference:** Command Receipt schema, canonical request hash, optimistic version, transaction/guard/transition, duplicate-command result semantics는 `04 Domain · DB` + State Transition Contract가 소유한다.
- **Interface authority reference:** 외부 Command identity/request 계약은 `07 Interface`가 소유한다.
- **Repository mapping reference:** command-receipt operation/path/symbol naming은 `16 Repository Architecture`가 소유한다.

### FN-074 Google OAuth 연결·재인증 Coordination

- **상태:** P0
- **기능:** FN-002 계정 연결과 FN-073 재인증은 동일한 Credential boundary와 보안 규칙을 사용해 Google OAuth를 수행할 수 있어야 한다.
- **처리:** Core/UI는 계정·승인 Scope·연결 상태·재인증 필요 여부 같은 bounded metadata만 소비하고, Refresh/Access Token·Authorization Code·PKCE Verifier 원문을 소유하거나 영속하지 않아야 한다. 실제 OAuth browser flow와 Credential 저장/갱신은 Connector Credential boundary 안에서 수행되어야 한다.
- **완료 조건:** 연결과 재인증이 서로 다른 Credential ownership 규칙으로 구현되지 않고, Secret이 UI/Core/SQLite에 노출되지 않는다.
- **Interface/Security authority reference:** `OAuthCredentialPort` 및 MCP Credential Provider, OAuth browser flow·PKCE/state/callback·token exchange·Keyring boundary는 `07 Interface`와 `09 Security`가 소유한다.
- **Infrastructure authority reference:** OAuth deployment/runtime credential environment는 `10 Infrastructure`가 소유한다.
- **Domain authority reference:** 재인증 필요 상태와 resume lifecycle은 `04 Domain · DB` + State Transition Contract가 소유한다.
- **Repository mapping reference:** connection/credential/keyring Port·Adapter와 use-case placement/naming은 `16 Repository Architecture`가 소유한다.

### FN-075 실행 Claim 증명

- **상태:** P0
- **기능:** 승인된 Action을 실제 외부 Write로 넘길 때는 현재 승인과 실제 실행 요청이 동일한 Action·Tool·Arguments에 대한 것임을 증명하는 서버 발급형, 짧은 수명의 1회용 실행 권위가 필요하다.
- **완료 조건:** 다른 Action/승인/실행 시도/Tool/Arguments에 실행 권위를 재사용할 수 없고, Browser나 LLM이 이 실행 권위를 임의 생성할 수 없다.
- **Domain authority reference:** Claim 가능 상태·Claim Command/Guard·Attempt binding은 `04 Domain · DB` + State Transition Contract가 소유한다.
- **Interface/Security authority reference:** claim token의 exact payload/hash/signature/TTL/service-instance binding/validation은 `07 Interface`와 `09 Security`가 소유한다.
- **Repository mapping reference:** claim issuance/validation operation placement·naming은 `16 Repository Architecture`가 소유한다.

### FN-076 대화 이름 변경

- **상태:** P1
- P0에서는 최초 USER 요청을 기반으로 대화 생성 시 한 번 자동 생성한 title을 표시하며 이름 변경 API를 제공하지 않는다. title은 이후 같은 Conversation에 추가되는 후속 요청이나 업무적으로 무관한 새 요청으로 자동 재생성하거나 최신 메시지로 덮어쓰지 않는다.

### FN-077 대화 삭제

- **상태:** P1
- P0에서는 대화·Run 삭제 API를 제공하지 않는다. 보존 기간·완전 삭제는 설정·Uninstall 정책을 따른다.

### FN-078 대화 이력 조회

- **상태:** P0
- **사용자 목적:** 오른쪽 Conversation 목록에서 과거 대화를 선택해 저장된 USER/ASSISTANT Message와 Run 진행 이력을 중앙 Timeline에 복원한다.
- **입력:** `conversation_id`.
- **처리:** Local API의 bounded Conversation History Query로 저장 Message와 Run metadata를 시간순으로 조회한다. Message/Run 조회 상한은 `10 Infrastructure`의 configured `HISTORY_MESSAGE_LIMIT` / `HISTORY_RUN_LIMIT`을 사용하며 Message가 configured bound를 넘으면 `truncated=true`를 반환한다. exact 숫자는 기능/architecture invariant가 아니다.
- **출력:** Conversation 정보, Message `id/run_id?/role/content/created_at_ms`, Run `run_id/status/started_at_ms/finished_at_ms?`, `truncated`.
- **예외:** 존재하지 않는 Conversation은 404.
- **완료 조건:** 과거 Timeline을 표시하되 조회 자체가 Domain State나 LangGraph Checkpoint를 변경하지 않는다. History는 새 Run의 암묵적 Prompt Context가 아니며 새 요청 전송 Payload에 자동 포함하지 않는다.
