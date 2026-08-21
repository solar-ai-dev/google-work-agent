# Google Work Agent — Repository Architecture Source

> **Status:** CANONICAL_FOR_REFACTOR  
> **Version:** 1.0  
> **Effective:** 2026-08-22  
> **Scope owned by this source:** repository placement, module responsibility, naming grammar, dependency direction, single production authority, refactor procedure.  
> **Semantic behavior remains owned by the concern-specific canonical documents under `/docs/design` and executable Domain/SQL constraints.**

---

# 0. Mandatory Agent Entry Rule

Before creating, editing, moving, or deleting production code:

1. Resolve the **semantic capability** from the specification/domain term.
2. Resolve its **canonical owner directory**.
3. Resolve its **canonical filename/symbol grammar**.
4. Search the repository semantically, not only by filename.
5. Identify every existing implementation of the same capability.
6. Identify the single production caller/authority.
7. If the current implementation is in the wrong location or has the wrong name, **do not create another parallel implementation**.
8. Move/split/merge/delete according to the architecture contract.
9. Preserve semantic behavior unless a separate canonical behavior contract requires a change.

**Current code placement is not architectural authority.**  
For placement/naming/dependency questions, this contract is newer and authoritative.

---

# 1. The Four Repository Invariants

```text
DIRECTORY TELLS OWNERSHIP
FILENAME TELLS RESPONSIBILITY
IMPORT TELLS DEPENDENCY DIRECTION
ONE CAPABILITY HAS ONE PRODUCTION AUTHORITY
```

A production file has one semantic reason to change.

A semantic capability has exactly one live production owner.

---

# 2. Deterministic Spec → Code Translation

Never begin with "which existing filename looks similar?"

Begin with:

```text
SPEC TERM
→ CANONICAL DOMAIN TERM
→ LAYER
→ OWNER PACKAGE
→ OPERATION
→ FILE
→ SYMBOL
```

## 2.1 Canonical domain vocabulary

```text
Run                 → run
Plan                → plan
Action              → action
Approval            → approval
Claim               → claim
ExecutionAttempt    → execution_attempt
Verification        → verification
Recovery            → recovery
ResourceRef         → resource_ref
Conversation        → conversation

Request Understanding → request_understanding
Tool Route            → tool_routing
Retrieval             → retrieval
Work Analysis         → work_analysis
Planning              → planning
Review                → review
```

Do not introduce synonyms when a canonical term exists.

## 2.2 Operation vocabulary

Prefer explicit semantic verbs:

```text
create
get
list
search
update
delete
send
approve
revoke
claim
execute
verify
recover
cancel
block
complete
resume
request
finalize
validate
project
route
assemble
persist
publish
```

Avoid ambiguous verbs:

```text
handle
process
manage
run
do
perform
helper
util
common
```

---

# 3. Canonical Placement Grammar

## Domain

```text
domain/<aggregate>/model.py
domain/<aggregate>/commands.py
domain/<aggregate>/transitions.py
domain/<aggregate>/invariants.py
```

Example:

```text
Run transition
→ domain/run/transitions.py
```

## Application use case

```text
application/use_cases/<aggregate-or-capability>/<verb>_<object>.py
```

Example:

```text
BlockRun
→ application/use_cases/run/block_run.py
→ BlockRunCommand
→ BlockRunResult
→ BlockRunHandler
```

## Six semantic Agents

```text
application/agents/<role>/
```

Roles:

```text
request_understanding
tool_routing
retrieval
work_analysis
planning
review
```

## LangGraph

Main graph:

```text
adapters/langgraph/main/graph.py
adapters/langgraph/main/state.py
adapters/langgraph/main/routing.py
```

Role subgraph:

```text
adapters/langgraph/subgraphs/<role>/graph.py
adapters/langgraph/subgraphs/<role>/state.py
adapters/langgraph/subgraphs/<role>/routing.py
adapters/langgraph/subgraphs/<role>/nodes/<verb>_<object>_node.py
```

A LangGraph node only:

```text
typed projection
→ application call
→ typed owner-field patch
→ optional WorkflowSignal
```

## Persistence port

```text
ports/persistence/<aggregate>_repository.py
```

## SQLite repository

```text
adapters/persistence/sqlite/repositories/<aggregate>_repository.py
```

## Connector operation

```text
adapters/connectors/<provider>/<product>/<resource>/<verb>_<resource>.py
```

Example:

```text
Gmail Create Message
→ adapters/connectors/google/gmail/messages/create_message.py
```

`search_messages.py` MUST NOT also own create/update/delete.

## API

```text
api/routes/<resource>.py
api/schemas/<resource>.py
api/dependencies/<concern>.py
```

API owns transport, not business semantics.

## Launcher

```text
launcher/composition.py
```

Launcher composes dependencies only.

---

# 4. Naming Grammar

| Responsibility | Filename | Primary symbol |
|---|---|---|
| command use case | `<verb>_<object>.py` | `<Verb><Object>Command`, `Result`, `Handler` |
| query use case | `<verb>_<object>.py` | `<Verb><Object>Query`, `Result`, `Handler` |
| domain transition | `transitions.py` | `transition_<aggregate>()` |
| repository port | `<aggregate>_repository.py` | `<Aggregate>Repository` |
| SQLite repository | `<aggregate>_repository.py` | `SQLite<Aggregate>Repository` |
| connector operation | `<verb>_<resource>.py` | `<Verb><Resource>Operation` |
| LangGraph node | `<verb>_<object>_node.py` | `<verb>_<object>_node()` |
| router | `route_after_<stage>.py` or `routing.py` | `route_after_<stage>()` |
| graph | `graph.py` | `build_<scope>_graph()` |
| state | `state.py` | `<Scope>State` |
| projection | `<scope>_projection.py` | `project_<scope>_input()` |

Contract type versioning is allowed:

```text
RequestIntentV2
WorkAnalysisResultV2
```

Parallel production module versioning is not.

Final production filenames must not encode migration history:

```text
canonical_*.py
production_v*.py
legacy_*.py
*_v2.py
*_r2.py
*_r21.py
new_*.py
old_*.py
final_*.py
```

Generic production filenames are prohibited unless explicitly exempted:

```text
runtime.py
manager.py
service.py
helpers.py
utils.py
common.py
misc.py
```

---

# 5. Dependency Direction

```text
API / LangGraph
      │
      ▼
Application
   ├────► Domain
   └────► Ports
             ▲
             │
      Outbound Adapters

Launcher → composes all only
```

## Allowed

```text
Domain      → Domain
Ports       → Domain
Application → Domain + Ports
API         → Application + stable contracts
LangGraph   → Application + Ports
Persistence → Ports + Domain
Connector   → Connector Ports + stable Domain contracts
LLM Adapter → LLM Ports
Launcher    → all layers for composition only
```

## Forbidden

```text
Domain      → Application / Adapter / API
Application → concrete Adapter
Application → provider SDK
LangGraph   → SQLite repository implementation
LangGraph   → Google SDK/API
LangGraph   → concrete MCP transport
LangGraph   → Domain transition implementation
Persistence → Application use case
Connector   → Application workflow
Production  → Evaluation
```

---

# 6. Single Production Authority

For every semantic capability, the project must be able to answer:

```text
What is the one production owner module?
Who calls it?
Which Domain aggregate does it mutate?
Which Port does it depend on?
Which Adapter implements the Port?
```

If two live modules implement the same semantic capability, the repository is structurally invalid.

A migration is complete only when:

```text
new owner is live
+ every production caller moved
+ old owner deleted
+ compatibility wrapper deleted
+ tests target the new owner
```

"New implementation exists" is not completion.

---

# 7. Legacy / Compat

Temporary compatibility code may exist only under a clearly isolated `_compat/` package.

It must declare:

```text
reason
owner being replaced
removal condition
maximum lifetime
```

Public production exports must not permanently point to `_compat`.

Patch-stack inheritance is not an accepted final architecture.

---

# 8. One File = One Responsibility Test

Every production file must pass:

> "This file exists only to own __________."

If the answer requires multiple independent lifecycle operations or multiple aggregates, split it.

Allowed:

```text
create_run.py
  CreateRunCommand
  CreateRunResult
  CreateRunHandler
```

Forbidden:

```text
run_service.py
  CreateRun
  CancelRun
  BlockRun
  RecoverRun
  CompleteRun
```

---

# 9. Mandatory Semantic Search Before Refactor

Do not search only for similar names.

To find all implementations of a capability, inspect:

- every writer of the same Domain aggregate,
- every writer of the same Main State field,
- every caller of the same repository mutation,
- every implementation of the same external effect,
- every handler of the same transition/result enum,
- every exported symbol with equivalent semantics,
- every production caller chain.

Example:

```text
prepare_retry()
modify_action()
rebuild_plan()
reconcile_failure()
```

may all belong to one semantic family even though names differ.

---

# 10. Full Canonical Detail

The normative detail is under:

```text
/docs/design/16-repository-architecture/
```

Read in this order:

```text
00-README.md
01-spec-to-code-mapping.md
02-directory-ownership.md
03-naming-grammar.md
04-dependency-direction.md
05-langgraph-state-ownership.md
06-single-authority-legacy-policy.md
07-refactor-playbook.md
08-architecture-enforcement.md
```

Behavioral semantics still come from their existing concern owners under `/docs/design`.

---

# 11. Agent Stop Rule

If a requested implementation appears to require creating a second implementation beside an existing capability:

**STOP.**

Do not add another file.

Report:

```text
SEMANTIC_AUTHORITY_COLLISION
```

and identify:

```text
existing implementation(s)
actual production caller
canonical target location
required MOVE / SPLIT / MERGE / DELETE plan
```

This rule exists specifically to prevent repository entropy from growing during refactor.
