# Google Work Agent — Repository Architecture Source

> **Status:** CANONICAL_FOR_REFACTOR  
> **Version:** 1.4  
> **Effective:** 2026-08-22  
> **Scope owner:** repository placement, module responsibility, naming grammar, repository import/export dependency realization and enforcement, semantic ownership, single production authority, refactor procedure, architecture enforcement.

## Mandatory invariants

```text
DIRECTORY TELLS OWNERSHIP
FILENAME TELLS RESPONSIBILITY
IMPORT TELLS DEPENDENCY DIRECTION
ONE CAPABILITY HAS ONE PRODUCTION AUTHORITY
```

## Frozen convention decisions

- Domain organization follows **canonical semantic owner**, not DB aggregate-root grouping.
- Domain lifecycle transitions and guards use **operation-per-file**; broad `commands.py` / `transitions.py` / `guards.py` buckets are not final production structure.
- Application command/query use cases use **`<Verb><Object>Handler` classes** with colocated Command/Query + Result in one capability file.
- Contract types are **owner-local**; there is no global catch-all `contracts/` package.
- `_compat` may exist only transiently on a structural-refactor integration branch and must be **zero on `main`**.
- Workflow v7.22 / Prompt Contract v1.28 atomic LLM responsibilities are represented repository-side as operation-per-file. `work_analysis`, `planning`, and `review` responsibilities must not collapse back into broad production modules such as `analyze.py`, `planning.py`, or `review.py`.
- LangGraph routing is **operation-per-file** under `routing/route_after_<stage>.py`; catch-all final-production `routing.py` is prohibited.
- Naming and placement are **closed-world**. If a construct does not match this Source or its normative subordinate grammar, an Agent may not invent a local convention.

## Deterministic spec-to-code rule

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

Current code placement is never architecture authority. Before adding production code, search semantically for every existing implementation and production caller. If a second live implementation would be created, stop with `SEMANTIC_AUTHORITY_COLLISION`.

## Canonical semantic vocabulary

Domain/lifecycle owners:

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

Agent owners:

```text
request_understanding
tool_routing
retrieval
work_analysis
planning
review
```

Do not replace these with synonyms such as `job`, `manager`, `processor`, or generic `runtime` terminology.

## Canonical operation vocabulary

External/resource operations:

```text
get
list
search
create
update
delete
send
```

Domain lifecycle verbs preserve the state-transition contract:

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

Deterministic transform verbs:

```text
validate
resolve
build
assemble
map
normalize
project
route
persist
publish
```

Ambiguous semantic operation names are prohibited: `handle`, `process`, `manage`, `perform`, `do`, `run`, `helper`, `util`, `common`.

## Artifact taxonomy

Use the artifact name that states the actual role; generic `DTO` naming is prohibited.

```text
Command   state-changing application input
Query     read-only application input
Result    use-case outcome
Request/Response external wire/API boundary only
Candidate unvalidated local intermediate
Draft     reviewable/proposable artifact
Snapshot  immutable point-in-time binding
Projection allowlisted downstream view
Receipt   durable evidence of an applied command/user decision
Ref       stable identity/reference
Handle    runtime-local opaque lookup
Policy    product allow/deny rule
Guard     domain transition precondition
Validator artifact/contract validity check
Resolver  deterministic meaning/target resolution
Builder   low-level artifact construction
Assembler composition of prepared artifacts
Mapper    representation translation
Normalizer canonical representation transform
Registry  registered-set lookup authority
Repository persistence abstraction only
Port      outbound/inbound boundary abstraction
Adapter   concrete Port implementation only
```

`Factory` is exceptional and allowed only for true runtime-selected implementation creation recorded by the Exception Registry.

## Placement grammar

Application use case:

```text
application/use_cases/<owner>/<verb>_<object>.py
<Verb><Object>Command | Query
<Verb><Object>Result
<Verb><Object>Handler
```

Domain transition:

```text
domain/<owner>/transitions/<verb>_<object>.py
→ transition_<verb>_<object>()
```

Domain guard:

```text
domain/<owner>/guards/<verb>_<object>.py
→ guard_<verb>_<object>()
```

Agent semantic operation:

```text
application/agents/<role>/<verb>_<object>.py
→ <verb>_<object>()
```

Each versioned atomic responsibility owned by 06/15 maps to exactly one owner-local operation file unless 06/15 explicitly defines it as deterministic composition rather than an LLM responsibility.

Owner-local contract type:

```text
application/agents/<role>/contracts/<artifact_name>.py
→ <ArtifactName>[Vn]
```

There is no global production `contracts/` package. Main/subgraph state types remain in the architecture-role `state.py` files owned by LangGraph.

LangGraph adapter:

```text
adapters/langgraph/main/graph.py
adapters/langgraph/main/state.py
adapters/langgraph/main/routing/route_after_<stage>.py

adapters/langgraph/subgraphs/<role>/graph.py
adapters/langgraph/subgraphs/<role>/state.py
adapters/langgraph/subgraphs/<role>/routing/route_after_<stage>.py
adapters/langgraph/subgraphs/<role>/nodes/<verb>_<object>_node.py
```

Router symbol grammar is `route_after_<stage>()`.

LangGraph input projection:

```text
adapters/langgraph/main/projections/<scope>_projection.py
adapters/langgraph/subgraphs/<role>/projections/<scope>_projection.py
→ project_<scope>_input()
```

A projection file owns one allowlisted input projection.

Persistence:

```text
ports/persistence/<owner>_repository.py
adapters/persistence/sqlite/repositories/<owner>_repository.py
```

Connector operation:

```text
adapters/connectors/<provider>/<product>/<resource>/<verb>_<resource>.py
```

API:

```text
api/routes/<plural_resource>.py
api/schemas/<plural_resource>/<verb>_<object>.py
api/dependencies/<concern>.py
```

## Workflow repository naming normalization

Repository semantic owner/package is `Tool Routing` / `tool_routing`; existing contract artifact `ToolRoutePlanV2` remains unchanged.

Versioned runtime identifiers and PromptRef IDs remain owned by 06 Workflow / 15 Prompt·Failure and are **not silently renamed by this document**. Workflow v7.22 / Prompt Contract v1.28 explicitly version the heavy-Agent atomic responsibility IDs; Repository Architecture v1.4 maps those same semantic capabilities to canonical repository owner/path/file/symbol names. `planning.compose_dependencies` does not exist as a Product Prompt/LLM authority; dependency construction is deterministic `planning.build_dependencies`.

The following list defines canonical repository implementation capability labels aligned with the currently versioned 06/15 semantic IDs:

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
work_analysis.resolve_entity_relations
work_analysis.resolve_temporal_dependencies
work_analysis.detect_duplicate_conflict_candidates
work_analysis.validate_relations
work_analysis.assess_information_gaps
work_analysis.assess_operational_risks
work_analysis.assemble_work_analysis
work_analysis.validate_work_analysis

planning.choose_answer_or_action_from_route
planning.outline_answer
planning.compose_answer
planning.draft_action_objective_per_output_route
planning.compose_arguments_per_output_route
planning.build_dependencies
planning.assemble_plan
planning.validate_plan

review.inspect_goal_and_evidence
review.inspect_action_scope_and_route
review.inspect_constraints_and_policy_summary
review.aggregate_review_findings
review.validate_review
review.recheck_affected_dimensions
```

A LangGraph node is a thin adapter only: typed projection → application call → typed owner-field patch → optional WorkflowSignal.

## Naming restrictions

Contract symbol versioning is allowed (`RequestIntentV2`, `WorkAnalysisResultV2`). Production implementation module generation/version naming is prohibited.

Final production filenames must not use:

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
config.py
errors.py
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

Explicit architecture-role filename exceptions are exactly:

```text
state.py
graph.py
model.py
composition.py
```

`routing.py` is not an exception.

## Package and symbol rules

- Domain/Application semantic owner packages are singular.
- REST collection routes are plural.
- Provider resource packages may use the Provider's natural plural resource noun.
- Cross-owner production imports use absolute package imports.
- `__init__.py` is empty by default; only stable public contracts/Ports may be explicitly re-exported. Concrete production authority must remain directly importable from its owner module.
- Bare `Event` is prohibited: use `CalendarEvent`, `TraceEvent`, `AuditEvent`, `WorkflowEvent`/`SSEEvent` as applicable.
- `Approval`/`ApprovalSnapshot` and `claim_token` are distinct. `approval_token` must not be used as execution authority.
- `Ref` means stable reference; `Handle` means runtime-local opaque lookup.
- Deterministic semantic operation functions use `<verb>_<object>()`; Application command/query entry points use `<Verb><Object>Handler` classes.
- Validators, resolvers, builders, assemblers, mappers, and normalizers use `validate_`, `resolve_`, `build_`, `assemble_`, `map_`, and `normalize_` filename/function prefixes.
- Registries are owner-local noun authorities: `<subject>_registry.py → <Subject>Registry`.
- Errors are owner-local and use `<subject>_<condition>_error.py → <Subject><Condition>Error`.
- Configuration modules are owner-local and semantic. Generic `config.py` is not a production naming escape hatch.

## Test and migration grammar

Unit tests mirror production ownership:

```text
src/.../<verb>_<object>.py
→ tests/unit/.../test_<verb>_<object>.py
```

Test functions:

```text
test_<operation>_<object>__<condition>__<expected>
```

Existing `TST-<AREA>-<NNN>` traceability IDs remain unchanged.

Migrations:

```text
NNNN_<semantic_change>.sql
```

Applied migrations are immutable and must never be renamed or rewritten for structural refactoring.

## Repository dependency realization

System/layer dependency semantics are owned by 03 Architecture. This section defines their repository import/export realization and enforcement and may not relax 03.

```text
API / LangGraph → Application → Domain + Ports ← Outbound Adapters
Launcher → composition only
```

Forbidden includes Domain→Application/Adapter/API, Application→concrete Adapter/provider SDK, LangGraph→SQLite implementation/provider SDK/concrete MCP transport/Domain transition implementation, Persistence→Application workflow, Connector→Application workflow, Production→Evaluation.

## Single production authority

A capability migration is complete only when:

```text
new canonical owner is live
+ every production caller moved
+ old owner deleted
+ compatibility wrapper deleted
+ tests target canonical owner
```

`_compat` is forbidden on `main`.

## Documentation authority boundary

This source owns **where/how code is named and placed, repository import/export enforcement, and production-authority uniqueness**. It does not redefine behavioral semantics owned by 01–15, Domain State Transition Contract, Test Matrix, or executable SQL constraints.

02 continues to own UI·UX behavior. 03 continues to own system/layer dependency semantics. 06/15 continue to own versioned runtime Agent/Node/Prompt identifiers; 16 only maps those semantics to repository owner/path/file/symbol conventions unless the owning runtime contract is explicitly versioned. Workflow v7.22 / Prompt Contract v1.28 explicitly version the heavy-Agent atomic responsibility topology; therefore Repository Architecture v1.4 maps those semantic responsibilities to distinct repository operation files without creating a second production authority.

For repository naming/placement questions, 16 is the single concern authority. Other Project Sources may contain semantic names they own, but they must not establish an independent repository path/file/symbol grammar.

## Closed-world naming rule

If a production construct does not match a grammar in this Source or its subordinate normative pages, an Agent must not invent a new naming or placement pattern. It must map the construct to an existing taxonomy/grammar or add an explicit Exception Registry entry through a Repository Architecture version change. Undocumented discretion such as “either form is acceptable” is not allowed for production placement.

Detailed subordinate pages under this Source are normative detail but are not separate Project Source entries:

- [00. Authority · Read Order](16-repository-architecture/00-README.md)
- [01. Spec → Code Deterministic Mapping](16-repository-architecture/01-spec-to-code-mapping.md)
- [02. Directory Ownership](16-repository-architecture/02-directory-ownership.md)
- [03. Naming Grammar](16-repository-architecture/03-naming-grammar.md)
- [04. Artifact Taxonomy](16-repository-architecture/04-artifact-taxonomy.md)
- [05. Dependency · Import · Export Rules](16-repository-architecture/05-dependency-import-export-rules.md)
- [06. LangGraph · State Ownership](16-repository-architecture/06-langgraph-state-ownership.md)
- [07. Connector · API · Persistence Grammar](16-repository-architecture/07-connector-api-persistence-grammar.md)
- [08. Single Production Authority · Compat](16-repository-architecture/08-single-authority-compat.md)
- [09. Test · Fixture · Migration Grammar](16-repository-architecture/09-test-fixture-migration-grammar.md)
- [10. Error · Event · Configuration Naming](16-repository-architecture/10-error-event-configuration-naming.md)
- [11. Structural Refactor Playbook](16-repository-architecture/11-refactor-playbook.md)
- [12. Architecture Enforcement](16-repository-architecture/12-architecture-enforcement.md)
- [13. Exception Registry](16-repository-architecture/13-exception-registry.md)
