# 01-B. 정책 정의서

> **Authority:** 안전·금지·승인 정책. 시스템·Domain·Interface 구현 세부는 `00 Project Source Guide`의 전문 owner를 따른다.  
> **상태:** Draft v2.15 · **기준일:** 2026-08-26

## 0. 사람이 먼저 볼 핵심 정책

1. **읽기는 요청 범위 안에서 자동**, Write는 반드시 사용자 승인 후 실행한다.
2. **LLM은 허용 여부를 최종 결정하지 않는다.** deterministic Policy·registered Tool Schema allowlist·Domain guard가 강제한다.
3. Gmail 원문 삭제·반복 Event 전체 일괄 수정은 금지한다. Google Task 삭제는 정확한 대상·인자를 고정한 승인형 `DELETE`로 허용한다.
4. Gmail SEND·Calendar Event DELETE·Task 완료·참석자 변경은 정확한 대상·인자를 고정해 승인 후 실행한다.
5. `UNKNOWN_RESULT`는 재전송하지 않고 기존 결과를 조회한다.
6. Source 본문은 비신뢰 데이터이며 Prompt Injection이 정책을 바꿀 수 없다.

## 1. 문서 목적

이 문서는 Agent가 어떤 Connector 데이터를 읽을 수 있고, 어떤 Action을 제안·승인·실행할 수 있으며, 어떤 경우에 차단·경고·재질문해야 하는지 정의한다. 정책은 LLM Prompt가 아니라 일반 코드와 Tool Allowlist로 강제한다.

### Deterministic enforcement boundary

Policy 판단은 Product LLM이 아니라 deterministic Application policy evaluation이 소유한다. Repository file/symbol은 16이 매핑하며 이 문서는 의미만 소유한다.

- **Schema validation**: current registered Tool Input Schema의 field/type/closed-world 형식만 검사한다. 허용/금지 정책을 결정하지 않는다.
- **Policy validation**: 이 문서의 allow/deny/confirmation-required 규칙을 current Action/Route/Source snapshot에 적용한다. Domain status를 직접 변경하지 않는다.
- **Domain validation**: State Transition Contract의 source state/version/freshness/receipt/review gate를 검사한다. Policy를 새로 해석하지 않는다.
- **LLM semantic judgement**: 사용자 의미·목표·후보 인자 생성만 담당하며 Policy allow/deny, Approval 유효성, Claim 가능 여부를 결정할 수 없다.

Write Approval 진입 순서는 `Schema validation → Policy validation → Review freshness → Domain ApproveAction guard`이며 하나라도 실패하면 Approval을 만들지 않는다.

정책은 두 층으로 구분한다.

- **Core Policy:** Connector와 무관한 승인·무결성·Write·Verification·UNKNOWN_RESULT·Prompt Injection 안전 규칙
- **Connector Policy:** Provider별 Resource·Scope·금지 Tool·중복/충돌·Verification 세부 규칙. P0에서는 Google Workspace의 Gmail·Tasks·Calendar 정책을 정의한다.

## 2. 정책 우선순위

정책 충돌 시 다음 순서를 적용한다.

1. 금지·보안 정책
2. 승인·무결성 정책
3. 데이터·개인정보 정책
4. 실행·검증 정책
5. 사용자 설정
6. Agent 추천

메일·Task·Event 본문에 포함된 지시는 이 정책보다 우선할 수 없다.

## 3. 위험 등급

| 등급 | 정의 | 처리 |
| --- | --- | --- |
| READ | 조회·검색·분석 | 사용자 요청 범위에서 자동 실행 가능 |
| WRITE_LOW | Draft·Task·Event 생성 또는 허용 필드 수정 | 사용자 승인 필수 |
| WRITE_HIGH | 메일 전송·Event 삭제·외부 참석자 변경처럼 외부 영향이 큰 작업 | 정확한 대상·인자를 고정하고 사용자 승인 후 실행. 승인 이후 인자 변경·UNKNOWN_RESULT 자동 재실행 금지 |
| SYSTEM | Credential·환경·DB 변경 | 명시적 설정 화면에서만 수행 |

## 4. Tool 허용 정책

### 4.1 허용되는 읽기 Tool

- Gmail Thread·Message 검색과 조회
- Google Tasks List·Task 조회
- Google Calendar List·Event 조회
- Calendar FreeBusy 조회
- 생성 결과 재조회

### 4.2 승인 후 허용되는 쓰기 Tool

- Gmail Draft 생성·수정
- Gmail 실제 전송 (`gmail_send`, `SEND`)
- Google Task 생성·허용 필드 수정·완료 상태 변경·삭제
- Calendar Event 생성·허용 필드 수정·삭제 (`calendar_delete_event`, `DELETE`)
- Calendar 참석자 추가·수정

### 4.3 금지 Tool

- Gmail Message·Thread 원문 삭제
- Gmail Label·설정 변경
- 반복 Event 전체 일괄 수정
- 승인·Policy·Verification을 우회하는 System/DB 직접 변경
- Connector MCP 경계 밖에서 외부 Provider API/SDK를 직접 호출하는 경로. 외부 Connector I/O의 직접 제품 caller는 Application의 결정적 use-case/Application operation이며, Application은 내부 structural `SignedToolRegistry`로 `ValidatedConnectorToolBindingV1`을 만든 뒤 **외부 I/O에는 `ConnectorReadPort | ConnectorWritePort | OAuthCredentialPort` 같은 abstract Connector Application Port에만 의존한다.** Core-side Connector Adapter는 그 binding과 `ConnectorRuntimeRegistry + MCPClientPort`를 사용해 정확한 Connector MCP Server로 dispatch한다. React·FastAPI Route·LangGraph adapter/Agent·Domain은 concrete Connector/MCP path나 `ConnectorRuntimeRegistry`를 직접 호출하지 않는다. Provider Credential/API Adapter는 해당 Connector MCP Server 내부에서만 소유하며 P0 Google Workspace도 동일하다.

금지 Tool은 UI에서 숨기는 것만으로 끝내지 않고 MCP Server에 등록하지 않는다.

## 5. 승인 정책

### POL-APP-001 쓰기 승인

모든 WRITE_LOW·WRITE_HIGH Action은 실행 전에 사용자의 명시적 승인을 받아야 한다.

### POL-APP-002 승인 단위

- Action별 승인 기본
- 전체 승인과 시스템별 일괄 승인 허용
- 일부 승인 허용
- 거절 Action과 종속 Action은 실행하지 않음

### POL-APP-003 승인 내용

승인 화면은 다음을 표시해야 한다.

- Tool과 Action 유형
- 변경 전·후 값
- 대상 Connector Resource
- 근거 Evidence
- 중복·충돌·Evidence 기반 업무 마감 위험
- 예상 실행 결과

### POL-APP-004 승인 무결성

- Arguments를 Canonical JSON으로 변환한다.
- SHA-256 Hash를 생성하고 Approval Snapshot에 Action Version·Tool·Arguments·Source Snapshot·Policy/Tool Schema Version과 함께 고정한다.
- 실행 전 Preflight/Claim에서 현재 Action과 Approval Snapshot의 Hash·Version·정책·Source 조건을 재검증한다.
- Domain Claim Commit 이후 서버가 발급한 1회용 `claim_token`은 Action·Approval·Attempt·Tool·실제 Execution Arguments Hash·Service Instance를 바인딩하며 MCP가 실제 수신 인자와 함께 재검증한다. **Claim Commit과 Token 발급은 필요조건일 뿐 외부 Write 권한이 아니다.**
- Application은 current ClaimContext binding과 `cancel_intent_active=false`를 검증해 `BeginExecutionAttempt`를 적용하고, 해당 Command/Receipt/Audit가 `applied=true`로 Commit되어 current Attempt가 `EXECUTING`인 경우에만 MCP Write를 호출한다. 불일치·conflict·cancel intent이면 외부 Write는 0이고 필요한 경우 Action 수정·새 Approval 또는 cancel resolution으로 돌아간다.

### POL-APP-005 승인 만료

다음 중 하나면 승인을 만료한다.

- 정책에서 정한 승인 유효 시간이 지남
- 원본 Resource가 변경됨
- 사용자가 Arguments를 수정함
- Tool Schema 또는 Policy Version이 변경됨

구체적 유효 시간은 policy invariant가 아니라 `10 Infrastructure`의 운영 설정으로 관리한다.

## 6. Evidence 정책

### POL-EVD-001 최소 Evidence

모든 Action은 최소 1개 Evidence가 필요하다.

### POL-EVD-002 기존 Resource 수정

기존 Draft·Task·Event 수정은 다음 중 하나가 필요하다.

- 사용자가 Resource를 직접 지정함
- 서로 독립적인 Evidence 2개 이상
- 하나의 명확한 Gmail Thread 또는 Resource 관계

### POL-EVD-003 낮은 신뢰도

근거가 부족하거나 후보가 복수이면 실행 가능한 Action으로 만들지 않고 제안 또는 확인 질문으로 전환한다.

## 6-A. Run Context 격리 정책

### POL-CTX-001 새 Run의 Context 권위

- 새 Run의 Context 권위는 현재 `RunInputV1`과 그 Run에서 새로 확정된 Typed Artifact다.
- 같은 Conversation의 이전 Run Message·RequestIntent·Tool Route·Retrieval/Evidence·Work Analysis·Plan/Review·Confirmation Receipt·Checkpoint를 현재 Run의 근거·의도·승인·정책 확인으로 자동 재사용하지 않는다.
- 사용자가 이전 화면에서 Resource를 다시 명시적으로 선택해 새 Run에 첨부한 경우에는 그 **Resource reference**만 현재 Run의 Entry Context가 된다. 이전 Run의 Evidence 판정이나 Approval은 함께 승계되지 않으며 필요하면 현재 Run에서 다시 조회·검증한다.
- 이전 Run의 Approval, Claim, Confirmation Receipt는 새 Run의 Write 권한 또는 Scope 확장 근거가 될 수 없다.
- 같은 Run의 Confirmation/재인증/Recovery resume는 새 Run Context 승계가 아니라 동일 Run의 안전 checkpoint 연속성으로 취급한다.
- 현재 요청이 이전 Run 없이는 해석되지 않는 모호한 표현이고 이번 Run에 명시적 Resource가 없으면, 과거 Conversation 내용을 암묵적으로 추론 근거로 사용하지 않고 확인 질문으로 전환한다.

## 7. Gmail 정책

### POL-GML-001 읽기 범위

- 사용자 요청과 관련된 Thread·Message만 조회한다.
- 기간·사람·제목·Resource ID를 우선 사용한다.
- 필요 이상으로 전체 메일함을 조회하지 않는다.

### POL-GML-002 Draft 생성

- Draft는 전송하지 않는다.
- 기존 Thread 회신이면 Thread 연결을 유지한다.
- 수신자·CC·제목·본문을 승인 화면에 표시한다.

### POL-GML-003 외부 주소

외부 도메인 수신자는 다음 경우에만 Draft에 포함할 수 있다.

- 사용자가 직접 지정함
- 기존 Thread 참여자임

그 외에는 확인 질문을 한다.

### POL-GML-004 원문 저장

Gmail 전체 원문은 SQLite에 장기 저장하지 않는다. 사용자가 메일을 열거나 선택하거나 Agent가 후보를 확정했을 때 필요한 Thread·Message 상세만 현재 Run 메모리에서 사용한다. 실제 판단과 승인에 사용된 최소 Evidence excerpt와 생성 Draft만 Run 보존 기간 동안 저장할 수 있다.

## 8. Tasks 정책

### POL-TSK-001 생성 전 중복 검사

Task 생성 전에 기존 미완료 Task를 검사한다.

### POL-TSK-002 중복 처리

- 명확한 중복: 기존 Resource를 보여주고 기본적으로 새 생성을 중단
- 사용자가 중복임을 인지하고 동일 Resource 추가 생성을 명시적으로 요구: 재확인·승인 후 허용
- 유사 후보: 경고 후 사용자 확인
- 관련 없음: 생성 허용

구체적 유사도 임계값은 bounded configuration이며 채택 근거와 calibrated value는 `13 Evaluation`이 관리한다. 이 문서는 threshold 수치 자체를 policy invariant로 소유하지 않는다.

### POL-TSK-003 허용 필드

- 제목
- 메모
- 예정일
- 대상 Task List

Task 완료 상태 변경과 Task 삭제는 정확한 Task 대상과 사용자 승인 후 허용한다. Task 삭제는 `DELETE` Effect로 처리하고 실행 후 대상 부재를 재조회해 검증한다.

### POL-TSK-004 날짜·상태 의미와 금지

- Google Task `due`는 제품 내부 `scheduled_date`에만 대응하는 예정일이다. 이를 실제 업무 `business_deadline`으로 표현·판단·검증하지 않는다.
- Gmail·사용자 요청·Evidence에서 확인한 `business_deadline`을 `scheduled_date` 또는 Google `due`로 자동 변환하지 않는다. Task 생성에서 의미 보존이 필요하면 승인된 notes와 Evidence·Approval Summary를 사용한다.
- API에 없는 deadline 또는 작업 시간을 추정해 Task Write Argument에 만들지 않는다. 정확한 시간 예약은 승인형 Calendar Event 대안을 사용자에게 제시할 수 있으나 자동 생성하지 않는다.
- Provider raw status는 UI에 직접 노출하지 않는다. 예정일 경과는 실제 완료 상태를 변경하지 않으며, Task 완료는 정확한 대상·사용자 승인형 `UPDATE`만 허용한다.

## 9. Calendar 정책

### POL-CAL-001 Event 생성 조건

작업 Event 생성에는 다음이 필요하다.

- 예상 소요시간
- 업무 마감 또는 배치 기준
- 대상 Calendar
- 충돌 검사 결과

예상 소요시간이 없으면 사용자에게 질문한다.

### POL-CAL-002 Busy 판정

다음은 Busy로 취급한다.

- Opaque Event
- Out of Office
- Focus Time
- 선택 Calendar의 Busy Interval

Tentative는 경고로 처리하고, Declined 또는 Free Event는 Busy에서 제외한다.

### POL-CAL-003 참석자 변경

내부·외부 참석자 추가·수정을 승인형 Write로 지원한다. 참석자 이메일과 대상 Event를 승인 화면에 명시하며 대상이나 이메일이 모호하면 실행 전에 확인한다.

### POL-CAL-004 작업 시간

초기 기본값은 평일 09:00~18:00이며 사용자가 Settings의 `working_day_start_local`, `working_day_end_local`, `include_weekends`로 변경할 수 있다. 주말은 기본 제외한다. 일정 앞뒤 Buffer는 `calendar_buffer_minutes`, timezone 해석은 persisted `timezone`을 사용하며 exact Settings meaning은 10, wire는 07이 소유한다.

## 10. 중복·충돌 정책

### POL-DUP-001 결정 방식

중복과 충돌은 LLM 단독 판단으로 확정하지 않는다. 일반 코드 Validator와 Source 데이터로 판단한다.

### POL-DUP-002 Override

- 중복·충돌 경고는 사용자 2차 확인으로 Override 가능
- 명확한 중복도 사용자가 중복 사실을 인지하고 동일 Resource 추가 생성을 명시적으로 요구한 경우 재확인·승인 후 허용 가능
- 금지 작업과 승인 무결성 위반은 Override 불가

## 11. Google Workspace Connector OAuth 정책

### POL-OAUTH-001 사용자 로그인 방식

사용자는 자신의 Google Cloud 프로젝트나 OAuth Client JSON을 준비하지 않는다. 앱은 개발팀이 소유한 Desktop OAuth Client를 사용하고 UI에는 `Google로 로그인` 버튼만 제공한다. 다만 계정 인증만으로는 충분하지 않으며 Gmail·Tasks·Calendar Scope 동의가 함께 완료되어야 한다.

### POL-OAUTH-002 OAuth 프로젝트 분리

개발, 스테이징, 운영은 서로 다른 Google Cloud 프로젝트와 OAuth Client를 사용한다. 테스트 Scope나 Redirect 설정을 운영 프로젝트에 직접 추가하지 않는다.

### POL-OAUTH-003 Desktop OAuth 흐름

- OAuth Client 유형: Desktop App
- Redirect: `http://127.0.0.1:<ephemeral-port>` loopback
- PKCE 필수
- `state` 검증 필수
- OOB 수동 코드 복사 방식 금지
- Refresh Token은 OS Keyring 저장
- P0 Installed/Desktop OAuth는 non-secret `oauth_client_id`와 PKCE·`state`·ephemeral loopback만 사용하며 `client_secret`을 요구하지 않는다.
- Provider/downloaded client configuration에 `client_secret` field가 있어도 current P0 loader는 무시하고 Token request, MCP child environment, React/Vite, FastAPI wire, SQLite, Log, Trace, Diagnostic, OS Keyring으로 전달·저장하지 않는다.

### POL-OAUTH-004 팀 테스트

- 개발·스테이징 OAuth 앱은 팀 Google 계정을 Test User로 등록한다.
- External + Testing 상태의 Refresh Token 7일 만료를 정상 오류로 처리하고 재로그인을 제공한다.
- Test User가 아닌 계정은 P0 테스트 배포에서 연결하지 않는다.

### POL-OAUTH-005 운영 배포 Gate

공개 운영 배포는 OAuth 브랜드와 데이터 액세스 검증이 완료된 Client만 사용한다. Gmail 본문 읽기와 Draft 관리 Scope는 제한 Scope로 관리하며 검증되지 않은 Client를 일반 사용자 배포에 포함하지 않는다.

### POL-OAUTH-006 최소 Scope

P0 OAuth permission은 **구현된 기능에 필요한 최소 집합만 요청**하고, required permission 일부가 거절되면 연결을 완료 처리하지 않는다.

Exact provider Scope 문자열과 Credential/Auth realization은 `09 Security §P0 Scope`가 소유하고, Tool별 required Scope mapping은 `07 Interface`가 소비한다. Policy 문서에서 같은 Scope 목록을 별도 유지하지 않는다. Gmail Send를 포함한 모든 Write는 Scope 보유 여부와 무관하게 본 문서의 승인·Tool Allowlist·실행 무결성 정책을 그대로 통과해야 한다.

### POL-OAUTH-007 Gmail 데이터 외부 처리

API LLM 모드에서 Gmail Context를 외부 Provider로 전송하는 것은 사용자 기능 제공에 필요한 범위와 사용자 동의 안에서만 허용한다. Provider가 해당 데이터를 광고, 범용 모델 학습, 재판매에 사용하도록 허용하지 않는다. 공개 운영 배포 전 제한 Scope 보안 평가와 Google Limited Use 준수 여부를 확인한다.

## 12. LLM Runtime 정책

### POL-LLM-001 CPU-only

CPU-only 또는 GPU 기준 미달 PC는 API_LLM으로 고정한다. CPU Local LLM은 지원하지 않는다.

### POL-LLM-002 P0 GPU 사용 가능 환경

P0에서 검증된 GPU 환경은 AUTO, LOCAL_GPU, API_LLM을 모두 제공한다. Local 모드는 후속 기능이 아니라 P0 제품 기능이다.

### POL-LLM-003 AUTO fallback

AUTO는 다음 기술 오류에서 API로 최대 1회 fallback할 수 있다.

- Local Runtime 연결 실패
- 모델 없음 또는 로드 실패
- GPU OOM
- Timeout
- 반복된 Structured Output 실패

단순한 답변 품질 불만이나 낮은 자신감만으로 자동 fallback하지 않는다.

### POL-LLM-004 명시 모드

사용자가 LOCAL_GPU 또는 API_LLM을 명시 선택하면 동의 없이 다른 모드로 전환하지 않는다.

### POL-LLM-005 Ollama 고정

제품의 Local LLM Runtime은 Ollama로 고정한다. Release Config에 포함되지 않은 Runtime은 제품 Runtime/UI authority가 아니며 제품 UI에 노출하지 않는다.

### POL-LLM-006 모델 선택

제품 기본 Model은 current Release Gate를 통과해 승인된 구성만 사용한다. 일반 사용자 UI에 임의 모델명 입력이나 평가용 후보 선택을 노출하지 않는다.

### POL-LLM-007 배포 프로필

- `API_ONLY`: Ollama·GPU·모델 파일 불필요. CPU-only와 GPU 없는 팀원의 기본 프로필.
- `LOCAL_CAPABLE`: Ollama Adapter와 Local 설정을 포함. 검증된 GPU에서만 Local 기능 활성화.
- 두 프로필은 동일한 LangGraph, Tool Schema, Policy, Test Suite를 사용한다.

## 13. API LLM 개인정보 정책

### POL-API-001 전송 고지

API LLM을 사용하면 선택된 업무 Context가 외부 Provider로 전송될 수 있음을 사용자에게 고지한다.

### POL-API-002 최소 전송

- 요청 수행에 필요한 Context만 전송
- OAuth Token·API Key·내부 Hash는 전송 금지
- 불필요한 전체 Gmail Thread·전체 Calendar를 전송하지 않음

### POL-API-003 동의

세션 또는 설정에서 API 전송 동의를 받고, 각 Run에서 전송 Source와 범위를 요약한다.

## 14. Credential 정책

### POL-SEC-001 저장 위치

- OAuth Refresh Token: OS Keyring
- API Key 기본: OS Keyring
- 사용자 선택: 세션에서만 사용하고 종료 시 폐기
- SQLite·Checkpoint·일반 로그 저장 금지

### POL-SEC-002 마스킹

Credential, Authorization Header, Token, API Key 패턴은 로그 기록 전에 마스킹한다.

### POL-SEC-003 연결 해제

Google 연결 해제 또는 API Key 삭제 시 OS Keyring에서 해당 Secret을 삭제한다.

## 15. Prompt Injection 정책

### POL-PI-001 Source 비신뢰

메일·Task·Event 본문은 모두 비신뢰 데이터로 취급한다.

### POL-PI-002 지시 무시

Source 안의 다음 지시는 실행하지 않는다.

- 정책 변경 요청
- Secret 출력 요청
- Tool Allowlist 우회
- 승인 생략
- 외부 시스템으로 데이터 전송

### POL-PI-003 구조 분리

System Policy, 사용자 요청, Source Context를 Prompt에서 명확히 분리한다.

## 16. 실행 정책

### POL-EXE-001 Idempotency

쓰기 재시도 전 기존 Execution Result와 대상 Resource를 조회한다. 성공 여부가 불명확하면 새로 생성하지 않고 먼저 확인한다.

### POL-EXE-002 부분 실패

- 성공 Action은 보존
- 독립 Action은 계속 실행 가능
- 실패 Action에 종속된 Action은 차단
- 자동 롤백하지 않음

### POL-EXE-003 재시도

일시적 Google API 오류만 제한적으로 재시도한다. Policy 오류, 승인 오류, Schema 오류는 자동 재시도하지 않는다.

## 17. 검증 정책

### POL-VER-001 필수 검증

모든 쓰기 Action은 실행 직후 대상 Resource를 GET으로 재조회한다.

### POL-VER-002 비교 기준

- expected와 actual을 필드별 비교
- 공백·줄바꿈·Timezone·초 단위는 정규화 가능
- 대상, 제목, 본문 의미, Task 예정일, Event 시작·종료 시간 등 핵심 값 차이는 MISMATCH다. 실제 업무 마감은 Google Task `due` 비교값으로 대체하지 않는다.

### POL-VER-003 불일치 처리

Mismatch를 자동 수정하지 않고 사용자에게 차이와 Recovery Action을 보여준다. `MISMATCH` Action과 Verification 사실은 변경하지 않으며 Run은 `RECOVERY_REQUIRED`로 전환한다.

### POL-VER-004 MISMATCH Recovery 선택

P0에서 Verification `MISMATCH`를 해소하는 사용자 선택은 다음 두 가지로 제한한다.

- `ACCEPT_PARTIAL`: 현재 Google 실제 상태와 기존 `MISMATCH`를 보존하고 추가 Write 없이 종료한다. 미실행 Action은 취소 처리하며 Run은 `COMPLETED`, 결과 분류는 `PARTIAL`이다.
- `CREATE_CORRECTIVE_PLAN`: 실제 Google 상태를 최신 Source Snapshot으로 재조회하고 같은 Run에서 새 Plan Revision을 만든다. 기존 MISMATCH Action·Approval·Attempt·Verification을 재사용하지 않는다.

교정 Write는 반드시 새 Domain Validation → 새 Approval → 새 `ClaimExecution` → ClaimContext 구성 → `BeginExecutionAttempt(applied=true)` → external Write → 새 Verification 경계를 통과한다. 기존 MISMATCH Action을 `EXECUTING`으로 되돌리거나 자동 수정·자동 Rollback하지 않는다. 전체 Run 중단은 Recovery 선택이 아니라 별도 Cancel Command로 처리한다.

### POL-VER-005 Write 전달 확실성

Write 실패 분류는 Exception 이름이 아니라 외부 시스템 전달 가능성을 기준으로 한다.

- `NOT_SENT`: Google 변경이 발생하지 않았음을 확정할 수 있는 경우에만 `FAILED` 후보가 된다.
- `MAY_HAVE_BEEN_SENT`: 요청이 전달됐을 가능성이 있으면 `UNKNOWN_RESULT`로 처리한다.
- `SENT_RESPONSE_LOST`: 요청 전달 후 응답만 유실된 경우 `UNKNOWN_RESULT`로 처리한다.

Dispatch 이후 Timeout·5xx·Transport Disconnect를 Provider가 미전달로 보장하지 않는 한 `FAILED`로 단정하지 않는다.

## 18. 데이터 보존 정책

P0의 persisted `retention_days`는 **기본 30일, 허용 범위 1..30일**이다. 사용자는 30일보다 짧게만 줄일 수 있으며 31일 이상으로 늘리는 기능은 P1 이후 별도 정책 변경으로만 도입한다.

| 데이터 | P0 보존 의미 | `retention_days` 적용 | 사용자 삭제 |
| --- | --- | --- | --- |
| Conversation·Message | 기본 30일. 보존 cutoff가 지난 row는 아래 보호 조건이 없을 때 물리 삭제 | 예 | 예 |
| Terminal Run과 소유 child(Plan·Action·Approval·ExecutionAttempt·Verification·ResourceRef·Evidence·Trace) | Run `finished_at_ms` 기준 기본 30일 | 예 | Conversation 삭제 시 함께 정리 가능 |
| LangGraph Checkpoint | owning Run과 같은 보존 창. resume/recovery가 필요한 동안 선행 삭제 금지 | 예 — owning Run에 종속 | owning Run 삭제와 함께 |
| Command Receipt | 독립 숫자 보존기간 없음. owning Aggregate의 replay/recovery 가능 기간보다 먼저 삭제 금지 | 직접 적용하지 않음 | owning Aggregate purge UoW에서 순서 보장 |
| Audit Log | 90일 고정 | **아니오** | 제품 데이터 삭제 뒤에도 업무 원문 없이 최소 식별·상태만 유지 |
| Sidebar page/batch·opaque Local API continuation·Calendar Month cache | React Client Session Cache, 세션 종료 시 삭제 | 아니오 | 세션 폐기 |
| Agent 검색 중간 후보 | 현재 Run 메모리, Run 종료 시 삭제 | 아니오 | Run 종료 시 폐기 |
| Gmail 전체 원문 | 영구 저장하지 않음 | 아니오 | 해당 없음 |
| Task·Event 상세 원문 | 기본적으로 영구 저장하지 않음 | 아니오 | 해당 없음 |
| Google Refresh Token | OS Keyring | 아니오 | 연결 해제/Uninstall 정책 |
| Google Access Token | Connector MCP Credential Provider process memory만 | 아니오 | process/session 종료 시 폐기 |
| LLM API Key | `KEYRING` 또는 사용자가 선택한 `SESSION_ONLY` Local Agent process memory | 아니오 | credential delete/session 종료 |

**Purge 보호 규칙:** nonterminal Run, active Confirmation/Reauth/Recovery, replay에 필요한 Command Receipt, 아직 보존 대상인 child를 가진 parent는 retention cutoff가 지났다는 이유만으로 먼저 삭제하지 않는다. Conversation은 retained Message/Run이 모두 정리되고 open Run이 0일 때만 삭제한다. Audit 90일은 `retention_days`로 줄이거나 늘리지 않는다. 정확한 timestamp/cascade/UoW realization은 04가 이 Policy를 그대로 소비한다.

Sidebar page/batch·opaque Local API continuation·Calendar Month cache는 React Client Session Cache에, Agent 검색 중간 후보는 Python Run 메모리에만 유지한다. Google Workspace 목록 전체를 SQLite에 동기화하거나 상시 복제하지 않는다.

## 19. 로그·감사 정책

### 기록

- Run·`langgraph_thread_id`·Action ID
- Node·Tool 이름
- Sanitized Arguments Metadata
- 승인·수정·거절
- 실행·검증 상태
- Provider·모델·fallback
- Latency·Token·오류 코드

### 기록 금지

- 전체 API Key
- OAuth Token
- Authorization Header
- 불필요한 전체 Gmail 원문
- OS·GPU 고유 식별자

## 21. Policy 결과 유형

| 결과 | 의미 |
| --- | --- |
| ALLOW | 자동 읽기 또는 승인된 쓰기 실행 가능 |
| REQUIRE_APPROVAL | 사용자 승인 필요 |
| REQUIRE_CONFIRMATION | 모호성·경고에 대한 사용자 확인 필요 |
| BLOCK | 정책상 실행 금지 |
| EXPIRED | 승인 또는 Credential 상태 만료 |
| MISMATCH | 실행 결과가 승인 내용과 다름 |

## 22. Google Source 조회·메모리 캐시 정책

### POL-SRC-001 호출 위치

Google Workspace API는 사용자 PC의 로컬 MCP Server가 사용자 OAuth Credential로 호출한다. React Frontend는 Google Credential과 Google API를 직접 다루지 않으며 별도의 원격 동기화 서버나 Google 데이터 저장 서버를 두지 않는다.

### POL-SRC-002 요청 진입 방식

- `AGENT_SEARCH`: 사용자의 Query, 날짜·기간, 사람·이메일, Keyword 또는 복합 요구사항을 구조화해 Source-native 검색을 수행한다.
- `RESOURCE_SELECTED`: 사용자가 사이드바에서 선택한 하나 이상의 Resource를 초기 Context로 사용한다.
- 두 방식은 Context 구성 이후 동일한 분석·계획·승인·실행·검증 정책을 적용한다.

### POL-SRC-003 사이드바 목록

Sidebar의 표시 순서·기본 범위·Month View·페이지 presentation은 `01-A Functional`과 `02 UI·UX`, wire/continuation semantics는 `07 Interface`가 소유한다. Policy는 사용자가 허용한 Source·기간·계정 범위를 벗어난 조회를 금지하고, Browser가 Provider raw continuation을 생성·해석·수정하지 못하게 한다.

### POL-SRC-004 페이지 메모리 캐시

- 이미 materialize한 Gmail·Tasks page/batch와 opaque Local API continuation, Calendar Month cache만 React Client Session Cache에서 재사용한다.
- Cache identity/invalidation은 02/07의 current contract를 따르며 Provider raw continuation은 Connector/MCP Adapter 내부에 남는다.
- UI 세션 종료, 계정·container·scope·검색·filter·sort 변경 또는 수동 새로고침 시 관련 Cache를 폐기한다.
- Sidebar Cache는 승인·중복·충돌·검증의 기준점이 아니며 SQLite에 영구 저장하지 않는다.

### POL-SRC-005 직접 선택

- authenticated `selection_handle`에서 resolve된 current Resource identity는 다시 검색해 추측하지 않고 canonical Connector detail Read로 최신 상세를 조회한다.
- 하나 또는 여러 Resource를 선택할 수 있다.
- 추가 Source 검색은 사용자의 요청을 수행하는 데 필요한 경우에만 허용한다.
- 선택한 Resource의 사람·날짜·제목을 사용자에게 다시 입력하도록 요구하지 않는다.

### POL-SRC-006 Agent 검색

- Agent는 요청 조건으로 Google Source-native 목록 검색을 먼저 수행한다.
- 후보 전체의 상세를 조회하지 않고 Metadata와 일반 코드로 후보를 축소한다.
- 필요한 후보만 상세 조회하고 필요한 Context만 LLM에 전달한다.
- Context가 부족한 경우에만 최대 2회 재검색한다.

### POL-SRC-007 영구 저장 범위

SQLite에는 실제 Run에서 사용된 Resource ID, Source, 원본 링크, 최소 Metadata, Evidence excerpt만 저장할 수 있다. 사용되지 않은 목록 페이지, 검색 중간 후보, Gmail 전체 원문, Task·Event 상세 원문은 영구 저장하지 않는다.

### POL-SRC-008 최신성 기준

- 사이드바 Cache는 탐색과 즉시 표시를 위한 임시 데이터다.
- 선택형 요청 시작 시 선택 Resource의 상세를 다시 조회한다.
- 쓰기 계획 확정 전, 승인 후 실행 직전, 실행 직후에는 관련 Resource를 Google API로 재조회한다.
- 승인·충돌·중복·검증 판단에서 Cache보다 최신 Google API 응답을 우선한다.

### POL-SRC-009 수동 새로고침

사용자가 Source의 새로고침을 실행하면 해당 Source의 materialized Cache와 opaque Local API continuation generation을 폐기하고 current initial scope를 최신 데이터로 다시 조회한다.

## 23. Secure & Resilient 시스템 정책

### 23.1 입력·출력·오류 정책

#### POL-INP-001 중앙 입력 검증

사용자 입력, Connector 응답, LLM Structured Output, Resource ID, opaque Local API continuation, 날짜·시간, 이메일 주소는 해당 typed boundary에서 타입·길이·개수·허용값을 검증한다. Provider raw continuation은 Connector/MCP Adapter 경계에서만 검증한다. UI·Agent·MCP가 서로 다른 검증 규칙을 임의로 가지지 않는다.

#### POL-INP-002 허용 목록 우선

Tool Name, Source, 상태, AI 모드, URL Scheme, 수정 가능 필드는 Allowlist로 검증한다. 검증되지 않은 값은 추정하거나 보정해 실행하지 않고 차단 또는 사용자 확인으로 전환한다.

#### POL-INP-003 안전한 렌더링

Google·사용자·LLM에서 받은 문자열을 React에서 Raw HTML로 실행하지 않는다. Markdown과 Link는 안전한 Renderer를 통과하며 `javascript:`, `data:` 등 실행 가능한 Scheme은 차단한다. OAuth Loopback을 제외한 링크는 기본적으로 `https`만 허용한다.

#### POL-ERR-001 오류 정보 분리

사용자 화면에는 원인, 현재 상태, 데이터 변경 여부, 다음 행동만 표시한다. Stack Trace, SQL, 로컬 파일 경로, Authorization Header, Token, Keyring Entry 이름은 진단 로그에도 Sanitized 형태로만 기록한다.

### 23.2 로컬 실행 경계 정책

#### POL-LOCAL-001 `Localhost` 바인딩

FastAPI Local Agent Service는 `127.0.0.1`의 동적 포트에만 바인딩한다. P0에서 Public IP, LAN 전체 Interface, 원격 Reverse Proxy에 직접 노출하지 않는다.

#### POL-LOCAL-002 요청 위조 보호

운영 빌드는 React UI와 Local API를 같은 Origin에서 제공한다. State-changing API는 JSON Content-Type, Host·Origin, Local Session, Command ID 검증을 요구한다. 임의 Origin Allowlist, Wildcard CORS, 브라우저 Form POST 기반 Command를 허용하지 않는다.

#### POL-LOCAL-003 외부 Endpoint 제한

외부 통신 목적지는 검증된 Google Workspace API, 승인된 API LLM Provider, OAuth Endpoint로 제한한다. React Browser Runtime은 제품 외부 API를 직접 호출하지 않고 Local Agent Service를 통한다. 사용자 입력 URL을 서버가 임의 Fetch하는 범용 기능은 제공하지 않는다.

#### POL-LOCAL-004 Local Session 수립

- Launcher는 앱 시작마다 고엔트로피 일회성 Bootstrap Secret을 생성한다.
- Bootstrap Secret은 URL Query, SQLite, 일반 로그에 기록하지 않는다.
- React Frontend는 Bootstrap을 한 번 교환해 Local Session을 수립하고 즉시 폐기한다.
- Session은 앱 Process 수명과 연결되며 재사용·외부 복사를 허용하지 않는다.

#### POL-LOCAL-005 Local API Command 경계

- FastAPI Route는 UI Adapter이며 Policy와 Domain Transition을 직접 구현하지 않는다.
- 모든 변경 Command는 Command ID, Aggregate ID, expected version을 포함한다.
- 승인·수정·거절·취소·실행 시작은 Application Command를 통해서만 수행한다.
- Endpoint 재호출은 기존 Command Result를 반환하거나 Version Conflict로 종료하며 상태를 중복 적용하지 않는다.

#### POL-LOCAL-006 Event Stream

- Run 진행 전달은 SSE를 기본으로 한다.
- Event는 Run·Action ID, Event Type, 상태, 사용자 표시 Payload와 Cursor를 포함할 수 있다.
- OAuth Token, API Key, Authorization Header, 불필요한 Gmail 원문을 포함하지 않는다.
- SSE 연결 단절은 Run 실패로 간주하지 않으며 Snapshot 재조회 또는 Cursor 재구독으로 복구한다.

#### POL-LOCAL-007 Production same-origin

운영 배포에서 FastAPI가 React 정적 산출물과 `/api/v1`을 같은 Origin으로 제공한다. Vite 개발 서버는 개발 환경에서만 사용하며 Local API Proxy와 제한된 개발 Origin 설정을 적용한다.

### 23.2-A Frontend · API 계약 정책

#### POL-APIX-001 Versioned Contract

REST Request·Response·Error와 SSE Event는 `/api/v1`과 Versioned Pydantic Schema로 관리한다. Frontend Type은 동일 Contract에서 생성하거나 CI에서 호환성을 검증한다.

#### POL-APIX-002 오류 정규화

Local API 오류는 `error_code`, `user_message`, `retryable`, `current_state`, `request_id`를 포함하는 공통 형식으로 반환한다. Stack Trace·SQL·파일 경로·Secret은 Frontend에 반환하지 않는다.

#### POL-APIX-003 명령과 조회 분리

조회 Endpoint는 Domain 사실을 변경하지 않는다. 상태 변경 Endpoint는 명시적 Command 이름과 대상 Version을 사용하며 GET 요청으로 변경을 수행하지 않는다.

#### POL-APIX-004 Frontend 비신뢰

React Client State, Browser Storage, URL Parameter와 SSE Payload는 Domain 사실의 기준점이 아니다. 승인·실행·검증 여부는 Local Agent Service가 Domain Store에서 다시 확인한다.

#### POL-APIX-005 상태 변경 권위 Metadata

브라우저는 사용자 의도와 낙관적 동시성에 필요한 `command_id`, 대상 ID, `expected_version`, 허용된 사용자 입력만 전달한다. `request_hash`, `approval_id`, Write `idempotency_key`, `source_snapshot`, 승인 주체, `canonical_arguments_hash`, `claim_token`은 Application·Domain이 현재 상태에서 생성·검증하며 Browser 입력을 실행 권위로 신뢰하지 않는다. `request_hash`는 Endpoint별 Versioned Request Schema를 Canonical JSON으로 정규화한 뒤 서버에서 계산한다.

### 23.3 SQLite 동시성·트랜잭션 정책

#### POL-DB-001 Write Coordination

모든 Domain Write는 Repository와 명시적 transaction boundary를 거친다. React Event Handler, FastAPI Route, LangGraph Node, Audit Writer가 각각 독립적으로 SQL을 실행하지 않는다.

#### POL-DB-002 짧은 Transaction

DB Transaction 안에서 Google API, LLM, MCP 호출을 기다리지 않는다. `ClaimExecution` Commit, ClaimContext 구성, `BeginExecutionAttempt` Commit, 외부 호출, 결과 저장, GET 검증, 최종 상태 저장을 각각 명시된 경계로 분리한다. 외부 Write는 `BeginExecutionAttempt` Transaction이 종료되고 `applied=true`인 뒤에만 수행한다.

#### POL-DB-003 실행권 Claim

Action 실행 전 `ClaimExecution` 조건부 상태 전이로 실행권을 **예약**한다. `APPROVED` 상태와 Version이 일치하는 Row 하나만 Action `EXECUTING` + Attempt `CLAIMED`로 전환할 수 있으며 영향 Row가 1개가 아니면 진행하지 않는다. 이 Commit은 외부 dispatch authority가 아니며, 별도 `BeginExecutionAttempt`가 Attempt `CLAIMED → EXECUTING`으로 `applied=true` Commit되어야 한다.

#### POL-DB-004 DB Constraint 우선

다음 무결성은 애플리케이션 코드와 함께 DB Constraint로 강제한다.

- Foreign Key
- Idempotency Key UNIQUE
- Action별 Attempt Number UNIQUE
- 필수 식별자 NOT NULL
- 허용 상태 CHECK 또는 Repository 상태 전이 검증
- 동일 Run·Source·Resource 중복 참조 제한

#### POL-DB-005 SQLite Connection

모든 Connection은 Foreign Key 검사를 활성화한다. `busy_timeout`, WAL 사용 여부, `synchronous` 수준, Retry 횟수는 `04. 도메인·데이터베이스 설계서`의 고정 Config를 사용하며 각 Repository가 임의 변경하지 않는다.

#### POL-DB-006 Busy 처리

`SQLITE_BUSY`는 짧은 대기 후 제한적으로 재시도할 수 있다. 무제한 Retry, Busy Loop, Transaction 전체 재실행은 금지한다. 반복 실패 시 현재 Run을 안전하게 중단하고 사용자에게 DB 잠김 상태를 표시한다.

#### POL-DB-007 외부 시스템과 ACID 가정 금지

SQLite와 외부 Connector Provider API를 하나의 Transaction으로 취급하지 않는다. Connector Write는 Action Saga와 상태 전이로 관리하고 성공한 외부 Resource를 DB 실패 때문에 자동 Rollback하지 않는다.

#### POL-DB-008 정규화와 Snapshot

관계·상태·검색 대상 필드는 정규화된 Table로 관리한다. Action Arguments, 승인 당시 값, expected·actual 결과, Provider Metadata처럼 구조가 변하거나 불변 이력이 필요한 값은 Version이 포함된 JSON Snapshot으로 저장할 수 있다.

### 23.4 조회·Pagination 정책

#### POL-QRY-001 N+1 방지

Repository는 View와 Use Case에 필요한 Aggregate를 Batch Query 또는 Join으로 조회한다. Action·Evidence·Execution을 Row별 반복 조회하는 구조를 기본 구현으로 사용하지 않는다.

#### POL-QRY-002 로컬 Cursor Pagination

Conversation, Message, Run, Audit처럼 증가하는 목록은 안정된 정렬값과 고유 ID를 결합한 Cursor를 사용한다. 작은 고정 목록에만 OFFSET을 허용한다.

#### POL-QRY-003 Google Pagination 분리

Browser는 opaque Local API continuation만 보존·재전송한다. Provider raw continuation은 Connector/MCP Adapter 내부 구현 세부사항이며 SQLite local keyset cursor와 혼용하지 않는다.

#### POL-QRY-004 Index 근거

Index는 실제 `WHERE`, `JOIN`, `ORDER BY` Query와 Query Plan을 근거로 추가한다. 추적 편의를 이유로 사용되지 않는 Column과 Index를 미리 대량 생성하지 않는다.

### 23.5 Migration·Backup·복구 정책

#### POL-MIG-001 Schema Version

모든 Migration은 순서가 있는 Version과 적용 결과를 기록한다. 실행 중인 애플리케이션 Schema보다 DB Version이 새롭거나 호환되지 않으면 Write를 차단한다.

#### POL-MIG-002 Migration 전 Backup

파괴적 또는 데이터 변환 Migration 전에는 SQLite Backup API 등 일관된 방식으로 Backup을 생성한다. 실행 중인 DB 파일을 단순 복사하는 방식을 기본 Backup으로 사용하지 않는다.

#### POL-MIG-003 무결성 검사

앱 시작과 Migration 후 빠른 DB 무결성 검사와 Foreign Key 검사를 수행한다. 실패 시 Connector Write와 Domain Write를 차단하고 진단·복구 기능만 허용한다.

#### POL-MIG-004 Restore

Restore는 사용자의 명시적 선택으로 수행한다. 현재 손상 DB를 별도 보존한 뒤 Backup을 복원하고 Schema Version·무결성·Foreign Key 검사를 다시 통과해야 정상 모드로 전환한다.

#### POL-MIG-005 물리 삭제

Conversation·Message와 terminal Run 소유 데이터는 §18의 P0 retention matrix와 사용자 삭제 요청에 따라 실제 삭제한다. `retention_days`는 §18에 명시된 대상에만 적용하고 Audit의 고정 90일·Secret lifecycle·session cache에는 적용하지 않는다. 모든 Table에 일괄 Soft Delete를 적용하지 않으며 Audit에는 업무 원문 없이 필요한 최소 식별·상태 정보만 남긴다.

### 23.6 외부 장애·호출 제한 정책

#### POL-RES-001 Run Budget

각 Run은 Google 목록 페이지 수, 상세 조회 수, LLM 호출 수, 재검색, Retry, Context 크기, 최대 실행 시간의 Config 상한을 가진다. 상한이 없으면 무제한 탐색을 허용하지 않는다.

#### POL-RES-002 Retry 제한

일시 오류만 제한적으로 재시도한다. Schema, Policy, 승인, 인증 거절, 잘못된 Arguments는 자동 재시도하지 않는다. 재시도는 동일 Idempotency 문맥을 유지한다.

#### POL-RES-003 Circuit 상태

Google API, API LLM, Ollama, MCP가 연속 실패하면 Component별 Circuit을 일시적으로 열어 새 호출을 중단한다. Circuit 상태와 재시도 가능 시각을 사용자 진단 화면에 표시한다.

#### POL-RES-004 Degraded Mode

읽기 Source 일부가 실패해도 남은 Source만으로 의미 있는 결과가 가능하면 부분 결과를 제공한다. DB 무결성 실패, 승인 무결성 실패, 사용 가능한 LLM 없음은 Degraded Mode로 우회하지 않고 실행을 차단한다.

### 23.7 공급망·Release 정책

#### POL-SUP-001 Dependency 고정

제품 배포는 Lockfile과 고정 Version을 기준으로 재현 가능해야 한다. 지원 종료 Runtime이나 검증되지 않은 Dependency 자동 업그레이드를 운영 Release에 직접 반영하지 않는다.

#### POL-SUP-002 자동 검사

CI에서 Dependency 취약점, Secret, 금지 파일, License와 테스트 실패를 검사한다. Critical 취약점 또는 Secret 탐지 상태에서는 Release Artifact를 생성하지 않는다.

#### POL-SUP-003 Artifact 무결성

Installer·ZIP·실행 Artifact의 SHA-256을 생성하고 Release Metadata에 기록한다. 배포되는 Test·Production Artifact는 Code Signing·Timestamp·SHA-256 Manifest를 Release Gate로 강제한다.

#### POL-SUP-004 Ollama·모델 고정

LOCAL_CAPABLE Release는 검증된 Ollama Version, Model ID, Model Hash와 Runtime Config를 고정한다. 사용자 환경에서 임의 모델을 제품 기본 모델로 자동 승격하지 않는다.

#### POL-SUP-005 적용 제외

원격 SaaS가 아닌 P0에는 WAF, VPC, Redis 분산 Lock, Kubernetes, ALB, DDoS 완화, 자체 JWT·비밀번호 정책을 적용하지 않는다. 제품 형태가 원격 서비스로 변경되면 별도 Threat Model과 정책을 작성한다.

## 24. Multi-Agent 정책

- Supervisor와 전문 Agent는 제안·분석·검토만 수행하며 정책 허용 여부를 최종 확정하지 않는다.
- 요청 이해 Agent는 Google Tool을 호출하지 않는다.
- Retrieval의 LLM semantic operation은 조회 전략 후보만 제안하고, 같은 Retrieval owner의 결정적 Application operation이 Query·MCP 인자를 검증·실행한다.
- Retrieval LLM Node와 Agent Subgraph는 MCP·Provider API를 직접 호출하지 않는다. 외부 Read는 결정적 Application operation이 `ConnectorReadPort`를 통해 수행한다.
- 업무 분석 Agent의 중복·충돌·위험 판단은 후보이며 `work_analysis.validate_relations`/`validate_work_analysis`가 Evidence·semantic consistency를 결정적으로 검증한다. 이후 `action.evaluate_action_policy`가 Policy requirement를, lifecycle Domain guard가 상태·version/freshness를 각각 별도로 판정한다.
- 해결책·계획 Agent와 계획 검토 Agent는 Approval·ExecutionAttempt·Verification Row를 생성하거나 변경하지 않는다.
- Agent 간 자유 대화, 무제한 Handoff, Agent별 독립 장기 Memory와 Peer-to-Peer A2A를 금지한다. 전문 Agent Subgraph는 invocation 범위의 Local State만 보유하며 이를 장기 Memory나 Domain 사실로 승격하지 않는다.
- Agent Subgraph Output은 Schema 검증 실패 시 동일 invocation 안에서 최대 1회 Schema Repair하고, 다시 실패하면 Supervisor에 실패 disposition을 반환하여 사용자 확인·부분 결과·차단 중 하나로 전환한다.
- 승인 이후 Tool·Arguments·대상 Resource·Dependency를 LLM이 다시 생성하거나 수정할 수 없다.
- 실행·검증·복구는 결정적 Subgraph와 Domain Command가 담당하며 Agent 판단으로 성공 상태를 확정하지 않는다.

## 25. Agent·Retry 정책

- Tool Route와 Retrieval 책임을 분리한다.
- Tool Route는 IN/OUT Tool을 한 번 확정하고 Retrieval·Planning은 재선택하지 않는다.
- Retrieval의 LLM Node는 Google API·MCP를 직접 호출하지 않는다.
- Supervisor는 결정적 Conditional Edge를 사용한다.
- 일반 Retrieval 호출은 Action Row가 아니다.
- Answer-only Run은 Open Write·UNKNOWN_RESULT·Recovery 상태가 없을 때만 완료한다.
- READ Output Schema 실패는 `FAILED`이며 Approval·Attempt·Verification Row를 만들지 않는다.
- Write `FAILED`는 `FAILED → MODIFIED → 새 승인 → APPROVED`로만 재시도한다.
- `UNKNOWN_RESULT`에서는 기존 결과 확인만 허용한다.
- 승인 이후 LLM은 Tool·Arguments·대상 Resource를 변경할 수 없다.

### POL-EXE-004 Command Receipt

- Domain Aggregate 상태 변경 lifecycle Command는 영속 SQLite `command_receipts`에 등록한다. non-Domain operational Command는 07의 별도 `OperationalCommandReplayPort`를 사용하며 Domain DB receipt를 복구 선행조건으로 만들지 않는다.
- 같은 `command_id`와 같은 Request Hash는 기존 결과를 반환한다.
- 같은 `command_id`와 다른 Request Hash는 보안·무결성 오류로 차단한다.
- Receipt 완료와 Domain 변경은 같은 SQLite Transaction에서 Commit한다.

### POL-EXE-005 MCP 실행 Claim

- Connector Write Tool은 Domain Claim 이후 발급된 1회용 `claim_token`을 요구한다. 단 Claim/Token만으로 dispatch하지 않으며, Core Application은 `BeginExecutionAttempt(applied=true)`와 current Attempt=`EXECUTING`을 외부 호출의 선행조건으로 강제한다.
- Token은 Service Instance, Action, Approval, ExecutionAttempt, Tool, Arguments Hash, 만료와 Nonce에 바인딩한다.
- 재사용·만료·Binding 불일치 Token은 차단하고 Audit한다.
- Token 원문은 Log·Trace·Audit·SQLite에 저장하지 않는다.

### POL-OAUTH-008 Credential Provider 소유권

- Google Authorization Code 교환, Refresh Token 저장·갱신·폐기는 MCP Credential Provider가 소유한다.
- Authorization-code/refresh-token grant는 `oauth_client_id`와 PKCE/state/loopback contract만 소비하며 `client_secret` load/use branch를 두지 않는다.
- FastAPI와 React에는 계정·Scope·연결 상태 Metadata만 반환한다.
- Refresh Token 원문을 FastAPI Process Memory나 React로 복사하는 구현은 금지한다.

## 26. Clarification·조회 범위·일정 관계 정책

- 전체 Gmail Mailbox, 장기간 무제한 원문, 모든 Workspace Source 전체 조회 요청은 `BLOCKED`다. 자동으로 범위를 축소해 실행하지 않는다.
- bounded 범위 확대가 새로 필요하면 이유·Source·기간을 제시하고 사용자 확인 후 수행한다.
- 시간 `overlap`은 곧바로 업무 `conflict`가 아니다. `NESTED_RELATED`, `TRUE_BUSY_CONFLICT`, `TENTATIVE`, `FREE_OR_TRANSPARENT`, `UNKNOWN_RELATION`을 구분한다.
- 모호성은 실제 발견 단계에서 `NEEDS_CONFIRMATION`으로 보내며 후보가 존재하면 후보·차이·선택지를 제공한다.

## 27. 승인 인자·첨부파일 정책

### Claim V2

1. Approval Snapshot은 사용자 의미를 갖는 Canonical Business Arguments와 `approval_arguments_hash`를 고정한다.
2. 실행 준비 과정에서 Recovery Fingerprint 같은 서버 생성 전송 Metadata를 결정적으로 추가할 수 있으나 사용자 의미·Target·Tool을 변경할 수 없다.
3. 최종 MCP Dispatch Payload는 별도 `execution_arguments_hash`로 고정한다.
4. Core Application은 `BeginExecutionAttempt(applied=true)`와 current Attempt=`EXECUTING`을 확인한 뒤에만 MCP 호출을 시작한다. MCP는 실제 수신 인자를 동일 Canonical 규칙으로 재해시하여 서명된 ClaimContextV2의 `execution_arguments_hash`와 비교한 뒤에만 Provider Write한다.
5. Claim Token은 TTL 내 1회용이며 Process Instance와 Action·Approval·Attempt·Tool·두 Hash·Nonce에 바인딩한다.

### 첨부파일

- Gmail 수신 첨부파일 다운로드와 Draft/SEND 첨부파일 전달을 허용한다.
- 첨부파일 bytes·내용은 Agent/LLM Context·Evidence·Prompt 입력으로 사용하지 않는다.
- 발신 파일은 raw Local Path를 Action Argument로 신뢰하지 않고 Staging Descriptor와 SHA-256으로 승인한다.
- Staging 파일이 바뀌거나 Hash가 불일치하면 기존 Approval·Claim을 사용할 수 없다.
- 기존 Gmail Message/Thread 삭제 금지 정책은 그대로 유지한다.

### External LLM prior-consent exact rule

P0 외부 LLM 전송은 persisted Settings의 `external_llm_consent=true`가 선행조건이다. `API_LLM`과 `AUTO`의 API fallback 모두 동일 guard를 사용하고, consent revoke 뒤 새 external inference는 0이다. API Key configured 여부는 동의를 대체하지 않는다. **“Run UI가 external call 전에 범위를 표시한다”의 enforceable 의미는 Browser paint ACK가 아니라, exact inference input에서 계산한 bounded source/data-class `ExternalLlmTransferScopeV1`을 server-side Run projection/checkpoint metadata에 먼저 publish하고 SSE-visible event를 만든 뒤에만 Provider adapter를 호출한다는 순서 보장이다.** P0는 별도 Browser ACK를 consent authority로 만들지 않는다. Retrieval/Route 변화로 전송 scope hash가 커지거나 달라지면 새 scope를 다시 publish한 뒤 다음 external call을 허용한다.
