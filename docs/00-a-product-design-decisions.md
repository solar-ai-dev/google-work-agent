# 00-A. 제품 설계 결정과 선택 이유

> R8.3 설명 문서. 구현 권위는 01~15의 Concern Owner 문서가 가진다.

## 한 문장으로

Google Work Agent는 Gmail·Tasks·Calendar의 근거를 읽고 업무를 분석한 뒤, **사용자가 승인한 작업만 결정적 실행 엔진으로 수행하는 Windows 로컬 업무 Agent**다.

## 왜 로컬 앱인가

- 개인 Gmail·Tasks·Calendar를 다루므로 사용자 PC에서 실행한다.
- 원격 Backend/SaaS를 두지 않아 P0 운영 복잡도와 데이터 이동을 줄인다.
- React UI와 FastAPI Core는 `127.0.0.1` same-origin으로 연결한다.

## 왜 결정적 Supervisor + Agent Subgraph인가

```text
사용자 요청
→ 결정적 Supervisor
→ 필요한 Agent Subgraph
→ Typed Result
→ Domain·Policy
→ 승인
→ 결정적 Write
→ Verification
```

Agent는 자유 대화형 Peer-to-Peer 군집이 아니다. 각 Agent는 invocation 범위 Local State와 Prompt/Validation/Repair 계약을 가진 LangGraph Subgraph이며, 다른 Agent가 필요하면 Parent에 disposition을 반환한다.

## 왜 1/3/6을 비교하는가

6개 Agent가 좋다고 미리 결정하지 않는다. 같은 의미 책임을 SINGLE=1, THREE=3, SIX=6 Agent Subgraph에 재배치해 품질·비용·지연·오류 전파를 측정하고 Release Graph를 선택한다.

## 왜 Write를 Agent에게 맡기지 않는가

메일 전송·Task/Event 변경은 실제 외부 상태를 바꾼다. 그래서 모든 Profile이 같은 `Domain Validation → Approval → Claim → Execution → Verification → Recovery` 경로를 공유한다. LLM은 승인 뒤 Tool·Arguments·Target을 바꾸지 못한다.
