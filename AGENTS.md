# Google Work Agent — Codex Instructions
- 이 `AGENTS.md`는 저장소 루트 전체에 적용한다.
- 하위 `AGENTS.md`가 있으면 해당 경로 작업에는 함께 적용한다.
- 하위 규칙은 경로별 convention을 추가할 수 있지만 이 파일의 Canonical·안전·의존성 경계를 약화시키면 안 된다.
- 최종 patch의 모든 수정 파일에 적용되는 instruction을 확인한다.

## Source of truth
- 공식 설계 원본은 Notion이다. 저장소에서는 `00-PROJECT-SOURCE-GUIDE.md`로 현재 Canonical과 Concern Owner를 먼저 확인한다.
- Canonical은 목표 동작, 코드·테스트·Migration·Runtime wiring은 현재 구현의 근거다.
- 문서와 구현이 다르면 숨기지 말고 `IMPLEMENTATION_DELTA`로 분리한다. 구조 리팩터링에서 의미를 몰래 바꾸지 않는다.
- 과거 버전이 남은 파일명만 보고 권위를 판단하지 않는다. 적용된 Migration은 소급 수정하지 않는다.

## 작업 시작
1. branch와 working tree를 확인한다.
2. 요청 Concern의 Canonical Owner와 관련 문서만 읽는다.
3. 실제 구현, 소비자, 테스트, DI wiring을 확인한다.
4. 이미 존재하는 기능·경계를 중복 구현하지 않는다.
5. 요청 범위 안에서 가장 작은 완결 변경을 정한다.
- 저장소에서 확인 가능한 내용을 사용자에게 다시 묻지 않는다.

## Architecture
```text
React → FastAPI API → Application / Workflow → Domain / Policy
Application / Workflow → Port ← Connector Adapter
→ Connector Registry / MCP Runtime → Connector MCP Server → Provider Adapter/API
```
- P0 첫 Connector는 `google_workspace`이며 Gmail·Tasks·Calendar를 제공한다.
- Composition Root는 생성·DI·lifecycle wiring만 소유한다. 업무 정책, SQL, Workflow routing, Provider 동작을 구현하지 않는다.
- 금지: Core의 Provider API/SDK 직접 호출, MCP 장애 direct fallback, Application→concrete Adapter, Domain→Application/Adapter, Route→DB/Adapter concrete, Agent→peer Agent direct call, Agent/LLM의 Write 권한.

## Ownership
- Domain: invariant, 상태 전이, domain vocabulary
- Policy: deterministic allow/block/approval/safety
- Application: use case와 transaction orchestration
- Workflow: graph phase/routing/handoff
- Port: 외부 capability 계약
- Adapter/Connector: integration-specific 구현
- API: protocol validation/translation
- Composition Root: construction/wiring
- `Enum`, `Literal`, DTO, `TypedDict`, `dataclass`, `Protocol`, type alias, constant, exception, validator, normalizer, mapper도 실제 의미 Owner가 소유한다.
- 공유 계약을 대형 구현 파일이 소유하게 두지 않는다. Local-only 타입은 불필요하게 공용 contract로 승격하지 않는다.

## Cohesion / abstraction
- 목표는 작은 파일이 아니라 **change locality**다. 한 Concern 수정 시 관련 Owner 몇 개만 읽으면 되게 유지한다.
- 새 동작 추가 전 `기존 Owner가 있는가 / 두 번째 책임이 생기는가 / 새 cross-layer dependency가 생기는가`를 확인한다.
- junk drawer(`utils.py`, `common.py`, `helpers.py`, `shared.py`, 전역 `enums.py`/`models.py`)를 만들지 않는다.
- 미래 Connector를 상상한 speculative interface, LOC 감소만을 위한 분할, forwarding/call-chain만 늘리는 distributed spaghetti를 금지한다.
- Port는 실제 외부 경계·교체 가능 구현·독립 테스트 capability가 있을 때 usage-driven으로 추출한다.
- 800 LOC 이상은 cohesion review, 1200 LOC 이상은 responsibility audit 신호일 뿐 강제 분할 기준이 아니다.

## Broad refactor freeze
- R1~R7 이후 광범위 구조 리팩터링은 기본 동결한다.
- 파일 길이, 디렉터리 미관, 이름 통일, interface 추가 가능성만으로 broad refactor를 시작하지 않는다.
- 다음 실제 결함이 증명될 때만 최소 local refactor를 허용한다: 책임 혼재, shared contract의 implementation 종속, dependency violation, private reach-through, service locator, unsafe transaction/I/O ownership, facade의 business logic 누적, circular/lateral dependency, 심각한 poor change locality, Canonical 기능을 올바른 Owner에 넣을 수 없는 구조.
- 구조 수정은 증명된 문제만 고치며 새 전면 아키텍처 재설계로 확대하지 않는다.

## LangGraph / LLM
- Main Graph는 deterministic Supervisor다. Agent는 전문 LangGraph Subgraph이며 invocation-local state를 사용한다.
- Node는 필요한 Typed Projection만 받는다. 공식 Main State Artifact는 단일 Owner를 가진다.
- LLM은 해석·분석·작성 후보를 만든다. deterministic code가 routing guard, policy, authorization, state transition, execution authority, verification/recovery 허용 여부를 결정한다.
- Agent가 Tool을 임의 재선택하거나 Provider call/Write를 직접 실행하게 만들지 않는다.
- Prompt/Schema/State/Edge 책임을 섞지 않는다.
- ToolRoutePlanV2, RAG, lineage, Confirmation/Resume 등 Canonical behavior 구현은 구조 리팩터링과 분리한다.

## Write safety
```text
Approval → Claim → Claim commit → tool/args/hash/token 검증
→ Connector Write → result persistence → Verification Read → deterministic recovery
```
반드시 유지:
- Unauthorized Write = 0
- Claim commit 전 Write = 0
- reused/invalid Claim Write = 0
- Tool mismatch Write = 0
- arguments/hash mismatch Write = 0
- UNKNOWN_RESULT blind resend = 0
- required Verification 누락 = 0
- Recovery 자동 성공 오판 = 0
- SQLite write transaction 중 external I/O = 0
- `UNKNOWN_RESULT`는 자동 재전송하지 않고 Recovery로 간다.
- 안전 코드 구조 변경은 characterization → 작은 extraction → focused safety tests 순서로 하고 behavior change와 섞지 않는다.

## State / DB / transaction
- Domain Store가 승인·실행·검증 사실의 기준점이다. LangGraph Checkpoint는 재개 위치이며 SSE/UI는 Projection이다.
- undocumented state/transition을 만들지 않는다.
- optimistic concurrency, command receipt/idempotency, aggregate invariant를 유지한다.
- SQLite write transaction은 짧게 유지하고 Provider/MCP/LLM I/O를 transaction 안에서 기다리지 않는다.
- Schema 변경은 새 Migration으로 한다.

## Compatibility
- 필요한 기존 import/path는 얇은 re-export/delegate facade로 유지할 수 있다.
- Compatibility facade는 새 business logic을 갖지 않고 canonical implementation에만 위임한다.
- private 이름이라는 이유만으로 소비자 조사 없이 삭제하지 않는다.

## Prompt / Dataset / Evaluation
- Product Prompt에 gold, grader, expected answer/route, benchmark 정보를 넣지 않는다.
- Prompt/Dataset은 최신 Canonical 기준으로 수정한다.
- 코드 변경이 필요한 차이는 `IMPLEMENTATION_DELTA`로 보고하고 Prompt/Dataset에 억지로 흡수하지 않는다.
- 구조 리팩터링과 Prompt/Dataset 의미 변경을 섞지 않는다.
- 실제 사용자 Google 데이터는 일반 자동 평가/fixture에 사용하지 않는다.

## Tests / gates
- 명령어를 추측하지 말고 저장소 실제 설정을 확인한다.
- 위험에 비례해 focused → contract/state-transition → safety → integration/component → broader regression → lint/format/type/schema 순으로 검증한다.
- 가능한 Architecture rule은 자동 회귀 테스트로 고정한다.
```text
Application → concrete Adapter       = 0
Domain → Application                 = 0
Core → Provider SDK/direct API       = 0
FastAPI Route → Adapter/DB concrete  = 0
Agent → Provider API/SDK             = 0
Agent → peer Agent direct call       = 0
external I/O inside SQLite write tx  = 0
```
- 기존 baseline 실패와 현재 작업이 만든 실패를 구분한다. 관련 safety/contract test가 깨진 상태에서 완료라고 보고하지 않는다.

## Git / scope
- 사용자가 명시하지 않으면 commit, push, merge, rebase, branch switch, destructive Git operation을 하지 않는다.
- 관련 없는 cleanup, dependency-wide upgrade, broad rename, formatting-only 대형 diff를 만들지 않는다.
- 작업 중 외부 commit/변경이 나타나면 덮어쓰지 말고 충돌 여부를 확인한다.

## Completion
완료 전 확인: 요청 Concern 완결, Canonical Owner/의존 방향 준수, 중복 path 없음, 필요한 compatibility 보존, safety/state/transaction invariant 유지, 관련 테스트/static check 통과, unrelated change 없음.
완료 보고는 `변경 내용 / 보존 경계 / 테스트 결과 / 기존 baseline 실패 / 남은 IMPLEMENTATION_DELTA 또는 live 검증`만 간결하게 포함한다.
별도 status/report 문서는 사용자가 요청하지 않으면 만들지 않는다.
