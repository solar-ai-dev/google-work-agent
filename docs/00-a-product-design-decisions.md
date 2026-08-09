# 00-A. 제품 설계 결정과 선택 이유

> **R8.4 핵심 관점 문서** · 구현 세부값의 권위 문서가 아니며 충돌 시 Concern Owner 계약을 따른다.

## 1. 한 문장으로 설명하면

Google Work Agent는 Gmail·Tasks·Calendar의 실제 근거를 연결해 업무를 이해하고 계획하되, 외부 상태를 바꾸는 권한과 실행 사실은 LLM이 아니라 결정적 소프트웨어가 통제하는 로컬 업무 Agent다.

## 2. 제품 설계 중심 명제

- Agent: 언어 이해, Source 전략, Evidence 선택, 분석, 계획, 검토.
- Supervisor: Phase·Typed Result·Budget 기반 결정적 Routing.
- Domain·Policy: 허용 여부, 상태 전이, 승인·중복·충돌·무결성.
- Execution·Verification: 승인된 Write, Google 재조회, Recovery.

Agent는 판단하고 제안하지만 실행할 권리와 실행 성공의 사실을 소유하지 않는다.

## 3. 왜 1/3/6 Agent를 비교하는가

전문화 자체가 목표가 아니다. 동일한 Semantic Responsibility를 1·3·6 Agent Subgraph에 재배치해 업무 성공, 비용, 지연, 오류 전파, Review 효과를 비교한다.

## 4. 왜 Write Engine은 공통인가

```text
Plan Draft
→ Domain Validation
→ Approval Snapshot
→ Claim V2: 승인 Business Hash + 실제 Execution Hash
→ MCP 실제 수신 인자 재검증
→ Google Write
→ Verification
→ Recovery / Finalize
```

Graph Profile이 달라도 안전 엔진은 동일해야 Agent 구조의 효과와 안전 정책 효과를 분리해 평가할 수 있다.

## 5. 왜 첨부파일을 LLM이 읽지 않는가

R8.4 첨부파일은 **파일 분석 기능이 아니라 Google I/O 기능**이다. Agent는 파일명·MIME·크기 같은 Descriptor만 보고 필요한 파일을 선택할 수 있지만 bytes는 Local API·MCP 경계에서만 이동한다. 이 선택으로 개인정보·Prompt Injection·Token 비용을 늘리지 않고 다운로드·Draft/Send 기능만 제공한다.
