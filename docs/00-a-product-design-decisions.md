# 00-A. 제품 설계 결정과 선택 이유

## 제품 형태
Windows 로컬 애플리케이션으로 React UI, FastAPI Local Agent Service, MCP stdio, Google Work MCP Server 내부 Provider Adapter, SQLite, OS Keyring을 사용한다. 원격 SaaS 인프라를 P0에 추가하지 않는다.

## 왜 계층형 Multi-Agent인가
P0의 Agent는 자유 대화형 군집이 아니라 결정적 Supervisor가 전문 LangGraph Subgraph를 조정하는 구조다. SAME semantic responsibility를 SINGLE/THREE/SIX로 나눠 품질·비용·지연·오류 전파를 비교하고 Release Graph를 실험으로 선택한다.

## 왜 State 중심인가
Schema는 출력 가능 범위, State는 확정 정보의 작업 메모리, Prompt는 한 Node의 작업, Edge는 다음 책임을 통제한다. 모든 Node가 전체 State를 보는 구조를 피하고 필요한 Projection만 전달한다.

## 왜 Tool Route를 앞에서 고정하는가
IN(읽기)과 OUT(효과)을 State에 한 번 저장하면 Retrieval/Planning이 Tool을 재선택하지 않아 책임 중복과 오류 전파를 줄일 수 있다. Registry eligibility는 결정적 코드로 검증하되 단순 모델 부담 감소를 위한 의미 손실 shortlist는 금지한다.

## 왜 Google Workspace 접근을 MCP 하나로 고정하는가
제품 Core가 Gmail·Tasks·Calendar Provider API/SDK에 직접 의존하면 Agent/Domain/Sidebar마다 인증·retry·schema·audit 통제가 분산된다. 그래서 `FastAPI/Application/LangGraph/Domain → MCP Client/Port → Google Work MCP Server → Provider Adapter`만 허용한다. MCP 장애 시 direct Provider API fallback을 두지 않아 Tool Allowlist·Claim·Credential·관측 경계를 하나로 유지한다.

## 왜 실행을 Agent 밖에 두는가
Plan Draft 이후 Domain Validation → Approval Snapshot → Claim V2 → MCP 실제 인자 재검증 → MCP Write Tool → MCP 내부 Provider Adapter → MCP Verification Read을 결정적 Engine으로 고정해 모델 품질과 실행 안전성을 분리한다.
