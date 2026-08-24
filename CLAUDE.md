# Google Work Agent — Claude Code Instructions

이 `CLAUDE.md`는 Claude Code가 저장소에서 작업할 때 항상 적용하는 공통 규칙이다.
특정 작업용 임시 계획이나 장문 보고서를 이 파일에 누적하지 않는다.

## Authority

- 코딩 기준은 현재 저장소 `/docs`의 Canonical snapshot이다.
- 항상 `00 Project Source Guide`에서 Concern Owner와 선행 읽기 순서를 먼저 확인한다.
- behavior는 해당 Concern Owner가 소유하고, repository path/file/symbol/import/single-authority 규칙은 `16 Repository Architecture`가 소유한다.
- 현재 코드, 기존 테스트, Git history, 기존 파일명은 설계 Authority가 아니다. 모두 migration input이다.
- 현재 구현에서 target architecture를 역추론하지 않는다.
- 문서에 없는 state, lifecycle, owner, Port, operation, contract/type, repository convention을 임의로 만들지 않는다.
- 적용된 Migration은 수정하지 않는다. 필요한 DB 변경은 forward Migration으로 추가한다.

## Current Work Mode

현재 작업은 일반적인 behavior-preserving refactor가 아니라
**Canonical design에 기존 구현을 reconciliation하는 migration**이다.

잘못된 기존 구조나 behavior는 “기존 코드이므로 보존”하지 않는다.
반대로 Canonical과 이미 일치하는 구현은 불필요하게 rewrite하지 않는다.

작업 단위는 파일이 아니라 **semantic capability**다.

## Session / Task Start

작업을 시작하면:

1. branch와 working tree를 확인한다.
2. 요청 capability의 `00 Project Source Guide` Concern Owner를 찾는다.
3. 필요한 선행 Canonical 문서를 읽는다.
4. repository mapping이 필요하면 `16 Repository Architecture`와 해당 subordinate mapping을 확인한다.
5. 현재 implementation / writer / caller / effect / test / DI wiring을 semantic search한다.
6. target과 current를 비교해 disposition을 정한 뒤 수정한다.

저장소에서 확인 가능한 내용을 사용자에게 다시 묻지 않는다.

## Work Procedure

각 capability는 다음 순서로 처리한다.

```text
SPEC
→ CANONICAL OWNER / OPERATION / PATH / SYMBOL 확인
→ 기존 semantic implementation / writer / caller / effect / test / DI wiring 검색
→ KEEP | MOVE | RENAME | SPLIT | MERGE | REWRITE | DELETE | CREATE 판정
→ canonical implementation으로 cut-over
→ 모든 production caller 전환
→ old authority / import / export 제거
→ canonical test ownership 정리
→ structural + behavioral regression
```

규칙:

- 새 production file을 만들기 전에 동일 capability의 기존 구현을 먼저 찾는다.
- 하나의 capability에는 하나의 production authority만 허용한다.
- 새 구조 전체를 먼저 구현한 뒤 마지막에 한꺼번에 연결하지 않는다.
- 가능한 한 capability 하나를 완전히 cut-over한 뒤 다음 capability로 이동한다.
- God module은 Canonical semantic responsibility 기준으로 SPLIT/MOVE한다.
- 구조만 틀렸으면 MOVE/RENAME한다. 의미가 틀렸으면 REWRITE한다.
- 중복 구현은 MERGE/DELETE하여 second authority를 남기지 않는다.
- “작은 diff”보다 **가장 작은 완결 capability cut-over**를 우선한다.

## Decision Rules

- Canonical이 명시한 것은 그대로 구현한다.
- Canonical이 implementation choice로 남긴 세부사항만 합리적으로 결정한다.
- 문서가 허용하지 않은 새 semantic owner/package/Port/type/state/operation을 발명하지 않는다.
- Canonical sources를 모두 지키면서 구현을 하나로 결정할 수 없으면 architecture ambiguity/blocker로 보고한다.
- 기존 코드와 Canonical이 다르다는 이유만으로 중단하지 않는다. 그것이 migration 대상이다.
- equivalent production authority가 이미 있으면 두 번째 구현을 추가하지 말고 MOVE/SPLIT/MERGE/REWRITE/DELETE 여부를 먼저 결정한다.

## Architecture / Ownership

핵심 불변조건:

```text
DIRECTORY TELLS OWNERSHIP
FILENAME TELLS RESPONSIBILITY
IMPORT TELLS DEPENDENCY DIRECTION
ONE CAPABILITY HAS ONE PRODUCTION AUTHORITY
```

- Domain: invariant와 lifecycle/domain semantics
- Policy: deterministic allow/block/approval/safety
- Application: use case와 transaction orchestration
- Workflow/LangGraph: State projection, Node/Edge/Interrupt/Resume orchestration
- Port: 외부 boundary contract
- Adapter/Connector: concrete integration
- API: protocol validation/translation
- Composition Root: construction/DI/lifecycle wiring only

금지:

- Core → Provider SDK/API direct call
- Application → concrete Adapter dependency
- Domain → Application/Adapter
- FastAPI Route → DB/Adapter concrete
- Agent → peer Agent direct call
- Agent/LLM → external Write authority
- generic junk drawer (`utils.py`, `common.py`, `helpers.py`, broad global `contracts/models/enums`)
- speculative architecture
- second live production authority

## State / Workflow / Write Safety

- undocumented state/transition/edge/resume target을 만들지 않는다.
- Domain Store는 승인·실행·검증 사실의 기준점이다.
- LangGraph Checkpoint는 workflow resume 위치다.
- UI/SSE/Trace는 Projection이며 Domain truth가 아니다.
- external MCP/Provider/LLM I/O 중 SQLite write transaction을 유지하지 않는다.
- Write는 Canonical Approval → Claim → BeginExecutionAttempt → Connector Write → Verification/Recovery 경계를 따른다.
- ClaimExecution commit만으로 Write하지 않는다.
- `BeginExecutionAttempt(applied=true)` commit 전 Connector Write는 0이어야 한다.
- `UNKNOWN_RESULT`에서 blind resend나 새 Write Attempt를 만들지 않는다.
- Agent/LLM이 승인, policy, state transition, execution success를 최종 판정하지 않는다.

## Compatibility

Compatibility는 migration 수단일 뿐 최종 구조가 아니다.

- 필요한 경우 얇은 delegate/re-export를 일시적으로 사용할 수 있다.
- compatibility layer는 business logic이나 독립 authority를 소유할 수 없다.
- capability cut-over가 끝나면 old caller/path/import/export와 compatibility layer를 제거한다.
- 최종 Canonical target에는 duplicate production authority와 `_compat`가 없어야 한다.

## Tests / Gates

- 기존 테스트도 Authority가 아니다. Canonical owner contract를 검증해야 한다.
- 기존 테스트가 Canonical과 충돌하면 preservation 대상인지 obsolete test인지 판정한다.
- 위험에 비례해 focused → contract/state-transition → safety → integration/component → broader regression → static checks 순으로 검증한다.
- 가능한 Architecture rule은 structural test로 고정한다.
- 관련 safety/contract/state test가 깨진 상태에서 완료라고 보고하지 않는다.
- 기존 baseline 실패와 현재 변경이 만든 실패를 구분한다.

필수 구조 Gate 예:

```text
Application → concrete Adapter       = 0
Domain → Application                 = 0
Core → Provider SDK/direct API       = 0
FastAPI Route → Adapter/DB concrete  = 0
Agent → Provider API/SDK             = 0
Agent → peer Agent direct call       = 0
external I/O inside SQLite write tx  = 0
duplicate production authority       = 0
```

## Completion

Capability는 다음을 모두 만족해야 완료다.

- canonical owner/path/file/symbol 존재
- intended production caller가 canonical authority만 사용
- duplicate writer/authority 0
- old caller/import/export 0
- temporary compatibility 0 또는 아직 끝나지 않은 명시적 dependency만 존재
- relevant Canonical tests 통과
- safety/state/transaction invariant 유지

새 구현을 추가한 것만으로 완료가 아니다.
**기존 authority가 제거되었다는 negative proof까지 필요하다.**

## Git / Scope

- 사용자가 명시하지 않으면 commit, push, merge, rebase, branch switch, destructive Git operation을 하지 않는다.
- 관련 없는 cleanup, formatting-only 대형 diff, dependency-wide upgrade를 만들지 않는다.
- 다른 작업자의 변경을 임의로 되돌리지 않는다.

## Completion Report

완료 보고는 다음만 간결하게 포함한다.

- 변경한 capability
- cut-over / 삭제한 legacy authority
- 테스트·Gate 결과
- 남은 실제 blocker 또는 아직 미완료인 explicit migration dependency

별도 status/report 문서는 사용자가 요청하지 않으면 만들지 않는다.
