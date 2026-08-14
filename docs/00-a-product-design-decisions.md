# 00-A. 제품 설계 결정과 선택 이유

> 설명 문서이며 구현 세부값의 권위 문서가 아니다. 충돌 시 01/03/04/05/06/07 Concern Owner를 따른다.

## 1. 한 문장

Google Work Agent는 Connector 확장 가능한 Core가 외부 업무 시스템의 실제 근거를 연결해 업무를 이해하고 계획하되, **외부 상태를 바꾸는 권한과 실행 사실은 LLM이 아니라 결정적 소프트웨어가 통제**하는 로컬 업무 Agent다.

## 2. 중심 설계 결정

1. **LLM과 deterministic safety engine 분리** — 언어·업무 의미는 모델이, 승인·상태·무결성·실행·검증은 코드가 소유한다.
2. **결정적 Supervisor** — Agent끼리 직접 호출하지 않고 Typed Disposition을 Parent에 반환한다.
3. **Typed Main State + Local State** — 공식 Handoff만 Main State에 올리고 후보·Repair·RAG 내부 상태는 Subgraph Local State/Run Cache에 둔다.
4. **Tool Route 선결정** — IN/OUT Resource·Effect·Tool을 한 번 정한 뒤 Retrieval/Planning이 재선택하지 않는다.
5. **Retrieval과 Planning 분리** — Retrieval은 고정 IN Route에서 Query/Read/RAG/Evidence, Planning은 고정 OUT Route에 Arguments를 작성한다.
6. **동일 Write Engine** — 1/3/6 Agent Profile 모두 동일 Approval→Claim→Write→Verification/Recovery Engine을 쓴다.
7. **Domain Store와 Checkpoint 분리** — Checkpoint는 재개 위치, Domain은 실제 승인·실행 사실이다.
8. **Agent별 장기 Memory 없음** — 최신 Connector 원본·Main State·Domain Store를 기준으로 한다.
9. **로컬 제품** — P0 단일 사용자 범위에서 데이터·Credential 경계를 로컬로 좁힌다.
10. **Connector 확장** — Core는 Registry/MCP 계약에 의존하고 Provider API/SDK는 Connector 내부 Adapter만 소유한다.

## 3. 왜 1/3/6인가

Agent 수 자체가 목표가 아니다. 같은 Semantic Responsibility를 1·3·6 Subgraph로 나눠 **Business Task Success, 오류 격리, Review 효과, LLM Call/Token/Latency/Handoff 비용**을 비교하기 위한 실험 변수다.
