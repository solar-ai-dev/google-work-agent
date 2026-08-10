# 01-A. Google Work Agent 기능 정의서

> **상태:** Draft v2.8 · **기준일:** 2026-08-10

## 1. 문서 목적

이 문서는 사용자가 사용할 수 있는 기능과 시스템 내부 기능을 식별 가능한 단위로 정의한다. 각 기능은 기능 ID, 사용자 목적, 선행 조건, 입력, 처리, 출력, 예외, 완료 조건을 가진다.

## 2. 기능 상태

| 상태 | 의미 |
|---|---|
| P0 | MVP 필수 |
| P1 | P0 안정화 후 추가 |
| EXP | 실험 Runner에서 비교 후 제품 반영 |
| OUT | 제품 범위 제외 |

## 3. 기능 목록 요약

| 영역 | 기능 |
|---|---|
| 설정 | 첫 실행, Google 로그인, OAuth 환경, Runtime 진단, 배포 프로필, 기본 Resource 선택 |
| 요청 | 자연어 입력, 범위 지정, 실행 취소, Run 재개 |
| Context | Source 선택, 검색, 정규화, Evidence, 재검색, Gmail 첨부파일 Metadata 조회·사용자 요청 시 다운로드 |
| 분석 | 관계 연결, 중복, 충돌, 업무 가능성 |
| 계획 | Action Plan, DAG, Draft 생성, 위험 표시 |
| 승인 | 전체·부분 승인, 수정, 거절, 승인 만료 |
| 실행 | MCP Tool 호출, Idempotency, 부분 실행, Gmail Draft·Send 첨부파일 전달 |
| 검증 | GET 재조회, 필드 비교, Recovery |
| 관측 | Trace, Audit, 오류 진단 |
| 실험 | API 호출 예산 통제, 모델·Graph·Retrieval 비교, sLLM 실험 분리 |

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
- **사용자 목적:** OAuth Client 파일을 준비하지 않고 Google 계정만 연결한다.
- **입력:** `Google로 로그인` 버튼, Google 계정 선택, Scope 동의.
- **처리:** 앱에 포함된 개발팀 소유 Desktop OAuth Client → 시스템 브라우저 → PKCE·state → `127.0.0.1` loopback callback → Token 교환 → Refresh Token을 OS Keyring에 저장.
- **출력:** 활성 Google 계정, 연결된 서비스, 승인 Scope, OAuth 환경(개발·스테이징·운영).
- **예외:** 동의 취소, Scope 일부 거절, Test User 미등록, 검증되지 않은 앱 경고, Token 갱신 실패.
- **Scope 규칙:** P0 필수 Scope 하나라도 거절되면 연결을 완료 처리하지 않고 Agent Run과 Google Tool을 차단한다.
- **완료 조건:** 모든 P0 필수 Scope가 승인되고 Gmail·Tasks·Calendar 읽기 테스트가 성공한다.
- **주의:** 로그인은 사용자 인증과 권한 승인을 함께 포함한다. `openid` 로그인만으로 Workspace API를 호출하지 않는다.

### FN-003 Google 계정 연결 해제

- **상태:** P0
- **처리:** OS Keyring Credential 삭제, 앱의 활성 계정 상태 초기화.
- **출력:** 재인증 필요 상태.
- **완료 조건:** 기존 Credential로 Google API를 호출할 수 없다.

### FN-004 LLM Runtime 진단

- **상태:** P0
- **입력:** 하드웨어, Ollama 상태, 설치 모델, API Key.
- **처리:** CPU-only 여부, GPU 기준 충족, Ollama 연결, Local 테스트 추론, API 연결을 확인한다.
- **출력:** 사용 가능한 모드, 배포 프로필, 고정된 실행 모드.
- **규칙:** CPU-only 또는 GPU 기준 미달은 API_LLM 고정. Local 제품 Runtime은 Ollama만 지원한다. 앱은 Ollama·Model을 설치·시작·종료·업데이트하지 않고 존재·Version·승인 Model 상태만 진단한다.

### FN-005 LLM 모드 선택

- **상태:** P0
- **선행 조건:** Runtime 진단 완료.
- **처리:** API_ONLY에서는 API_LLM만 표시한다. LOCAL_CAPABLE과 검증된 GPU에서는 AUTO, LOCAL_GPU, API_LLM을 표시한다.
- **출력:** 사용자 선택 모드와 실제 실행 모드.
- **완료 조건:** P0에서 API와 Local 모드를 모두 사용할 수 있다.

### FN-006 배포 프로필 선택

- **상태:** P0 배포 기능
- **프로필:** `API_ONLY`, `LOCAL_CAPABLE`.
- **API_ONLY:** Ollama 의존성 없이 실행하며 GPU가 없는 팀원과 CPU-only 사용자에게 제공한다.
- **LOCAL_CAPABLE:** Ollama Adapter, GPU·Runtime 진단, 승인 Model Manifest와 설치 안내 UI만 포함한다. Ollama·Model·실험 Runner·후보 모델은 Bundle하지 않는다.
- **완료 조건:** 동일 Core Code와 Policy를 사용하면서 Artifact 의존성과 Runtime 진단 경계가 분리된다.

### FN-007 OAuth 배포 환경 관리

- **상태:** P0 개발·운영 기능
- **처리:** 개발·스테이징·운영 Google Cloud 프로젝트와 OAuth Client를 분리한다.
- **팀 테스트:** Test User 등록, External + Testing Refresh Token 7일 만료 재로그인 안내.
- **운영:** 검증된 OAuth Client와 동의 화면만 사용한다.

### FN-008 Local Agent Service 시작

- **상태:** P0
- **사용자 목적:** 별도 명령어나 서버 설정 없이 앱을 실행한다.
- **입력:** Launcher 실행.
- **처리:** 동적 Local Port 선택 → FastAPI Process 시작 → `/health/live` → Manifest·Asset·API Contract·SQLite·Migration·Domain·Keyring Adapter·MCP Core Readiness → `/health/ready` → React UI Open → Local Session 이후 `/api/v1/runtime`에서 Google·LLM·Ollama 상세 진단.
- **출력:** Local Service 상태, UI URL, 진단 결과.
- **예외:** 포트 확보 실패, Service 시작 실패, DB Safe Mode, Frontend Asset 누락.
- **완료 조건:** `127.0.0.1`의 동일 Origin에서 React UI와 `/api/v1`이 사용 가능하다.

### FN-009 Frontend·API 세션과 버전 확인

- **상태:** P0
- **입력:** Launcher Bootstrap Secret, Frontend Build Version, API Contract Version.
- **처리:** 일회성 Bootstrap 검증 → Local Session 수립 → Frontend·Backend Version Compatibility 검사.
- **출력:** Session 상태, API Version, 지원 기능 목록.
- **예외:** Bootstrap 재사용, Origin·Host 불일치, Version 비호환.
- **완료 조건:** 호환되고 인증된 Frontend만 변경 Command와 Event Stream을 사용할 수 있다.

## 5. 요청 기능

### FN-010 자연어 요청 입력

- **상태:** P0
- **입력:** 한국어 또는 영어 자연어, 선택적 Query·기간·사람·이메일·Keyword, 선택된 Gmail·Task·Event Resource.
- **처리:** 요청을 `AGENT_SEARCH` 또는 `RESOURCE_SELECTED` 진입 방식으로 구분하고 Run과 LangGraph Thread ID를 생성한다.
- **출력:** 진입 방식, 처리 단계, 현재 Source, 진행 상태.
- **예외:** Runtime 미설정, Google 연결 없음.

### FN-011 요청 범위 제한

- **상태:** P0
- **입력:** 기간, Source 선택, 특정 Resource.
- **처리:** 사용자가 지정한 범위를 검색 계획의 상한으로 적용한다.
- **완료 조건:** 범위 밖 자료가 필요하면 조회 전에 추가 Source·기간과 이유를 제안하고 사용자 확인을 받는다. 사용자 확인 없이 지정 범위를 확대하지 않는다.

### FN-012 실행 취소

- **상태:** P0
- **처리:** 현재 읽기·LLM 단계는 중단하고 Checkpoint를 남긴다. 실행 중인 Google 쓰기는 결과 조회 후 상태를 확정한다.
- **출력:** 취소된 단계와 이미 완료된 Action.

### FN-013 Run 재개

- **상태:** P0
- **처리:** SQLite Checkpoint와 Thread ID로 마지막 안전 지점에서 재개한다.
- **완료 조건:** 승인 상태와 완료 Action이 중복 실행되지 않는다.

### FN-014 사이드바 목록 조회

- **상태:** P0
- **사용자 목적:** Gmail·Tasks·Calendar의 현재 항목을 목록으로 탐색한다.
- **입력:** Source, 검색·필터 조건, Page Token.
- **처리:** 페이지당 10~20개를 Google API에서 조회하며 P0 기본값은 20개로 한다.
- **정렬:** Gmail 최근 수신 순, Tasks 미완료·기한 임박 우선, Calendar 가까운 예정 일정 순.
- **출력:** 목록 Metadata, 다음 Page Token, 마지막 조회 시각.
- **완료 조건:** 사용자가 원본 전체를 로컬 DB에 저장하지 않고 최신 목록을 탐색할 수 있다.

### FN-015 Frontend 페이지 메모리 캐시

- **상태:** P0
- **처리:** 조회된 목록 페이지와 Page Token을 Google 계정·Source·검색 조건·정렬·Page Token 조합으로 React Client Session Cache에 저장한다.
- **재사용:** 이미 조회한 페이지로 돌아가면 API를 다시 호출하지 않고 메모리 결과를 표시한다.
- **폐기:** UI 세션 종료, Google 계정 변경, 해당 Source 수동 새로고침 시 폐기한다.
- **제한:** Frontend Page Cache는 승인·중복·충돌·검증 판단의 기준점이 아니며 SQLite에 영구 저장하지 않는다.

### FN-016 사용자 선택형 요청

- **상태:** P0
- **입력:** 사이드바에서 선택한 하나 이상의 Gmail·Task·Event Resource와 자연어 요청 또는 빠른 Action.
- **처리:** 선택된 Resource ID의 최신 상세를 조회하고 이를 초기 Context로 사용한다. 추가 Source 검색은 요청 수행에 필요한 경우에만 확장한다.
- **출력:** 선택 Resource 기반 Context, 분석 결과 또는 Action Plan.
- **완료 조건:** 사용자가 Resource의 사람·날짜·제목을 다시 입력하지 않고 요청을 수행한다.

### FN-017 Agent 검색형 요청

- **상태:** P0
- **입력:** Query, 날짜·기간, 사람·이메일, Keyword 또는 복합 자연어 요구사항.
- **처리:** 검색 조건 구조화 → Source 선택 → Source-native 목록 검색 → 후보 축소 → 필요한 후보 상세 조회 → Context 구성.
- **출력:** 검색 근거와 관련 Resource, 분석 결과 또는 Action Plan.
- **제한:** 검색 결과 전체를 LLM에 전달하지 않고 Metadata와 일반 코드로 후보를 줄인다.
- **완료 조건:** 직접 Resource를 선택하지 않아도 요청 조건에 맞는 Google 데이터를 탐색할 수 있다.

### FN-018 Run Event Stream 구독·복구

- **상태:** P0
- **입력:** Run ID, 마지막 Event Cursor.
- **처리:** SSE 구독 → 진행·질문·계획·실행·검증 Event 반영 → 연결 단절 시 Cursor 재구독 또는 Run Snapshot 재조회.
- **출력:** 현재 Run 상태와 화면 갱신 Event.
- **예외:** Cursor 만료, Local Session 만료, Service 재시작.
- **완료 조건:** 브라우저 새로고침이나 일시적 연결 단절 후에도 Domain 상태를 추정하지 않고 화면을 복구한다.

## 6. Context·Retrieval 기능

### FN-020 Source 선택

- **상태:** P0
- **입력:** 구조화된 목표·완료 조건, 요청 진입 방식, 선택된 Resource.
- **처리:** `RESOURCE_SELECTED`에서는 선택된 Source를 시작점으로 사용하고 필요한 경우에만 다른 Source를 확장한다. `AGENT_SEARCH`에서는 Gmail·Tasks·Calendar 중 필요한 Source와 순서를 선택한다.
- **출력:** Retrieval Plan.
- **예외:** 선택된 Resource를 다시 검색해 찾거나 근거 없이 전체 Source를 항상 선택하지 않는다.

### FN-021 Gmail 검색·조회

- **상태:** P0
- **입력:** 검색 Query, 기간, 참여자, Thread ID.
- **처리:** Thread 목록 조회 → Message 조회 → HTML 정리 → 인용·서명 제거.
- **출력:** 정규화된 Gmail WorkItem과 Evidence.

### FN-022 Tasks 검색·조회

- **상태:** P0
- **입력:** Task List, 상태, 기한, Keyword.
- **처리:** 기본·선택 List의 미완료 Task를 조회하고 정규화한다.
- **출력:** Task WorkItem.

### FN-023 Calendar 조회·FreeBusy

- **상태:** P0
- **입력:** 기간, Calendar 목록.
- **처리:** Event 조회와 FreeBusy 결과를 병합한다.
- **출력:** Event WorkItem, Busy Interval, 가용 Slot 후보.

### FN-024 Context 정규화

- **상태:** P0
- **처리:** Source별 결과를 공통 WorkItem·Evidence Schema로 변환한다.
- **완료 조건:** Source, Resource ID, 제목, 시간, 사람, 상태, 원본 링크가 보존된다.

### FN-025 Chunking

- **상태:** P0
- **대상:** 긴 Gmail Thread.
- **처리:** 메시지 경계를 우선하고 길이 초과 시 Token 기준으로 나눈다.
- **출력:** Chunk ID, Message ID, 원본 위치.

### FN-026 재검색

- **상태:** P0
- **처리:** Context 충분성 판단 실패 시 Query·기간·Source를 수정해 최대 2회 다시 조회한다.
- **출력:** 재검색 이유와 추가 Evidence.

### FN-027 사용자 확인 질문

- **상태:** P0
- **조건:** 동일 이름 후보, 불명확한 기간, 예상 시간 누락, 의미가 다른 후보가 복수인 경우.
- **출력:** 선택 가능한 후보와 차이.

### FN-028 Embedding·Reranking

- **상태:** EXP
- **설명:** Source-native 결과의 재정렬 방식은 실험 후 제품 적용 여부를 결정한다.

## 7. 분석 기능

### FN-030 Resource 관계 연결

- **상태:** P0
- **처리:** 제목, 참여자, Thread, 시간, Resource 링크, Semantic 정보로 Mail·Task·Event 관계를 계산한다.
- **출력:** 관계 유형, 신뢰도, Evidence.

### FN-031 Task 중복 검사

- **상태:** P0
- **처리:** 제목·사람·Thread·기한·상태를 비교한다.
- **출력:** 중복 차단, 중복 경고, 신규 허용.

### FN-032 Calendar 충돌 검사

- **상태:** P0
- **처리:** Busy Interval, 작업 시간, Buffer, 기존 Event를 비교한다.
- **출력:** 충돌 없음, 경고, 차단.

### FN-033 업무 가능성 판단

- **상태:** P0
- **입력:** 마감, 예상 소요시간, 가용 Slot, 사용자 업무 시간.
- **출력:** 가능, 위험, 불가능 및 근거.
- **예외:** 예상 시간이 없으면 Event를 자동 제안하지 않고 확인 질문을 한다.

## 8. 계획 기능

### FN-040 Action Plan 생성

- **상태:** P0
- **출력:** Action ID, Tool, Arguments, Evidence, Risk, Dependency, Expected Result.
- **완료 조건:** 모든 쓰기 Action에 Evidence가 존재한다.

### FN-041 Action DAG 생성

- **상태:** P0
- **처리:** 선행·후행 관계와 독립 실행 가능 여부를 정의한다.
- **예시:** Task 생성 후 해당 Task를 참조하는 Event 생성.

### FN-042 Gmail Draft 제안

- **상태:** P0
- **입력:** 기존 Thread, 실제 업무 가능성, 사용자 목표.
- **출력:** 수신자, CC, 제목, 본문, Thread 연결.
- **규칙:** `초안`, `문구`, `작성만`, `검토용`은 Draft다. `답장해줘`, `회신해줘`, `보내줘`, `전송해줘`는 SEND 의도이며 최종 수신자·CC·제목·본문·Thread를 고정한 뒤 승인으로 진행한다.

### FN-043 Task 제안

- **상태:** P0
- **출력:** 제목, 메모, 기한, Task List.
- **제한:** 정확한 Task 완료 상태 변경과 Task 삭제는 사용자 승인 후 허용한다. Task 삭제는 `DELETE`로 처리하고 실행 후 대상 부재를 검증한다.

### FN-044 작업 Event 제안

- **상태:** P0
- **출력:** 제목, 시작·종료, 설명, Calendar.
- **규칙:** 정확한 Event 삭제와 참석자 추가·수정을 승인형 Write로 지원한다. 반복 Event 전체 일괄 수정은 지원하지 않는다.

## 9. 승인 기능

### FN-050 Context Preview

- **상태:** P0
- **기능:** 계획 생성 전 사용된 Context와 제외 가능한 항목을 보여준다.

### FN-051 Action 승인

- **상태:** P0
- **기능:** 전체 승인, 시스템별 승인, Action별 승인을 지원한다.

### FN-052 Action 수정

- **상태:** P0
- **수정 가능:** Draft 수신자·CC·제목·본문, Task 제목·메모·기한, Event 제목·시간·설명.
- **처리:** 수정 후 Schema·Policy·중복·충돌을 다시 검사한다.

### FN-053 Action 거절

- **상태:** P0
- **처리:** 종속 Action을 차단하고 필요한 경우 계획을 다시 계산한다.

### FN-054 승인 Token 발급

- **상태:** P0
- **처리:** Canonical Arguments Hash와 만료 시간을 포함한 Token을 생성한다.

## 10. 실행 기능

### FN-060 MCP Tool 실행

- **상태:** P0
- **처리:** Approval Token 검증 → Tool Schema 검증 → Google API 실행.
- **출력:** Resource ID, 상태, Google 응답 Metadata.

### FN-061 Idempotency

- **상태:** P0
- **처리:** 동일 Action의 재실행 전에 기존 실행 결과와 Resource 존재 여부를 조회한다.

### FN-062 부분 실행

- **상태:** P0
- **처리:** 독립 Action은 계속 실행하고 종속 Action은 선행 결과에 따라 차단한다.

## 11. 검증·복구 기능

### FN-070 실행 결과 검증

- **상태:** P0
- **처리:** 생성·수정 Resource를 GET으로 다시 읽고 expected와 actual을 필드별 비교한다.

### FN-071 정상화 비교

- **상태:** P0
- **정상화:** 공백, 줄바꿈, Timezone 표현, 초 단위, Google 기본값.

### FN-072 Mismatch Recovery

- **상태:** P0
- **처리:** 핵심 필드 불일치 시 자동 수정하지 않고 사용자에게 차이와 Recovery Action을 제시한다.

### FN-073 OAuth 재인증 후 재개

- **상태:** P0
- **처리:** Token 갱신 실패 시 Checkpoint를 저장하고 재인증 후 동일 Thread를 재개한다.

## 12. 관측성 기능

### FN-080 Run Trace

- **상태:** P0
- **내용:** Node, Tool, Source 수, Provider, 모델, fallback, Latency, Token, 상태, API Command ID, Event Cursor.
- **제외:** Secret, 전체 OAuth Token, 전체 API Key.

### FN-081 Audit Log

- **상태:** P0
- **내용:** 승인, 수정, 거절, 실행, 검증, Policy 차단.
- **특성:** 앱 UI에서 수정할 수 없는 append-only 기록.

### FN-082 사용자 진단 화면

- **상태:** P0
- **내용:** Launcher, React Build, Local Agent API, Local Session, Google 연결, MCP 프로세스, LLM Runtime, SQLite, SSE 연결, 최근 오류.

## 13. 평가·실험 기능

### FN-090 Experiment Runner

- **상태:** P0 개발 도구
- **기능:** Dataset, Model, Prompt, Graph, Retrieval Config를 조합해 반복 실행한다.
- **API 제한:** 요청 수, 입력·출력 Token, 예상 비용, RPM, TPM, 동시성, Retry 한도를 Config로 강제한다.
- **단계:** Smoke 5 Case → Screening 20 Case → Finalist Full 60 Case.
- **중단:** 예산·요청 상한 또는 Provider Quota 위험에 도달하면 새 호출을 중단한다.

### FN-091 평가 리포트

- **상태:** P0 개발 도구
- **출력:** Source·Tool·Argument Accuracy, E2E, Latency, Cost, VRAM, 실패 유형.

### FN-092 제품 설정 채택

- **상태:** P0 Release 기능
- **처리:** 실험 결과와 Release Gate를 통과한 API·Local 모델 Config만 제품 기본값으로 고정한다.
- **제약:** P0 Local 기능은 제공하지만 실험 후보 전체를 사용자에게 노출하지 않는다.

### FN-093 sLLM 실험 분리

- **상태:** P0 개발 도구
- **처리:** GPU 전용 sLLM 실험 Runner, 후보 모델, Raw Result를 제품 배포와 별도 디렉터리·Artifact로 관리한다.
- **팀 분업:** GPU가 없는 팀원은 API_ONLY·Mock·고정 Fixture로 Core 기능을 개발하고 GPU 팀원만 Local 모델 벤치마크를 수행한다.
- **완료 조건:** 실험 환경이 없어도 API_ONLY 제품 빌드와 전체 정책·Tool 테스트가 통과한다.

## 14. 범위 제외 기능

| ID | 기능 | 상태 |
|---|---|---|
| P0-WRITE-001 | Gmail 승인형 전송 | P0 |
| OUT-002 | Gmail Message·Thread 원문 삭제 | OUT |
| P0-WRITE-002 | Google Task·Calendar Event 승인형 삭제 | P0 |
| P0-WRITE-003 | Calendar 참석자 승인형 추가·수정 | P0 |
| OUT-004 | CPU Local LLM | OUT |
| OUT-005 | 원격 SaaS·멀티 사용자·외부 공개 API | OUT |
| OUT-006 | 백그라운드 자동 실행 | OUT |
| OUT-007 | Gmail·Tasks·Calendar 전체 데이터의 로컬 상시 복제 | OUT |
| OUT-008 | 페이지 이동마다 이미 조회한 목록을 다시 호출하는 동작 | OUT |

## 15. Google Source 데이터 수명주기

1. **목록:** 사이드바 표시를 위해 Local API가 Google API에서 페이지 단위로 조회하고 React Client Session Cache에 유지한다.
2. **상세:** 사용자가 Resource를 클릭·선택하거나 Agent가 후보를 확정했을 때 필요한 항목만 조회한다.
3. **LLM Context:** 현재 Run 수행에 필요한 상세 내용만 메모리에서 사용한다.
4. **영구 기록:** 실제 판단과 승인에 사용된 Resource ID, 원본 링크, 최소 Metadata, Evidence excerpt만 SQLite에 저장한다.
5. **최신성:** 계획 확정 전, 승인 후 실행 직전, 실행 직후 Google API로 대상 Resource를 다시 조회한다.


## 16. Frontend · Local API 기능 경계

1. React Frontend는 사용자 입력, 화면 상태, Sidebar Page Cache와 Event 렌더링을 담당한다.
2. FastAPI Route는 Request Schema와 Local Session을 검증한 뒤 Application Service를 호출한다.
3. Application Service는 Run·Approval·Execution·Recovery Command를 조정한다.
4. LangGraph는 Workflow를 진행하지만 Domain 상태를 직접 SQL로 수정하지 않는다.
5. SSE Event는 화면 갱신용이며 승인·실행 사실의 기준점이 아니다.
6. UI 재요청과 네트워크 Retry는 Command ID·Version·Idempotency로 중복 적용을 차단한다.

## 17. Multi-Agent 기능

### FN-100 Supervisor Routing
현재 Workflow Phase, Agent Result, Domain Command Result와 호출 예산을 입력으로 받아 다음 Agent Subgraph·Interrupt·종료 경로를 결정한다. Agent Subgraph는 다른 Agent를 직접 호출하지 않고 Supervisor로 Typed Result를 반환한다.

### FN-101 요청 이해 Agent
목표·완료 조건·기간·사람·Source·제약·모호성을 Structured Output으로 생성한다. Google 조회와 Action Plan 확정은 수행하지 않는다.

### FN-102 Retrieval Agent
Source·검색 전략·추가 검색 필요성을 제안한다. 실제 Gmail Query·날짜 범위·Page Token·MCP 인자는 결정적 Query Builder와 Adapter가 확정한다.

### FN-103 업무 분석 Agent
업무 의미, Resource 관계, 누락 업무, 중복 후보, 일정 제약과 마감 위험을 분석한다. 최종 중복·충돌·정책 판정은 일반 코드가 수행한다.

### FN-104 해결책·계획 Agent
Evidence 기반 해결책, Action DAG, Arguments 초안, Risk와 Expected Result를 생성한다. 승인·실행·Domain Row 변경은 금지한다.

### FN-105 계획 검토 Agent
목표 충족, 근거 누락, 과잉 작업, 모순, Dependency 오류와 Unsupported Action을 독립 검토하고 `PASS`, `REVISE`, `RETRIEVE_MORE`, `CONFIRM`, `BLOCK` 중 하나를 반환한다.

### FN-106 Typed Handoff·Checkpoint
Agent Input·Result Schema Version을 검증하고 `resource_ref_id`, `evidence_id`, `segment_id` 기반으로 필요한 Context만 전달한다. 각 Agent Subgraph는 호출 단위 Local State와 bounded validation·repair/revision loop를 가질 수 있으나 자유 텍스트 Agent 대화와 Agent별 독립 장기 Memory는 금지한다.

### FN-107 응답 조립
Supervisor가 검증된 분석·Plan·실행·검증 결과를 사용자 응답으로 조립한다. 내부 Agent 대화와 비공개 추론은 사용자에게 노출하지 않는다.

## 18. Agent 실행 기능

### FN-108 API 탐색·수집 Agent
`RequestIntent`와 API Budget으로 Source·조회 순서·Page·후보·상세 예산을 제안한다. 일반 코드가 Query를 검증하고 MCP 읽기를 실행한다.

### FN-109 Context Retriever Agent
수집 Resource에서 Segment·Evidence를 선별하고 Token Budget과 충분성을 판정한다. Google API·MCP는 직접 호출하지 않는다.

### FN-110 Answer-only Run 완료
Plan·Action이 없는 조회·분석 결과는 `complete_answer_only_run`으로 종료한다.

### FN-111 READ-only Plan
명시적 READ 작업만 Action으로 저장하며 승인 없이 Plan을 활성화한다.

### FN-112 READ 실패
Output Schema 실패나 복구 불가능한 읽기 오류는 `fail_read_action`으로 `FAILED` 처리한다.

### FN-113 Write 재시도 준비
Write `FAILED`는 `prepare_write_retry`로 `MODIFIED` 전환 후 새 승인을 받아야 한다. `UNKNOWN_RESULT`에서는 Retry를 금지한다.

### FN-114 결정적 Supervisor
Supervisor는 Phase, Agent Result, Domain Result와 Budget으로만 Routing한다.


---

## 19. Local Command·Connection 보완 기능

> 문서 권위는 `01 PRD §1.1`의 Concern Owner 규칙을 따른다. 이 절은 기능 동작만 정의하며 안전·Domain·Tool 계약을 완화하지 않는다.


### FN-019 Command Receipt

- **상태:** P0
- **입력:** `command_id`, `command_type`, 요청 Canonical Hash, 대상 Aggregate와 `expected_version`.
- **처리:** Command 실행 전 Receipt 예약 → Domain 변경과 결과를 같은 Transaction으로 완료 → 재전송 시 저장된 결과 반환.
- **충돌:** 같은 `command_id`에 다른 Request Hash가 오면 `DUPLICATE_COMMAND`로 차단한다.
- **완료 조건:** 응답 유실·Service 재시작·중복 클릭이 Domain 전이를 두 번 적용하지 않는다.

### FN-074 Google OAuth 연결 Coordinator

- **상태:** P0
- **처리:** React → FastAPI Connection Command → Application `ConnectionService` → MCP Credential Port → MCP Credential Provider → Google OAuth·OS Keyring.
- **출력:** 계정 ID, 이메일, 승인 Scope, 연결 상태, 재인증 필요 여부.
- **제한:** FastAPI·React·SQLite는 Refresh Token 원문을 받거나 저장하지 않는다.

### FN-075 실행 Claim 증명

- **상태:** P0
- **처리:** Domain Claim Commit 후 Service Instance에 바인딩된 짧은 TTL의 1회용 `claim_token`을 생성하고 MCP Write Tool이 재검증한다.
- **완료 조건:** Action·Approval·Attempt·Tool·Arguments Hash가 모두 일치할 때만 Write가 가능하다.

### FN-076 대화 이름 변경

- **상태:** P1
- P0에서는 자동 생성 제목을 표시하며 이름 변경 API를 제공하지 않는다.

### FN-077 대화 삭제

- **상태:** P1
- P0에서는 대화·Run 삭제 API를 제공하지 않는다. 보존 기간·완전 삭제는 설정·Uninstall 정책을 따른다.

## 20. Clarification·승인형 Write 기능
### Clarification
- 요청만으로 모호하면 Request Understanding에서 확인한다.
- 검색 후 복수 후보·저신뢰가 드러나면 Retrieval 이후 확인한다.
- 분석 후 관계·충돌이 불명확하면 Work Analysis 이후 확인한다.
- 후보가 있으면 후보 라벨·차이·Resource Ref를 선택지로 제공한다.
- `처리/진행/시작/정리/마무리`는 이전 대화·선택 Resource로 의미가 단일하면 추가 질문하지 않는다.

### 승인형 Write
- `SEND`: Gmail 실제 전송.
- `UPDATE`: Task 완료, Calendar 참석자 변경 포함.
- `DELETE`: Calendar Event 삭제.
- Gmail Message·Thread 원문 삭제는 OUT 유지. Google Task 삭제는 승인형 `DELETE`로 지원한다.
### FN-115 Agent Subgraph 실행 계약

- **상태:** P0
- **처리:** Supervisor가 Profile Registry에 따라 Agent Subgraph를 호출한다. Subgraph는 Parent State에서 필요한 입력만 projection하고, 자신의 Local State에서 LLM 호출·Schema Validation·허용된 Repair/Revision을 수행한다.
- **출력:** Versioned Typed Result와 disposition만 Parent Graph에 반환한다.
- **상태 수명:** Local State는 해당 invocation이 끝나면 장기 기억으로 승격하지 않는다. Run 재개에 필요한 공식 결과만 Main Graph Checkpoint에 남긴다.
- **완료 조건:** Agent 간 직접 호출 0, Local State의 Domain 사실 승격 0, bounded loop 상한 준수.

## v2.7 Frontend 구현 전 Canonical 보완

이 절은 v2.7에서 Frontend UI 계약을 구체화하며, 기존 기능 정의 중 이 절과 상충하는 화면 표현·UI 페이지 단위는 이 절을 우선한다. 제품 범위, 정책, REST/SSE 및 Workflow 계약은 변경하지 않는다.

### Sidebar 목록과 숫자 페이지

- Sidebar UI의 기본 요청·표시 단위는 **10개**다. `RETRIEVAL_PAGE_SIZE=20`은 Agent Retrieval Budget이며 Sidebar UI 값이 아니다.
- Google Page Token API를 유지한다. React Session Memory는 조회 조건별 `pageNumber → request page token / result / next page token`을 연결해 `< 1 2 3 4 5 >` 형식의 숫자 페이지를 제공한다.
- 미조회 페이지는 앞 페이지의 next token으로 순차 획득하고, 조회 완료 페이지는 cache에서 표시한다. offset Backend나 전체 목록 선조회·집계는 요구하지 않는다.
- 검색·필터·정렬·Source·Google 계정 변경 또는 수동 새로고침 시 관련 page mapping을 비우고 1페이지부터 조회한다. cache와 page 번호는 Domain authority나 영속 상태가 아니다.
- 목록 기본 표현은 Card가 아닌 keyboard-navigable compact list row다. 제목, 제공되는 발신자/소유자, 시간·상태, snippet을 2~3줄로 표시하고 긴 문자열은 ellipsis 처리한다.

### Resource 선택과 Viewer

- Viewer의 **Focus Resource**와 Agent Context의 **선택 Resource 집합**을 분리한다. 행을 열면 Focus를 갱신하고, 기존 다중 선택 기능은 보존한다.
- `RESOURCE_SELECTED`는 선택 Resource ID로 최신 상세를 조회하는 진입 방식이다. 해당 Resource를 다시 검색해 찾지 않고, 추가 Source 검색은 요청 수행에 필요할 때만 확장한다.
- `AGENT_SEARCH`는 Resource를 먼저 선택하지 않은 자연어 요청의 진입 방식이다. Source 및 검색 조건은 Workflow가 결정한다.
- Quick Action은 선택 Resource와 사용자 의도를 Agent 요청으로 전달할 뿐 Google Write를 직접 실행하지 않는다. Write는 기존 Approval 흐름을 따른다.
- Viewer와 목록에는 현재 REST/SSE Projection이 제공하는 제목·metadata·상세 필드만 표시한다. count, 전체 본문, 첨부파일 상세, 최근 실행, 승인 상세를 Frontend가 추정·생성·집계하지 않는다.

### Main UI 보조 기능

- 대화 선택은 중앙 Conversation을 복원한다. 대화 목록은 Resource type으로 분류하지 않으며 Source icon은 보조 표식일 뿐 대화의 분류 기준이 아니다.
- Recent Execution은 실제 Projection이 있을 때만 표시하고, 없으면 숨기거나 Empty State를 보인다. Fake history를 만들지 않는다.
- Settings/Diagnostics는 Drawer 또는 Dialog이며, Main에는 사용자 이해에 필요한 Google 연결 상태와 진행 상태만 표시한다. Runtime/Model/Node/SSE 등 개발자용 상세 문자열은 Settings/Diagnostics에서만 제공한다.
- Browser 기반 P0에서는 minimize/maximize/close를 제품 Window Control 기능으로 정의하지 않는다.

## v2.8 Calendar·Tasks Sidebar 및 Viewer 보완

이 절은 v2.8의 Sidebar 탐색·Viewer Empty State 계약이며, 앞선 Sidebar 화면 표현과 상충하면 이 절을 우선한다. API, 정책, Workflow, Domain 상태 권위는 변경하지 않는다.

### Source별 Sidebar 목록

- Tasks는 실제 Google Workspace Source다. 지원 Projection은 제목, 메모, 기한, Task List, 완료 상태이며, 기본 compact row는 **Task 제목 → 기한** 순서로 표시한다. Task List는 실제 반환된 값만 보조 정보로 사용할 수 있다. 정렬은 미완료·기한 임박 우선 의미를 유지한다.
- Tasks와 Calendar row에는 priority, 임의 category·Task List 이름, 임의 색상 dot·marker·status badge, 내부 Google ID, Page Token을 생성하거나 표시하지 않는다.
- Calendar Event compact row는 **Event 제목 → 시간 범위** 순서다. 같은 날 시간 Event는 `YYYY년 M월 D일 (요일) 오전/오후 h:mm - 오전/오후 h:mm` 형식으로 연·월·일·요일·시작 시간·종료 시간을 표시하고 날짜는 한 번만 표시한다. 날짜가 다르면 시작일과 종료일을 각각 식별 가능하게 표시한다. All-day Event는 `YYYY년 M월 D일 (요일) · 하루 종일` 형식이다.
- Calendar Sidebar에는 `시작`, `종료` label을 표시하지 않는다. 중앙 Viewer의 Event 상세는 제공된 `시작`, `종료` 필드를 유지한다. 선택 상태는 기존 Source row와 같은 background/focus styling으로만 나타낸다.
- `calendar_list_events`의 `time_max`가 필요한 Upcoming 기간 정책은 이 UI 표기 계약에서 결정하지 않는다. 명시된 제품 정책 전에는 임의 기간을 생성하거나 적용하지 않는다.

### Source별 Resource Viewer Empty State

- 중앙 Viewer 제목은 모든 Source에서 `자료 상세`다. Focus가 없을 때 Gmail은 `왼쪽 목록에서 메일을 선택하면 상세 내용을 확인할 수 있습니다.`, Tasks는 `왼쪽 목록에서 태스크를 선택하면 상세 내용을 확인할 수 있습니다.`, Calendar는 `왼쪽 목록에서 일정을 선택하면 상세 내용을 확인할 수 있습니다.`를 표시한다.
- Source 전환은 이전 Source의 Focus와 상세 표시를 제거한 뒤 새 Source의 Empty State 또는 새 Focus 상세를 표시한다.

## R8.4 Gmail 첨부파일 기능

### FN-021A Gmail 첨부파일 조회·다운로드
- **상태:** P0
- **사용자 목적:** Gmail Message에 포함된 첨부파일을 확인하고 원본 파일을 받을 수 있다.
- **입력:** `message_id`, `attachment_id`, 검증된 Local Session.
- **처리:** Message 상세에서 파일명·MIME Type·크기·Google Attachment ID Metadata 확인 → MCP Gmail Attachment Read → Google API bytes 조회 → FastAPI Download Stream.
- **출력:** 원본 bytes와 검증된 `filename`, `mime_type`, `size_bytes`.
- **제한:** 첨부파일 bytes·내용을 LLM Prompt·Context·Evidence로 전달하지 않는다.
- **완료 조건:** LLM 호출 없이 사용자가 선택한 첨부파일을 받을 수 있다.

### FN-042A Gmail Draft·Send 첨부파일
- **상태:** P0
- **입력:** 사용자가 선택한 로컬 파일.
- **처리:** Local Service가 제한된 Staging 경계에 파일 bytes를 수신하고 `staged_attachment_id`, 파일명, MIME Type, 크기, SHA-256 Descriptor를 생성한다. Action·Approval에는 Descriptor만 포함한다. Claim 발급 전과 MCP MIME 조립 직전에 실제 bytes의 크기·SHA-256을 재검증한다.
- **출력:** 첨부파일이 포함된 Gmail Draft 또는 SEND 결과.
- **예외:** Staging 만료·파일 누락·크기/Hash mismatch이면 기존 Approval을 실행하지 않고 파일 재선택→Action 수정→새 Approval로 돌아간다.
- **완료 조건:** 승인된 파일과 실제 전송 파일이 동일하고 기존 SEND Verification 계약을 그대로 수행한다.
