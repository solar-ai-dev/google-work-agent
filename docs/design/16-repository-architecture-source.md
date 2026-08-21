# Google Work Agent — Repository Architecture Source

> **Status:** CANONICAL_FOR_REFACTOR  
> **Version:** 1.1  
> **Effective:** 2026-08-22  
> **Scope owner:** repository placement, module responsibility, naming grammar, dependency direction, semantic ownership, single production authority, refactor procedure, architecture enforcement.  
> **Behavioral semantics remain owned by 01–15, Domain State Transition Contract, State Transition Test Matrix, and executable Domain/SQL constraints.**

---

# 0. Mandatory Agent Entry Rule

Before creating, editing, moving, or deleting production code:

1. Resolve the semantic capability from the specification/domain term.
2. Resolve the canonical semantic owner.
3. Resolve the layer.
4. Resolve the canonical operation verb.
5. Resolve the canonical path, filename, and symbol grammar.
6. Resolve the mirror unit-test path.
7. Search the repository semantically, not only by filename.
8. Identify every existing implementation and every production caller of the same capability.
9. If the current implementation is in the wrong place/name, move/split/merge/delete it; do not create a parallel authority.
10. Preserve semantic behavior unless a separate concern-specific canonical contract requires a behavior change.

**Current code placement is not architectural authority.**

If a task would create a second live implementation, stop with:

```text
SEMANTIC_AUTHORITY_COLLISION
```

and report existing implementation(s), actual production caller, canonical target location, and the required MOVE / SPLIT / MERGE / DELETE plan.

---

# 1. Repository Invariants

```text
DIRECTORY TELLS OWNERSHIP
FILENAME TELLS RESPONSIBILITY
IMPORT TELLS DEPENDENCY DIRECTION
ONE CAPABILITY HAS ONE PRODUCTION AUTHORITY
```

A production file has one semantic reason to change.

A semantic capability has exactly one live production owner.

---

# 2. Frozen Convention Decisions

The following decisions are closed for structural refactoring:

1. Domain organization follows **canonical semantic owner**, not DB aggregate-root grouping.
2. Domain lifecycle transitions and guards use **operation-per-file**; broad final-production `commands.py` / `transitions.py` buckets are prohibited for multiple independent lifecycle capabilities.
3. Application command/query use cases use **`<Verb><Object>Handler` classes**. Command/Query + Result + Handler for one capability are colocated in one capability file.
4. Contract types are **owner-local**. A global catch-all `contracts/` package is prohibited.
5. `_compat` is allowed only transiently on a structural-refactor integration branch and must be **zero on `main`**.

---

# 3. Deterministic Spec → Code Translation

Never begin with “which existing filename looks similar?”

Use:

```text
SPEC TERM
→ CANONICAL TERM
→ SEMANTIC OWNER
→ LAYER
→ OPERATION
→ PATH
→ FILE
→ SYMBOL
→ TEST PATH
```

Example:

```text
BlockRun
→ run
→ Application Use Case
→ block
→ application/use_cases/run/block_run.py
→ BlockRunCommand / BlockRunResult / BlockRunHandler
→ tests/unit/application/use_cases/run/test_block_run.py
```

Example:

```text
Work Analysis / validate relations / node
→ work_analysis
→ LangGraph adapter
→ adapters/langgraph/subgraphs/work_analysis/nodes/validate_relations_node.py
→ validate_relations_node()
```

Example:

```text
Google / Gmail / Draft / CREATE
→ adapters/connectors/google/gmail/drafts/create_draft.py
→ CreateDraftOperation
```

---

# 4. Canonical Vocabulary

## 4.1 Domain / lifecycle semantic owners

```text
conversation
message
run
plan
action
approval
claim
execution_attempt
verification
recovery
resource_ref
evidence
command_receipt
policy_confirmation_receipt
```

Do not introduce synonyms when a canonical term exists. In particular, do not use `job` for Run, `task` for Action, or a generic `resource` when the semantic type is `ResourceRef`.

Google Tasks `Task` remains the Provider resource noun and is not renamed.

## 4.2 Six Agent semantic owners

```text
request_understanding
tool_routing
retrieval
work_analysis
planning
review
```

Canonical display role is **Tool Routing** and package owner is `tool_routing`. Existing contract artifact `ToolRoutePlanV2` remains unchanged.

## 4.3 Qualified Event names

Bare `Event` is prohibited because several event concepts coexist. Use an explicit qualifier such as:

```text
CalendarEvent
TraceEvent
AuditEvent
WorkflowEvent
SSEEvent
```

## 4.4 Approval vs Claim authority

`Approval`, `ApprovalSnapshot`, and `claim_token` are distinct. `approval_token` must not be used as execution authority. Claim authority remains the Claim contract.

---

# 5. Operation Vocabulary

## 5.1 Resource / external operations

```text
get       exact single lookup by identity/reference
list      collection/container enumeration
search    condition-based candidate retrieval
create    new external resource
update    mutation of an existing external resource
delete    removal effect
send      message send effect
```

`query` is reserved for query-plan/schema concepts and is not a synonym for arbitrary external reads.

## 5.2 Domain lifecycle verbs

Preserve the canonical state-transition vocabulary:

```text
start
begin
request
resume
publish
approve
modify
reject
expire
revoke
claim
store
mark
recover
resolve
prepare
cancel
block
complete
finalize
require
```

Examples such as `StartRun`, `BlockRun`, `ApproveAction`, `ClaimExecution`, `MarkUnknownResult`, `PrepareWriteRetry`, `FinalizeCancel`, and `ResolveRecovery` remain canonical semantic names.

## 5.3 Deterministic transform verbs

```text
validate   check contract/invariant validity
resolve    deterministically determine meaning/target
build      construct a low-level artifact from inputs
assemble   compose prepared artifacts into a higher artifact
map        translate one representation to another
normalize  preserve meaning while canonicalizing representation
project    select an allowlisted downstream view
route      deterministically select the next target
persist    perform persistence
publish    make a durable lifecycle artifact active/available
```

Ambiguous semantic operation names are prohibited:

```text
handle
process
manage
perform
do
run
helper
util
common
```

---

# 6. Artifact Taxonomy

Generic `DTO` naming is prohibited. Use the actual artifact role.

```text
Command      state-changing Application input
Query        read-only Application input
Result       Use Case outcome
Request      external/wire request boundary
Response     external/wire response boundary
Candidate    unvalidated local intermediate
Draft        reviewable/proposable artifact
Snapshot     immutable point-in-time binding
Projection   allowlisted downstream view
Receipt      durable evidence of applied command/user decision
Ref          stable identity/reference
Handle       runtime-local opaque lookup
Policy       product allow/deny rule
Guard        Domain transition precondition
Validator    artifact/contract validity check
Resolver     deterministic meaning/target resolution
Builder      low-level artifact construction
Assembler    composition of prepared artifacts
Mapper       representation translation
Normalizer   semantic-preserving canonicalization
Registry     registered-set lookup authority
Repository   persistence abstraction only
Port         boundary abstraction
Adapter      concrete Port implementation only
```

`Factory` is exceptional and may be used only when a true runtime-selected implementation must be created.

---

# 7. Canonical Placement Grammar

## 7.1 Domain

```text
domain/<owner>/model.py
domain/<owner>/status.py
domain/<owner>/transitions/<verb>_<object>.py
domain/<owner>/guards/<verb>_<object>.py
domain/<owner>/invariants/<semantic_rule>.py
```

`model.py` / `status.py` are architecture-role files and may collect one owner’s model/status definitions. Independent lifecycle operations do not share one final-production transition bucket.

## 7.2 Application use case

```text
application/use_cases/<owner>/<verb>_<object>.py
```

Primary symbols:

```text
<Verb><Object>Command | <Verb><Object>Query
<Verb><Object>Result
<Verb><Object>Handler
```

One capability file may contain its Command/Query, Result, and Handler. Do not split those into three files unless a later explicit contract requires it.

## 7.3 Owner-local contracts

Contracts live with the semantic owner, for example:

```text
application/agents/request_understanding/contracts/request_intent.py
application/agents/tool_routing/contracts/tool_route_plan.py
application/agents/retrieval/contracts/retrieval_result.py
application/agents/work_analysis/contracts/work_analysis_result.py
application/orchestration/contracts/workflow_signal.py
```

Do not create a global miscellaneous `contracts/` bucket.

## 7.4 Agent semantics

```text
application/agents/<role>/
```

Business/semantic computation belongs here, not in LangGraph adapter nodes.

## 7.5 LangGraph

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

A LangGraph node is only:

```text
typed input projection
→ application semantic call
→ typed owner-field patch
→ optional WorkflowSignal
```

## 7.6 Persistence

```text
ports/persistence/<owner>_repository.py
adapters/persistence/sqlite/repositories/<owner>_repository.py
```

Symbols:

```text
<Owner>Repository
SQLite<Owner>Repository
```

Repository means persistence only; it does not own workflow/application semantics.

## 7.7 Connector operation

```text
adapters/connectors/<provider>/<product>/<resource>/<verb>_<resource>.py
```

Primary symbol:

```text
<Verb><Resource>Operation
```

A connector operation file owns one operation. `search_messages.py` cannot also own create/update/delete.

## 7.8 API

```text
api/routes/<plural_resource>.py
api/schemas/<plural_resource>/<verb>_<object>.py
api/dependencies/<concern>.py
```

REST route collection files may aggregate route declarations for one transport resource. API owns transport and schema validation, not business semantics.

## 7.9 Launcher

```text
launcher/composition.py
```

Launcher composes dependencies only.

---

# 8. Workflow Naming Normalization

Repository/node implementation naming uses the following canonical namespaces while preserving behavioral semantics from 06 Workflow:

```text
request_understanding.identify_goal
request_understanding.detect_ambiguity
request_understanding.finalize_intent
request_understanding.validate_intent

tool_routing.determine_io_resources
tool_routing.bind_registry_candidates
tool_routing.select_tool_if_needed
tool_routing.finalize_route
tool_routing.validate_route

retrieval.plan_query
retrieval.build_query
retrieval.execute_read
retrieval.normalize_segments
retrieval.rag_retrieve_rerank
retrieval.select_evidence
retrieval.assess_sufficiency
retrieval.finalize_retrieval

work_analysis.extract_work_facts
work_analysis.resolve_relations
work_analysis.validate_relations
work_analysis.assess_analysis_gaps
work_analysis.assemble_analysis
work_analysis.validate_analysis

planning.choose_answer_or_action_from_route
planning.compose_answer
planning.compose_arguments_per_output_route
planning.build_dependencies
planning.assemble_plan
planning.validate_plan

review.inspect_plan
review.validate_review
review.recheck_plan
```

Planning dependency construction is deterministic. `planning.compose_dependencies` is not a Product Prompt/LLM authority. Repository implementation uses `planning.build_dependencies` semantics for this deterministic step.

---

# 9. Naming Grammar

## 9.1 Python

```text
package / module / function / variable → snake_case
class / type                         → PascalCase
constant / enum value / error code   → UPPER_SNAKE_CASE
```

Enum type names do not use an `Enum` suffix.

Exceptions follow:

```text
<Subject><Condition>Error
```

Avoid broad business errors such as `ProcessingError` or `RuntimeError` as semantic catch-alls.

## 9.2 Package singular/plural

- Domain/Application semantic owner packages: singular.
- REST route collections: plural.
- Provider resource packages: Provider-natural plural nouns are allowed.

## 9.3 Field suffixes

```text
<entity>_id
*_ref / *_refs
*_handle / *_handles
*_hash
*_version
*_at_ms
```

Use predicate prefixes (`is_`, `has_`, `can_`, `should_`) for new boolean fields when applicable. Existing canonical fields such as Domain Command Result `applied` remain unchanged.

## 9.4 Constants

Use `UPPER_SNAKE_CASE`. Equal numeric values with different semantic purposes remain separate constants.

---

# 10. Versioning and Forbidden Production Names

Contract symbol versioning is allowed:

```text
RequestIntentV2
ToolRoutePlanV2
WorkAnalysisResultV2
CommandResponseV1
```

Production implementation module generation/version naming is prohibited:

```text
canonical_*.py
production_*.py
legacy_*.py
new_*.py
old_*.py
final_*.py
*_v2.py
*_v3.py
*_r2.py
*_r21.py
```

Generic production filenames are prohibited unless explicitly listed as architecture-role exceptions:

```text
runtime.py
service.py
manager.py
processor.py
engine.py
handler.py
helpers.py
helper.py
utils.py
util.py
common.py
shared.py
misc.py
```

Explicit architecture-role filename exceptions:

```text
state.py
graph.py
routing.py
model.py
composition.py
```

An exception filename does not permit mixed semantic responsibilities.

---

# 11. Import / Export / Dependency Direction

```text
API / LangGraph
      ↓
Application
   ├──→ Domain
   └──→ Ports
          ↑
   Outbound Adapters

Launcher → composition only
```

Allowed:

```text
Domain      → Domain
Ports       → Domain/stable contracts
Application → Domain + Ports
API         → Application + stable contracts
LangGraph   → Application + stable contracts/Ports as explicitly required
Persistence → Ports + Domain
Connector   → connector Ports + stable contracts
LLM Adapter → LLM Ports
Launcher    → all layers for composition only
```

Forbidden:

```text
Domain      → Application / Adapter / API
Application → concrete Adapter
Application → provider SDK
LangGraph   → SQLite repository implementation
LangGraph   → Google/provider SDK/API
LangGraph   → concrete MCP transport
LangGraph   → Domain transition implementation
Persistence → Application use case/workflow
Connector   → Application workflow
Production  → Evaluation
```

Cross-owner production imports use absolute package imports.

`__init__.py` is empty by default. Only stable public contracts/Ports may be deliberately re-exported. Concrete production authority remains directly importable from its owner module so caller tracing is explicit.

---

# 12. MCP / API / DB / Migration Naming

Existing MCP wire Tool IDs are external/internal interface contract identifiers and are not renamed merely for repository refactoring. Python implementation paths map those IDs to canonical connector operation modules.

DB naming preserves existing schema compatibility:

```text
table          plural_snake_case
column         snake_case
foreign key    <entity>_id
JSON column    <meaning>_json
hash column    <meaning>_hash
timestamp      <meaning>_at_ms
```

Migration filenames:

```text
NNNN_<semantic_change>.sql
```

Applied migrations are immutable. Structural refactoring never renames or rewrites applied migration history.

---

# 13. Test / Fixture Grammar

Unit tests mirror production ownership:

```text
src/.../<verb>_<object>.py
→ tests/unit/.../test_<verb>_<object>.py
```

Test function grammar:

```text
test_<operation>_<object>__<condition>__<expected>
```

Existing `TST-<AREA>-<NNN>` identifiers remain traceability IDs; they do not become production filenames.

Code fixtures:

```text
tests/fixtures/<area>/<semantic_noun>.py
make_<noun>()
```

Static provider fixture data:

```text
tests/fixtures/data/<provider>/<resource>/<scenario>.<ext>
```

Evaluation datasets remain separate from production test fixtures.

---

# 14. Single Production Authority / Compat

For every semantic capability the project must be able to answer:

```text
What is the one production owner module?
Who calls it?
Which Domain owner/fact does it mutate?
Which Port does it depend on?
Which Adapter implements the Port?
```

A migration is complete only when:

```text
new canonical owner is live
+ every production caller moved
+ old owner deleted
+ compatibility wrapper deleted
+ tests target canonical owner
```

“New implementation exists” is not completion.

`_compat` may exist transiently only on the structural-refactor integration branch. `_compat` on `main` is prohibited.

Patch-stack inheritance and permanent compatibility wrapper chains are not accepted final architecture.

---

# 15. Architecture Exception Registry

Architecture exceptions are closed-by-default. Any new exception must explicitly record:

```text
rule being excepted
exact path/symbol
semantic reason
authority owner
scope
removal condition or permanent rationale
approval date
```

Undocumented exceptions are violations.

---

# 16. Mandatory Semantic Search Before Refactor

Do not search only for similar names. To find every implementation of a capability, inspect as applicable:

- writers of the same Domain fact/aggregate,
- writers of the same Main State owner field,
- callers of the same repository mutation,
- implementations of the same external effect,
- handlers of the same transition/result enum,
- exports with equivalent semantics,
- production caller chains,
- tests that exercise the same semantic outcome.

Only after that search may MOVE / SPLIT / MERGE / DELETE begin.

---

# 17. Documentation Authority Boundary

This Source owns **where code lives, what repository/module/symbol names mean, dependency direction, and production-authority uniqueness**.

It does **not** redefine:

- product scope or goals → 01,
- user behavior → 01-A,
- safety/approval policy → 01-B,
- system behavioral boundary → 03,
- persisted facts/state transition semantics → 04 + State Contract + SQL,
- Retrieval semantics → 05,
- Agent/Workflow behavior → 06,
- API/MCP wire contract → 07,
- sequence behavior → 08,
- security → 09,
- infrastructure → 10,
- observability event semantics → 11,
- behavioral regression requirements → 12,
- evaluation → 13,
- operations → 14,
- Prompt/Failure semantics → 15.

When an older document uses a historical implementation/module label, `16` normalizes repository naming without changing the behavioral semantic owned by that document.

---

# 18. Full Canonical Detail

Normative subordinate detail lives under:

```text
/docs/design/16-repository-architecture/
```

Subordinate detail files are not separate Project Source entries. The single Project Source entrypoint is this file.

Read the detail manifest in `16-repository-architecture/00-README.md`.
