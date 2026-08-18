# 02. Google Work Agent UI · UX 설계서

> **상태:** Draft v2.12 · **기준일:** 2026-08-18 · **대상:** P0 MVP

> **핵심 UX 원칙:** 사용자는 최소한의 행동으로 최대한의 결과를 얻어야 한다. 사용자가 이미 보고 있는 항목과 작업 흐름 안에서 다음 행동을 수행할 수 있어야 하며, 불필요한 화면 이동·재입력·반복 승인은 UX 실패로 본다.

## 1. 문서 목적

이 문서는 Google Work Agent의 화면 구조, 사용자 흐름, 상태 표현, 채팅 내부 Action UI, 오류 복구 UX를 정의한다. 제품은 사용자 PC의 FastAPI Local Agent Service가 제공하는 React UI로 동작한다. 최초 설정을 제외한 핵심 업무 흐름은 메인 화면과 채팅 안에서 끝나야 한다.

## 2. UX 성공 기준

### 2.1 최소 행동

- 정상적인 두 번째 이후 실행은 별도 입력 없이 자동 검사 후 메인 화면에 도달한다.
- 사용자는 기본적으로 자연어 요청 한 번으로 Context 조회와 Action Plan 생성까지 진행할 수 있다.
- 추가 정보가 필요할 때만 한 번의 선택 또는 짧은 입력을 요청한다.
- 여러 Action은 기본적으로 하나의 계획으로 묶어 승인할 수 있고, 필요한 경우에만 Action별로 펼쳐 수정·취소한다.
- 사용자가 Gmail·Task·Event를 보고 있는 위치에서 바로 Agent 행동을 시작할 수 있어야 한다.

### 2.2 화면 이동 최소화

- 승인, 수정, 취소, 재검증, 실행 결과, Recovery는 모두 중앙 채팅 안에서 처리한다.
- Gmail·Tasks·Calendar는 왼쪽 패널에서 탐색하고 현재 채팅 Context로 바로 연결한다.
- 과거 대화는 오른쪽 패널에서 열고 이어서 작업한다.
- 설정과 진단은 상단 버튼에서 Drawer 또는 Dialog로 연다.

### 2.3 자동화와 통제의 균형

- 읽기·검색·분석은 사용자 요청 범위 안에서 자동 진행한다.
- 쓰기 Action만 사용자 승인을 요구한다.
- 앱이 자동으로 판단할 수 있는 값은 먼저 제안하고, 불명확하거나 정책상 필요한 경우에만 질문한다.
- 기술 로그 대신 현재 진행 상황을 이해할 수 있는 한 문장으로 표시한다.

## 3. 실행·화면 구조

### 3.1 실행 구조

```text
Launcher 실행
→ Local Agent Service 시작·Health Check
→ React UI Open
→ Local Session과 API Version 확인
→ 시작 검사 또는 메인 화면
```

운영 빌드는 React 정적 파일과 Local API를 같은 `127.0.0.1` Origin에서 제공한다. 사용자는 Vite, Python, 포트 또는 API 주소를 직접 설정하지 않는다.

### 3.2 전체 화면 구조

제품의 독립 화면은 최소화한다.

1. 시작 검사 화면
2. 최초 설정 온보딩 화면
3. 메인 화면
4. 설정·진단 Drawer 또는 Dialog

Context 검토, 계획, 승인, 실행, 검증, 복구는 별도 페이지가 아니라 메인 화면의 채팅 메시지와 Inline Card로 표시한다.

## 4. 전체 사용자 흐름

```text
앱 실행
→ 시작 검사
→ Google 로그인 상태 확인
→ 최초 설정 또는 저장 설정 검증
→ 메인 화면
→ 자연어 요청 또는 Google 항목에서 Agent 행동 시작
→ 자동 Context 조회
→ 필요할 때만 확인 질문
→ Action Plan 제안
→ 승인·수정·취소
→ 실행
→ Google 재조회 검증
→ 결과 또는 Recovery
```

## 5. UI-001 시작 검사 화면

### 5.1 목적

앱이 사용 가능한 상태인지 자동 확인하고, 필요한 경우에만 사용자의 행동을 요청한다.

### 5.2 구성

- 앱 로고와 제품명
- 전체 진행 Bar
- 현재 검사 중인 항목을 설명하는 한 문장
- 완료·경고·실패 상태
- `자세히 보기` 접힘 영역

### 5.3 검사 순서

1. Launcher·Frontend Build·Local API Contract Version 확인
2. Local Session 수립과 Host·Origin 확인
3. 앱 설정과 버전 확인
4. SQLite 연결과 Migration 확인
5. OS Keyring 접근 확인
6. Google Work MCP 프로세스 확인
7. Google Credential 존재 여부 확인
8. Google Token 갱신과 Gmail·Tasks·Calendar 최소 조회 확인
9. API LLM Key와 연결 확인
10. Ollama와 Local 모델 확인
11. 중단된 Thread·Run 확인
12. SSE 연결과 메인 화면 상태 복원

검사 단계는 다음 두 범주로 구분한다.

- **Core Readiness:** Launcher·Asset·API Contract·SQLite·Migration·Domain·Keyring Adapter·MCP 실행 계약. 실패 시 Safe Mode 또는 진단 UI로 진입한다.
- **Runtime Availability:** Google Credential·필수 Scope·API Key·Ollama·승인 Model. 누락은 Core Service 실패가 아니며 온보딩·설정 Action으로 해결한다.

### 5.4 상태 문장 예시

- `로컬 데이터를 확인하고 있습니다.`
- `저장된 Google 로그인을 확인하고 있습니다.`
- `Gmail·Tasks·Calendar 연결을 확인하고 있습니다.`
- `API LLM 연결을 확인하고 있습니다.`
- `Ollama와 Local 모델을 확인하고 있습니다.`
- `이전 대화를 복구하고 있습니다.`

### 5.5 이동 규칙

- 모든 필수 검사 성공: 메인 화면 자동 이동
- Google 로그인 없음 또는 무효: Google 로그인 요청을 최우선 표시
- 최초 설정 미완료: 최초 설정 온보딩으로 이동
- API LLM만 문제이고 Local 사용 가능: 메인 화면 진입 후 API 경고 표시
- Local만 문제이고 API 사용 가능: 메인 화면 진입 후 API_LLM으로 사용 가능
- 사용 가능한 LLM이 없음: 연결 설정 Action을 표시하고 실행 차단
- 중단 Run 존재: 메인 화면 진입 후 `이전 작업 계속하기` 카드 표시

## 6. UI-002 최초 설정 온보딩

### 6.1 형태

여러 페이지를 넘기는 Wizard가 아니라 하나의 온보딩 화면에서 체크리스트가 순서대로 진행된다. 현재 필요한 행동 하나만 강조하고 완료된 단계는 자동으로 접는다.

### 6.2 진행 순서

1. Google 로그인과 Scope 동의
2. 개인정보·외부 LLM 전송 동의
3. PC와 GPU 환경 자동 진단
4. API LLM 연결
5. Local 사용 가능 환경이면 Ollama·승인 Local Model 상태 확인 및 설치 안내
6. 기본 Calendar·Task List·Timezone 확인
7. 메인 화면 진입

### 6.3 Google 로그인

- 기본 CTA: `Google로 로그인`
- 사용자는 OAuth Client JSON이나 Google Cloud 설정을 입력하지 않는다.
- 로그인 완료 후 계정 이메일과 Gmail·Tasks·Calendar 권한 상태를 표시한다. P0 필수 Scope 하나라도 거절되면 연결 미완료로 표시하고 Agent Run을 차단한다.
- Refresh Token은 OS Keyring에 저장해 다음 실행에서 자동 로그인 검증에 사용한다.

### 6.4 API LLM 연결

- 제품에서 지원하는 Provider와 고정 모델을 표시한다.
- API Key 입력과 `PC에 안전하게 저장` 선택을 제공한다.
- 기본 저장 위치는 OS Keyring이며, `이번 실행에서만 사용`을 선택할 수 있다.
- 연결 검사는 입력 후 자동 실행한다.

### 6.5 Ollama·Local Model 확인과 설치 안내

- GPU 기준을 충족한 `LOCAL_CAPABLE` 환경에서만 표시한다.
- Ollama 존재 여부, Loopback 실행 상태, 지원 Version, 디스크 공간, 승인 Model 존재 여부를 자동 검사한다.
- 앱은 Ollama·Model을 설치·시작·종료·업데이트하지 않는다.
- 누락 시 `설치 안내 열기`, `승인 Model 정보 보기`, `다시 검사`를 제공한다.
- 사용자가 외부 설치를 완료하기 전까지 `LOCAL_GPU`를 비활성화하며 API 사용 가능 여부를 함께 표시한다.
- GPU가 없거나 기준 미달이면 Local 설정·진단 UI와 Local 옵션을 표시하지 않는다.

### 6.6 두 번째 이후 실행

최초 설정 항목을 다시 입력받지 않는다. 시작 검사에서 Credential, API Key, Ollama, 모델, 기본 Resource를 자동 검증하고 문제가 있는 항목만 메인 화면에서 수정 요청한다.

## 7. UI-003 메인 화면

### 7.1 기본 레이아웃

```text
┌──────────────────────────────────────────────────────────┐
│ 상단 Bar                                                  │
├──────────────┬────────────────────────────┬───────────────┤
│ Google 패널  │ Agent 채팅                 │ 대화 내역     │
│ Calendar     │ 진행 문장                  │ Thread 목록   │
│ Tasks        │ 메시지·Inline Action Card  │ 상태·검색     │
│ Gmail        │ 입력창·AI 모드             │               │
└──────────────┴────────────────────────────┴───────────────┘
```

### 7.2 패널 동작

- 왼쪽과 오른쪽 패널은 상단의 간단한 Icon Button으로 각각 열고 닫는다.
- 닫힌 패널은 중앙 채팅 영역을 확장한다.
- 사용자가 선택한 패널 상태와 너비는 로컬에 저장한다.
- 창 폭이 좁아지면 오른쪽 패널부터 자동으로 닫고, 왼쪽 패널은 Overlay 방식으로 연다.

## 8. UI-004 상단 Bar

### 8.1 항상 표시할 항목

- 왼쪽 Google 패널 Toggle
- 제품명
- 연결 상태 요약
- 오른쪽 대화 내역 Toggle
- 설정
- 밝은 모드·야간 모드
- 현재 Google 계정

### 8.2 연결 상태

상세 상태를 여는 기능이 있을 때만 상태 Control을 사용하며, 열리는 화면은 다음 항목을 간단히 보여준다.

- Local Agent API
- Event Stream
- Google
- MCP
- API LLM
- Ollama
- Local 모델
- 마지막 검사 시간

정상 Google 연결은 Header 정중앙의 비대화형 compact chip으로 표시한다. chip은 green status dot과 `Google 연결됨` 문구, 충분한 padding과 높이를 가지며 button semantics를 사용하지 않는다. 경고나 오류가 있을 때만 Badge와 해결 Action을 보여준다.

## 9. UI-005 왼쪽 Google 서비스 패널

### 9.1 목적

Gmail·Tasks·Calendar를 확인하는 동시에 현재 항목에서 바로 Agent 행동을 시작한다.

### 9.2 공통 구성

- `Calendar`, `Tasks`, `Gmail` 탭
- 검색·필터
- 마지막 갱신 시간
- 수동 새로고침
- Gmail·Tasks는 페이지당 **20개**의 Resource 목록. Calendar는 Month View visible grid를 사용하며 numeric pagination을 사용하지 않음
- Gmail·Tasks는 이전·다음 목록 페이지 이동, Calendar는 이전·다음 월 이동
- 단일 선택과 다중 선택
- 원본 Google 서비스에서 열기
- 현재 채팅 Context로 추가
- 선택된 항목에서 Agent 요청 시작

### 9.3 행동 안에서 행동

각 Resource Card는 단순 조회에서 끝나지 않고 해당 항목을 기준으로 Agent 요청을 시작할 수 있어야 한다.

#### Gmail Card Action

- `이 메일 정리`
- `해야 할 일 찾기`
- `답장 Draft 제안`
- `채팅에 추가`

#### Task Card Action

- `일정 제안`
- `관련 메일 찾기`
- `관련 마감 확인`
- `채팅에 추가`

#### Calendar Card Action

- `회의 준비`
- `후속 업무 찾기`
- `관련 메일 찾기`
- `채팅에 추가`

이 Action들은 즉시 Google 쓰기를 수행하지 않는다. 선택한 Resource와 의도를 중앙 채팅에 전달해 Agent 분석을 시작하며, 쓰기 결과는 채팅 안에서 승인받는다.

### 9.4 목록 조회와 Pagination

- 앱 시작 화면에서는 Google 연결 상태와 계약된 최소 runtime metadata만 확인하며 사이드바 전체 목록을 선조회하지 않는다.
- 사용자가 Source 탭을 처음 열면 Local API가 Application → MCP Tool 경계로 목록을 조회한다. Frontend와 FastAPI Route는 Google Provider API를 직접 호출하지 않는다.
- Gmail·Tasks의 visible UI page size는 **20개**다. Agent Retrieval page size 20과 숫자가 같더라도 별도 계약이다.
- Gmail은 Local API의 opaque continuation을 사용한다. intermediate traversal은 필요한 최소 metadata만 읽고 visible target page를 hydrate한다. 이미 hydrate한 page 재방문은 React Client Session Cache를 사용한다.
- Tasks는 Provider metadata batch를 최대 100개까지 받고 React Session Cache에서 UI 20개 page로 slice한다. 100개+continuation이면 초기에는 1..5 page만 알고, 알려진 마지막 page에서 다음 batch를 append한다.
- Calendar Month View는 사용자 timezone의 visible grid 전체를 materialize하고 numeric pagination을 사용하지 않는다. 이전·다음 월 이동은 새 grid 조회다.
- Local API `next_page_token`은 opaque continuation이다. Frontend는 이를 Provider token·offset·총 페이지 수로 해석하지 않는다.

### 9.5 Source별 기본 정렬

- Gmail: 최근 수신 메일부터 표시
- Tasks: 미완료 우선, 예정일 임박 순, 예정일 없는 Task 순
- Calendar: 현재 이후의 가장 가까운 일정부터 표시
- 과거 Calendar 조회에서는 최근 과거 일정부터 표시

### 9.6 React Client Session Cache

- Cache Key는 Google 계정, Source, 검색·필터, 정렬, Page Token 조합으로 구성한다.
- 목록 Metadata와 Page Token은 React Client Session Cache에만 유지한다.
- UI 세션 종료, Google 계정 변경, 해당 Source 수동 새로고침 시 관련 Cache를 삭제한다.
- 사이드바 목록과 사용되지 않은 검색 결과를 SQLite에 영구 저장하지 않는다.
- 수동 새로고침을 누르면 해당 Source Cache를 비우고 첫 페이지를 최신 데이터로 다시 조회한다.

### 9.7 Resource 선택

- 사용자는 하나 또는 여러 개의 Gmail·Task·Event를 선택할 수 있다.
- 한 개를 클릭하면 Preview와 해당 Resource에서 수행할 수 있는 빠른 Agent Action을 표시한다.
- Row click은 Focus Resource와 Preview만 갱신하고, checkbox는 별도의 다중 선택 Context 집합만 변경한다. Focus 변경은 기존 선택 집합을 변경하지 않는다.
- 선택 Resource가 하나 이상이면 Composer 가까이에 선택 수와 사용자 의미 label을 compact하게 표시한다. 별도의 `선택 항목으로 요청`, `채팅에 추가`, `선택 해제` Action Bar는 표시하지 않는다.
- Composer 전송은 선택 집합이 있으면 중복 없는 전체 Resource ID를 `RESOURCE_SELECTED` Context로 전달하고, 선택 집합이 없으면 `AGENT_SEARCH`로 시작한다.
- 선택된 Resource의 ID, Source, 제목과 최소 Metadata를 중앙 채팅의 Context로 전달한다.
- 사용자가 이미 선택한 사람·날짜·제목을 채팅에서 다시 입력하도록 요구하지 않는다.

### 9.8 두 가지 Agent 진입 방식

#### 사용자 선택형

사이드바에서 선택한 Resource의 최신 상세를 조회해 초기 Context로 사용한다. 관련 Source 검색은 사용자의 요청을 수행하는 데 필요한 경우에만 확장한다.

#### Agent 검색형

사용자가 Query, 날짜·기간, 사람·이메일, Keyword 또는 복합 요구사항을 채팅에 입력하면 Agent가 Source와 검색 조건을 구조화하고 Google Source-native 검색을 수행한다. 목록 후보를 축소한 뒤 필요한 후보만 상세 조회한다.

## 10. UI-006 중앙 Agent 채팅

### 10.1 역할

사용자 요청, Agent 진행 상태, Context, 확인 질문, 계획, 승인, 수정, 실행, 검증, 복구를 하나의 연속된 대화로 처리한다.

### 10.2 채팅 Header

- 대화 제목
- 현재 Google 계정
- 현재 선택 AI 모드
- 실제 실행 Runtime
- 새 대화

### 10.3 AI 모드 설정

입력창 가까이에 Compact Selector로 표시한다.

- API_ONLY 환경: `API_LLM`만 표시
- LOCAL_CAPABLE 환경: `AUTO`, `LOCAL_GPU`, `API_LLM`
- Active Run 중에는 모드 변경을 잠근다.
- AUTO가 API로 전환되면 전환 이유를 채팅 상태 문장으로 표시한다.

### 10.4 입력창

- 자연어 입력
- 전송
- 현재 첨부된 Gmail·Task·Event 수
- 실행 중일 때 중단
- Enter 전송, Shift+Enter 줄바꿈
- 기본 상태는 1줄 높이의 compact 입력창이며 입력 내용에 따라 높이가 자동으로 늘어난다. 최대 높이에 도달하면 Composer 전체가 계속 커지지 않고 입력창 내부 scroll로 전환한다. 전송 후 입력값이 비워지면 다시 1줄 높이로 돌아온다.
- 전송 Button은 입력창과 같은 행에 위치하며 Composer는 Center 하단에서 항상 접근 가능하다.
- 하나의 대화에서 동시에 하나의 Active Run만 허용

같은 Conversation에는 여러 번의 USER 요청과 그에 대응하는 여러 Run이 순차적으로 존재할 수 있다. 이전 Run이 종료되면 사용자는 같은 Conversation에서 후속 요청뿐 아니라 이전 요청과 업무적으로 무관한 새 요청도 이어서 입력할 수 있다. Frontend는 새 요청의 업무 관련성을 판단해 새 대화를 강제하거나 자동으로 유도하지 않는다. 대화 맥락을 의도적으로 분리하고 싶을 때는 사용자가 직접 `+ 새 대화`를 선택한다.

## 11. 진행 상태 UX

### 11.1 기본 표현

기술적인 Node 이름이나 로그 대신 사용자가 이해할 수 있는 현재 작업 문장 하나를 표시한다.

예시:

- `요청의 목표를 확인하고 있습니다.`
- `관련 Gmail 메일을 찾고 있습니다.`
- `기존 Task와 중복되는지 확인하고 있습니다.`
- `Calendar에서 가능한 시간을 확인하고 있습니다.`
- `실행 계획을 정리하고 있습니다.`
- `사용자 승인을 기다리고 있습니다.`
- `승인된 작업을 실행하고 있습니다.`
- `Google에서 실행 결과를 다시 확인하고 있습니다.`

### 11.2 상세 정보

Source 수, 검색 Query, Tool 이름, Latency 등은 `자세히 보기`에서만 표시한다. 일반 사용자는 상세 정보를 보지 않아도 현재 단계와 다음 행동을 이해할 수 있어야 한다.

## 11-A. Local API와 Event Stream UX

### Command 처리

- 사용자 입력, 승인, 수정, 거절, 취소는 REST Command로 제출한다.
- Command 제출 중 Button을 잠그되 UI 잠금만으로 중복 실행을 보장하지 않는다.
- 성공 응답에는 현재 Aggregate Version과 상태를 반영한다.
- Timeout 발생 시 같은 Write를 추정 재실행하지 않고 Run·Action Snapshot을 조회한다.

### SSE 연결

- Run 시작 시 해당 Run Event Stream을 구독한다.
- 연결 상태는 정상일 때 숨기고 재연결 중일 때만 작은 상태 문구로 표시한다.
- 연결이 끊겨도 실행 실패로 표시하지 않는다.
- 마지막 Event Cursor 이후 재구독하고 불가능하면 현재 Snapshot을 다시 조회한다.
- Event 순서가 뒤바뀌거나 중복되면 Event Cursor와 Aggregate Version으로 오래된 화면 갱신을 무시한다.

### Service 장애

Local Agent Service가 응답하지 않으면 화면 전체를 초기화하지 않고 다음을 제공한다.

- 연결 다시 시도
- Launcher 상태 확인
- 진단 정보 보기
- 마지막 저장 상태 표시
- 앱 안전 종료

## 12. UI-007 오른쪽 대화 내역 패널

### 12.1 목적

현재 메시지를 반복 표시하는 영역이 아니라 저장된 대화 Thread를 탐색하고 이어서 작업하는 영역이다.

### 12.2 구성

- 새 대화
- 대화 검색
- 오늘·어제·최근 7일·이전 분류
- 실행 중
- 승인 대기
- 실패
- 완료

### 12.3 대화 항목

- 자동 생성 대화 제목
- 마지막 활동 시각
- 현재 상태
- Action 수 또는 실패 수
- 이름 변경 (P1, 27절 참고)
- 삭제 (P1, 27절 참고)

`Conversation.title`은 최초 USER 요청을 기반으로 대화 생성 시 한 번 생성되는 안정적인 식별 제목이다. 같은 Conversation에 후속 요청이나 업무적으로 무관한 새 요청이 여러 Run으로 추가되어도 title을 자동 재생성하거나 최신 USER 메시지로 덮어쓰지 않는다. "마지막 활동 시각"은 `Conversation.updated_at_ms`이며 개별 Message 내용과는 다른 값이다. 최근 USER 메시지 preview 표시는 P0 요구사항이 아니다.

대화를 선택하면 중앙 채팅에서 해당 Thread와 Checkpoint를 복원한다. 과거 승인은 다시 실행에 사용하지 않는다.

## 13. 채팅 내부 UI 유형

채팅에는 다음 메시지와 Inline Card 유형이 필요하다.

1. 사용자 메시지
2. Agent 일반 응답
3. 진행 상태 문장
4. Context 요약 Card
5. 확인 질문 Card
6. Action Plan Card
7. 승인 요청 Card
8. 수정 Form Card
9. 실행 상태 Card
10. 검증 결과 Card
11. 오류·Recovery Card
12. 완료 요약 Card

### 13.1 사용자 메시지와 Timeline 표시

- 사용자 메시지는 중앙 Conversation에서 우측 정렬 Message Bubble로 표시하며, 메시지마다 역할 이름을 반복 표시하지 않는다. Bubble 배경은 오른쪽 선택된 Conversation row와 같은 계열의 연한 accent 색을 사용한다.
- 각 메시지에는 저장된 `created_at_ms`를 사용자 Local Timezone으로 변환한 짧은 시간만 표시한다. 현재 시각으로 대체하지 않는다.
- Timeline은 사용자 Local Calendar Date 기준으로 메시지를 묶고, 날짜가 바뀌는 지점에만 Date Separator를 표시한다. 같은 날짜 안에서는 반복하지 않는다.
- Date Separator 문구는 오늘 `오늘`, 어제 `어제`, 올해의 다른 날짜는 `8월 13일` 형태이며 연도가 다르면 연도를 포함한다.
- 오래된 Conversation을 다시 사용하면 이전 날짜 그룹은 유지되고 새 활동 날짜에 새 Date Separator가 추가된다. Timeline 전체가 Conversation의 최초 날짜에 고정되지 않는다.
- Conversation을 선택·복원하면 Timeline은 최신 메시지가 보이는 위치를 기본 viewport로 사용한다. 같은 Conversation에 새 USER 메시지가 추가되면 Timeline은 다시 최신 메시지가 보이도록 이동한다. 이 범위를 넘는 unread-scroll 상태 관리는 P0 요구사항이 아니다.

모든 Card는 같은 대화 흐름 안에서 상태가 갱신되고, 결정 완료 후 기존 Button은 비활성화된다.

## 14. Context 요약과 확인 질문

### 14.1 Context 요약

기본적으로 Source 수와 핵심 근거만 보여준다.

```text
관련 정보를 찾았습니다.
Gmail 2개 · Tasks 1개 · Calendar 3개

[내용 보기] [일부 제외] [추가 검색]
```

전체 메일 원문은 기본 접힘으로 유지하며 원본 Google Resource 링크를 제공한다.

### 14.2 확인 질문

앱이 확정할 수 없는 정보만 한 질문으로 요청한다.

- 동명이인
- 불명확한 기간
- Event 예상 소요시간 누락
- Calendar 또는 Task List 후보
- 복수의 관련 메일
- 외부 이메일 주소 확인
- 충돌 Override 여부

후보가 있으면 직접 입력보다 후보 선택을 우선한다. 질문에 답하면 같은 Run을 이어서 진행한다.

## 15. Action Plan과 승인 UX

### 15.1 계획 요약

여러 Action은 기본적으로 하나의 Plan Card에 묶는다.

```text
3개의 작업을 제안합니다.
- Task 생성 1개
- Calendar Event 생성 1개
- Gmail Draft 생성 1개

[승인하고 실행] [내용 수정] [취소]
```

### 15.2 상세 펼치기

각 Action을 펼치면 다음을 확인할 수 있다.

- Action 유형과 대상 시스템
- 생성 또는 수정할 필드
- 변경 전·후 값
- Evidence
- 중복·충돌·위험
- 선행·종속 Action
- 예상 실행 결과

### 15.3 승인

- 승인 시 Card 상태를 `승인됨`으로 고정한다.
- 실행 전 Approval Hash, 현재 Resource, Policy를 다시 검증한다.
- 검증을 통과하면 같은 Card 아래에서 실행 상태를 표시한다.
- 승인 Button은 재클릭할 수 없다.

### 15.4 취소

- 취소한 Action은 실행하지 않는다.
- 종속 Action도 함께 차단되는 경우 영향 범위를 바로 표시한다.
- `취소됨` 응답은 같은 Card에 기록한다.

### 15.5 수정

- `내용 수정`을 선택하면 Card 자체가 편집 Form으로 전환된다.
- 사용자는 현재 화면에서 허용 필드만 수정한다.
- 수정 완료 후 Schema·Policy·중복·충돌을 자동 재검증한다.
- 재검증을 통과하면 같은 위치에서 다시 승인받는다.

수정 가능한 필드:

- Gmail Draft: 수신자, CC, 제목, 본문
- Task: 제목, 메모, 예정일, Task List
- Calendar Event: 제목, 시작, 종료, 설명, Calendar

## 16. 실행과 검증 UX

### 16.1 실행 상태

Action별로 다음 상태를 표시한다.

- 대기
- 실행 중
- 성공
- 검증 중
- 검증 성공
- 실패
- 차단
- 검증 불일치

### 16.2 부분 성공

성공한 Action을 유지하고 실패 또는 종속 차단 상태를 구분한다.

```text
Task 생성       성공
Event 생성      실패
Gmail Draft     선행 Action 실패로 차단
```

### 16.3 검증 성공

Google에서 재조회한 값이 승인 내용과 일치하면 핵심 필드와 원본 Resource 링크를 표시한다.

### 16.4 검증 불일치

승인 값과 실제 값을 필드별로 비교한다.

선택 가능한 행동:

- 수정 제안 만들기
- 현재 결과 유지
- Google에서 열기

자동으로 다시 수정하지 않는다.

## 17. 중단·오류·Recovery UX

### 17.1 분석 중 중단

Google 데이터 변경이 없음을 표시하고 현재 Checkpoint를 저장한다.

### 17.2 쓰기 실행 중 중단

이미 Google API에 전달된 요청이 있을 수 있으므로 즉시 취소 완료로 표시하지 않는다.

```text
중단 요청을 받았습니다.
현재 실행 중인 작업의 실제 결과를 확인하고 있습니다.
```

재조회 후 실제 성공·실패·미실행 상태를 확정한다.

### 17.3 오류 Card

- 사용자용 오류 설명
- 현재까지 완료된 작업
- 실패한 단계
- 데이터 변경 여부
- 권장 행동

가능한 Action:

- 다시 시도
- Google 재로그인
- API_LLM으로 전환
- Run 재개
- 계획 다시 생성
- 설정 또는 진단 열기

## 18. UI-008 설정·진단 Drawer

설정 때문에 메인 작업 화면을 떠나지 않는다. 상단 버튼에서 Drawer 또는 Dialog로 연다.

### 18.1 일반

- 밝은 모드·야간 모드
- 언어
- 시작 시 패널 상태
- 기본 화면 배치

### 18.2 Google

- 현재 계정
- 권한 상태
- 재로그인
- 계정 변경
- 연결 해제
- 기본 Calendar
- 기본 Task List

### 18.3 AI

- 기본 AI 모드
- API Key 상태와 저장 방식
- API 연결 검사
- Ollama 상태
- Local 모델 상태
- 테스트 추론

### 18.4 업무 환경

- Timezone
- 업무 시작·종료 시간
- 주말 포함 여부
- 일정 Buffer

### 18.5 데이터

- 채팅·Run 보존
- 로그 삭제
- Credential 삭제
- 전체 앱 초기화

삭제·초기화처럼 되돌릴 수 없는 작업은 명시적 확인 Dialog를 사용한다.

## 19. 상태 소유권과 저장

<table fit-page-width="true" header-row="true">
	<tr>
		<td>상태</td>
		<td>소유 위치</td>
		<td>규칙</td>
	</tr>
	<tr>
		<td>패널·Drawer·현재 탭·입력 중 Text</td>
		<td>React Client State</td>
		<td>화면 상태이며 실행 사실이 아님</td>
	</tr>
	<tr>
		<td>Sidebar 목록·Page Token</td>
		<td>React Client Session Cache</td>
		<td>세션 종료·계정 변경·새로고침 정책에 따라 폐기</td>
	</tr>
	<tr>
		<td>Conversation·Message·Run·Action</td>
		<td>SQLite Domain Store</td>
		<td>대화와 업무 사실의 기준점</td>
	</tr>
	<tr>
		<td>Graph State·Interrupt</td>
		<td>LangGraph Checkpointer</td>
		<td>Workflow 재개 위치의 기준점</td>
	</tr>
	<tr>
		<td>OAuth Refresh Token·API Key</td>
		<td>OS Keyring 또는 Process Memory</td>
		<td>Frontend·SQLite·Event에 원문 노출 금지</td>
	</tr>
	<tr>
		<td>비밀이 아닌 사용자 설정</td>
		<td>Local Settings</td>
		<td>테마·패널·기본 Resource 등을 저장</td>
	</tr>
</table>

브라우저 새로고침, 탭 복제, REST Retry, SSE 재연결로 동일 Write Action이 반복되지 않도록 승인 결정, Action 상태, Aggregate Version, Idempotency Key는 Domain Store에서 확인한다.

Local Storage에는 Secret, Approval Token 원문, Gmail 전체 원문, 실행 사실을 저장하지 않는다. Frontend는 화면 복원 시 Local API에서 최신 Snapshot을 조회한다.

## 20. API_ONLY와 LOCAL_CAPABLE 차이

### API_ONLY

- API_LLM만 표시
- Ollama·Local 모델 설정·진단 UI 숨김
- API Key 연결 실패 시 Agent 실행 차단
- GPU가 없는 팀원과 CPU-only 사용자 기본 경로

### LOCAL_CAPABLE

- `AUTO`, `LOCAL_GPU`, `API_LLM` 제공
- Ollama와 제품 모델 상태 표시
- 명시적 LOCAL_GPU 실패 시 자동 전환하지 않고 API 전환 Action 제공
- AUTO fallback 발생 시 이유와 실제 Runtime 표시

공통 UI, Agent 흐름, 승인 정책, Tool Schema는 두 프로필에서 동일하다.

## 21. P0 반응형 기준

- 기준 환경: Windows 11 x64, 최신 Chrome·Microsoft Edge, `127.0.0.1` same-origin React UI
- 넓은 화면: 3열 레이아웃
- 중간 폭: 오른쪽 패널 자동 접힘
- 좁은 폭: 중앙 채팅 우선, 양쪽 패널 Overlay
- 중앙 입력창과 승인 Button은 항상 접근 가능해야 한다.

## 22. 접근성·표현 규칙

- 상태를 색상만으로 구분하지 않고 Icon과 문구를 함께 사용한다.
- 주요 Button은 동사 중심으로 작성한다.
- 위험 Action은 결과를 함께 표시한다.
- 기술 용어보다 사용자 행동과 결과를 우선 표시한다.
- 오류 메시지는 원인, 현재 상태, 다음 행동을 포함한다.
- Keyboard로 채팅 입력, 후보 선택, 승인·취소가 가능해야 한다.

## 23. 금지 UX

- Context, 계획, 승인, 실행 결과를 각각 별도 페이지로 분리
- 정상 실행에서 매번 Source를 직접 선택하도록 요구
- Agent가 이미 확인한 사람·날짜·Resource를 다시 입력하도록 요구
- 읽기·검색 Action마다 승인 요청
- 같은 Plan을 시스템별로 반복 승인하도록 강제
- 수정 후 별도 화면에서 저장·검증·승인을 반복
- 기술 로그를 기본 화면에 상시 노출
- GPU가 없는 PC에 Local 설치 Action 노출
- 사용자가 한 번 결정한 승인 Button을 다시 실행 가능하게 유지
- Local Agent API·SSE 연결 오류를 Google Write 실패로 단정
- Browser Local Storage를 승인·실행 사실의 기준점으로 사용
- React Frontend에서 Google API·Keyring·SQLite를 직접 호출
- 실행 중인 쓰기를 결과 확인 없이 취소 완료로 표시

## 24. P0 UX 완료 조건

- 두 번째 이후 정상 실행에서 사용자 입력 없이 메인 화면까지 도달한다.
- 자연어 요청 한 번으로 Context 조회와 Plan 생성이 가능하다.
- Gmail·Task·Event Card에서 한 번의 Action으로 Agent 작업을 시작할 수 있다.
- 사용자는 Source별 최신 기본 목록을 페이지 단위로 탐색할 수 있다.
- 동일 세션에서 이미 조회한 페이지로 돌아가면 추가 API 호출 없이 즉시 표시된다.
- 하나 또는 여러 Resource를 선택해 채팅 Context로 전달하고 그 위치에서 Agent 요청을 시작할 수 있다.
- Agent 검색형과 사용자 선택형 요청이 동일한 승인·실행·검증 흐름으로 연결된다.
- 승인·수정·취소·실행·검증·복구가 채팅을 벗어나지 않고 완료된다.
- 승인 Button 중복 클릭, REST Retry, 브라우저 새로고침이나 SSE 재연결로 중복 쓰기가 발생하지 않는다.
- API_ONLY와 LOCAL_CAPABLE 환경에서 같은 핵심 사용자 흐름을 제공한다.
- 연결 오류가 발생하면 사용자가 설정 위치를 찾지 않아도 현재 화면에서 해결 Action을 실행할 수 있다.

## 25. Multi-Agent 진행 표시

- UI는 내부 Agent 대화를 노출하지 않고 `요청 이해 → 도구 경로 결정 → 자료 검색·근거 선택 → 업무 분석 → 실행 내용 작성 → 계획 검토 → 승인 대기 → 실행 → 검증` 단계를 표시한다.
- `agent_role`, `subgraph_name`, 내부 Prompt와 비공개 추론은 기본 화면에 표시하지 않는다.
- 계획 검토 결과 `REVISE`, `RETRIEVE_MORE`, `CONFIRM`, `BLOCK`은 각각 계획 수정, 추가 검색, 사용자 확인, 실행 불가 상태로 투영한다.
- 다중 LLM 호출은 하나의 Run 진행으로 묶고, 브라우저 새로고침 후 Run Snapshot과 Domain Store를 재조회한다.
- React Client State와 SSE Event는 Agent Handoff·Checkpoint·승인·실행 사실의 기준점이 아니다.

## 26. Agent 진행·결과 UX

사용자 단계:

```text
요청 이해 → IN/OUT 경로 결정 → 자료 검색·RAG 근거 선택 → 필요한 경우 업무 분석
→ 실행 내용 작성 → 계획 검토 → 승인 대기 → 실행 → 결과 확인
```

- Tool Route 결정과 Retrieval/RAG는 서로 다른 진행 단계로 표시한다.
- Agent Prompt·비공개 추론·자유 Handoff는 표시하지 않는다.
- 같은 IN Route의 추가 Retrieval은 같은 Run에서 최대 2회 진행하며, 새 Resource/Connector가 필요하면 Tool Route 재검토로 표시한다.
- Answer-only 결과에는 승인·실행 Card를 표시하지 않는다.
- READ-only Plan에는 실행 상태 Card만 표시하고 승인 Button은 표시하지 않는다.
- Write 실패 후 기존 Approval을 재사용하는 즉시 재실행 Button을 제공하지 않는다.

## 27. UX 실행 계약

### Local Session 전 화면

- `/health/live`, `/health/ready` 결과와 Bootstrap 교환 화면만 표시한다.
- Bootstrap 성공 전 일반 `/api/v1/*` Command를 보내지 않는다.

### OAuth 연결

- UI는 OAuth 시작 Command와 시스템 Browser 이동만 요청한다.
- Callback·Token 교환·Keyring 저장은 MCP Credential Provider가 처리하며 UI에는 Token을 노출하지 않는다.

### 중복 Command

- 전송 중 Button 잠금은 UX 보조 수단이다.
- Timeout 후 새 `command_id`를 만들지 않고 기존 ID로 상태를 조회·재전송한다.
- 같은 ID의 기존 결과가 있으면 해당 Snapshot을 반영한다.

### 대화 관리 범위

- P0: 새 대화, 대화 목록·검색·선택·재개.
- P1: 대화 이름 변경·대화 삭제.

## 28. Clarification 선택 UX
- 후보가 존재하면 자유입력만 요구하지 않고 후보 선택을 우선 표시한다.
- 후보에는 번호/라벨/회사·팀·업무 등 의미 있는 차이/최근 관련 Resource를 표시한다.
- 후보 선택 후에도 `처리/진행/시작`의 동작 의미가 불명확하면 필요한 최소 질문만 이어서 한다.
- 문맥으로 의미가 확정되면 추가 질문하지 않는다.
- 확인 응답 후 새 Run을 만들지 않고 같은 Run·LangGraph Thread를 Resume한다.

예시:
```text
'김 대리' 후보가 여러 개 있습니다.
1. 한빛건설 김 대리 — 최근 견적 회신
2. 세진중공업 김 대리 — 납품 일정
3. 디자인팀 김 대리 — 시안 검토
어느 김 대리 건인가요?
```

## 29. Main UI 구현 계약

### 29.1 Desktop 정보 구조

```text
Header: Google Work Agent | Google 연결 상태 | 현재 계정 | 설정
Left:   Google 업무 자료 (메일·Tasks·Calendar, 검색/필터, Resource List, 숫자 페이지)
Center: 선택 Resource Detail Viewer → Agent Conversation → Inline Status/Approval → Chat Input
Right:  Conversation (새 대화·검색·목록) → Recent Execution
```

- Center가 주 작업 공간이며 Dashboard나 개발자 Runtime 상태를 우선하지 않는다.
- Header는 제품명, 사용자 이해가 가능한 Google 연결 상태, 현재 계정, Settings만 기본 노출한다. `WAITING_APPROVAL`, node 이름, profile(`SINGLE/THREE/SIX`), `API_LLM`, `LOCAL_GPU`, `MCP READY`, `SSE CONNECTED` 같은 개발·Runtime 문자열은 Main에서 숨기고 Settings/Diagnostics로 옮긴다.
- Browser P0에서 창 최소화·최대화·닫기 표식은 시각 장식이나 제품 Window Control 기능으로 정의하지 않는다.
- App shell(상단 Bar·3 Panel)은 고정되고 페이지 단위로 스크롤되지 않는다. 좌·우 Panel과 Center Conversation Timeline은 각자 영역 안에서 독립적으로 scroll하며, Composer는 Center 하단에서 항상 접근 가능하다.

### 29.2 Left Resource Panel

- 탭은 메일, Tasks, Calendar이며 검색/필터와 수동 새로고침을 제공한다. 목록은 compact row, selected/hover/focus/disabled 상태와 키보드 탐색을 제공한다.
- Gmail·Tasks의 기본 visible UI page size는 20이다. Local API의 opaque continuation을 React Session Memory에서 이미 materialize한 page/batch와 연결해 숫자 page UI를 제공한다. Agent Retrieval 20과 혼용하지 않는다. Calendar는 Month View visible grid이며 numeric page를 만들지 않는다.
- Tasks 기본 목록은 **미완료 Task 전체**를 대상으로 하고, Calendar 기본 Upcoming 범위는 사용자 Timezone 기준 **현재부터 향후 90일** Event다.
- Gmail badge는 기본 `INBOX + PRIMARY` scope의 exact count가 확정된 경우에만 exact로 표시한다. Tasks badge는 incomplete batch의 terminal/continuation 상태에서 계산하고 terminal까지 materialize되면 exact total을 확정한다. Calendar tab에는 numeric badge가 없다. Frontend 전체 페이지 순회·hard code count는 금지한다.
- 행을 선택하면 Center 상단 Viewer에 제공 가능한 Resource 상세를 표시한다. Gmail sender/recipient/subject/received time/body/attachment metadata, Task title/task_status/scheduled_date/list/notes, Calendar title/start/end/attendees/location/description/calendar는 제공된 필드만 표시한다. 누락값의 추정·생성은 금지한다.
- 선택 Resource는 Center 상단의 독립 Card/Box로 표시해 아래 Conversation Timeline과의 시각적 경계를 명확히 한다.
- Resource Detail Viewer 기본 상태는 compact preview다. 제목·주요 Metadata와 제한된 길이의 본문 preview를 표시하고 `...`로 자르며 원문 접근을 막지 않는다. 전체 내용은 `펼치기`로 확인한다.
- 펼친 상태는 `접기`로 되돌릴 수 있고 bounded 영역 안에서 내부 scroll을 사용한다. Resource Detail이 Center 높이의 상당 부분을 항상 차지하지 않게 하여, 일반 상태에서는 Conversation Timeline이 남은 공간을 사용하고 Composer 접근성을 우선한다.
- Focus Resource와 다중 선택 Resource 집합을 분리한다. Focus는 Viewer용이며 다중 선택은 기존 Agent Context 기능을 보존한다.

### 29.3 Center Conversation과 Approval

- Chat은 `Viewer → Conversation → Inline 상태/Action/Approval → Input` 순서다. 사용자에게는 업무 단계와 다음 행동을 보이고 Agent node/profile/prompt는 표시하지 않는다.
- Quick Action은 Agent 요청의 Entry Point다. 직접 Google Write를 실행하지 않는다.
- Write Approval은 compact inline card다. `확인`, `수정`, `건너뛰기` 버튼은 기존 `approve`, `modify`, `reject` Command에 연결한다. Action/Tool, Target, 변경 요약, Evidence, Risk, Expected Result는 실제 Projection이 존재하는 값만 Summary + detail expand에 표시한다.
- pending/submitting/completed 상태에서는 중복 클릭을 막고, timeout 또는 SSE 단절은 Write 실패로 단정하지 않는다. Snapshot 재조회 또는 cursor 재구독으로 복구한다.

### 29.4 Right Panel, Settings, 반응형

- Conversation은 새 대화, 검색, 목록을 제공하고 선택 시 Center를 복원한다. Resource type은 Conversation의 분류 기준이 아니다.
- Recent Execution은 실제 Projection이 있을 때만 표시하며, 없으면 숨기거나 Empty State를 표시한다. Fake history는 금지한다.
- Settings/Diagnostics는 Drawer/Dialog다. 기존 사용자 설정과 Runtime/Model 진단을 구분해 보존한다.
- Desktop은 3 panel이다. 폭이 줄면 Right를 먼저 collapse하고, 이후 Left는 collapse 또는 overlay로 전환한다. Center와 Chat Input, Approval action은 항상 접근 가능해야 한다.

### 29.5 공통 상태와 접근성

- 모든 주요 영역은 Loading, Empty, Error, Selected, Hover, Focus, Disabled, Submitting, Approval pending, Completed 상태를 사용자 행동과 함께 명시적으로 표현한다.
- 색만으로 상태를 구분하지 않고 icon/문구를 함께 사용한다. 키보드로 탭, 목록, 대화, 승인, 취소, 입력을 사용할 수 있어야 하며 focus가 명확해야 한다.
- 오류는 원인, 현재 상태, 다음 행동을 제시한다. 민감 정보·secret·개발 Runtime 상세를 Main에 노출하지 않는다.

## 30. Calendar·Tasks Sidebar 및 Viewer Empty State

### 30.1 Calendar Sidebar

- Event row는 제목 아래에 시간 범위를 표시한다. 같은 날 시간 Event는 `YYYY년 M월 D일 (요일) 오전/오후 h:mm - 오전/오후 h:mm`이며 연도·월·일·요일·시작 시간·종료 시간을 모두 표시하되 날짜는 한 번만 쓴다.
- 날짜가 다른 Event는 시작일과 종료일을 각각 식별할 수 있도록 표시한다. All-day Event는 `YYYY년 M월 D일 (요일) · 하루 종일`이다.
- Sidebar에는 `시작`, `종료` label을 표시하지 않는다. 중앙 Resource Viewer에는 제공된 `시작`, `종료` 상세 필드를 유지한다.
- 실제 Event Projection에 없는 색상 dot·원형 marker·priority·category·status badge·내부 Google ID·Page Token을 추가하지 않는다. 선택 Event는 기존 row의 background/focus styling만 사용한다.
- Upcoming 기본 조회 범위는 사용자 Timezone 기준 현재부터 **향후 90일**이다. 사용자가 기간을 지정하면 지정 범위를 우선한다.

### 30.2 Tasks Sidebar

- Tasks는 실제 Google Workspace Source이며 기본 compact row는 **Task 제목 → 예정일** 순서다. 제목, 메모, 예정일, Task List, 완료 상태 중 실제 Projection이 제공한 값만 사용한다.
- Task List는 실제 반환 값일 때만 보조로 표시할 수 있으며, priority, 가짜 category·Task List 이름·색상 dot는 표시하지 않는다.
- 목록 정렬은 미완료·예정일 임박 우선의 기존 계약을 유지한다.
- Local API Projection은 Provider `needsAction`을 `미완료`, `completed`를 `완료`로 정규화한다. raw enum과 RFC3339 raw `due`는 UI에 노출하지 않는다.
- Google `due`는 UI에서 `예정일`로만 표시한다. 예정일이 없으면 날짜 영역을 비우거나 생략하며, API에 없는 작업 시간·업무 마감일을 생성하지 않는다.
- 미완료 Task의 예정일이 지났을 때만 보조 문구 `예정일 지남`을 표시할 수 있다. 이는 상태를 완료로 바꾸지 않으며 `기한 초과`·`마감 초과`로 표현하지 않는다. Provider가 제공한 완료 날짜는 `완료일`로 표시할 수 있다.

### 30.3 Resource Viewer Empty State

- 중앙 Viewer 제목은 `자료 상세`로 Source 공통이다. Focus가 없을 때 메일은 `왼쪽 목록에서 메일을 선택하면 상세 내용을 확인할 수 있습니다.`, Tasks는 `왼쪽 목록에서 태스크를 선택하면 상세 내용을 확인할 수 있습니다.`, Calendar는 `왼쪽 목록에서 일정을 선택하면 상세 내용을 확인할 수 있습니다.`를 표시한다.
- Source 전환 시 이전 Source의 Focus 및 상세 정보는 남지 않는다. 새 Source의 Empty State를 먼저 표시하고, 행 Focus 후 해당 Source의 실제 Projection 상세만 표시한다.

## 31. Gmail 첨부파일 UX

- Gmail Message에 첨부파일이 있으면 파일명·유형·크기를 표시한다.
- 사용자가 선택한 파일만 다운로드하며 첨부파일 내용을 Agent가 자동 요약·분석하지 않는다.
- Draft/Send Action에서는 첨부 예정 파일명·유형·크기를 승인 카드에 함께 표시한다.
- 파일이 Staging 만료·Hash mismatch로 무효화되면 기술 오류 대신 “파일을 다시 선택해야 합니다”를 표시하고 기존 승인 버튼을 재사용하지 않는다.
- 첨부파일은 별도 화면을 만들지 않고 기존 Message 상세·Action 승인 흐름 안에서 처리한다.
