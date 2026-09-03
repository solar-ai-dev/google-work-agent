# 16. Repository Architecture Source

> **선행 읽기:** `00 → 03/04/State/05/06/07/09/10/15 semantic owners`  
> **이 문서의 역할:** repository placement/naming/import/single production authority. 선행 문서의 의미를 재정의하지 않는다.


**Status:** CANONICAL_FOR_REFACTOR

**Version:** 1.17

**Effective:** 2026-09-03

**Scope owner:** repository placement, module responsibility, naming grammar, repository import/export dependency realization and enforcement, repository semantic-owner/package mapping, single production authority, refactor procedure, architecture enforcement. Behavioral semantic authority itself remains with the applicable concern-owning sources in 01–15, the Domain State Transition Contract, and 04 Domain·DB required DB invariant contract. The State Transition Test Matrix is normative verification authority for those lifecycle contracts and does not independently define behavior.

## Mandatory invariants

```
DIRECTORY TELLS OWNERSHIP
FILENAME TELLS RESPONSIBILITY
IMPORT TELLS DEPENDENCY DIRECTION
ONE CAPABILITY HAS ONE PRODUCTION AUTHORITY
```

## Canonical repository boundary

Repository/architecture 문서가 **반드시 고정해야 하는 것**은 Agent가 구현할 때 서로 다른 구조를 만들 수 있는 결정이다.

- semantic owner / layer / dependency direction
- production path / file / symbol grammar
- one-capability-one-authority
- Port ↔ Adapter boundary와 concrete binding 위치
- owner-local contract type과 closed vocabulary의 authority
- lifecycle command가 필요한 state/side-effect boundary
- external I/O와 persistence transaction 분리

반대로 다음은 위 구조를 바꾸지 않는 한 **implementation choice**다.

- timeout·page/batch/file-size 같은 numeric tuning value
- 내부 자료구조·helper algorithm·serialization detail
- 운영 환경별 configurable limit
- 사용자 문구·presentation-only formatting

Implementation choice는 여러 canonical 문서가 서로 다른 값을 중복 소유하지 않는다. 보안/정책상 최소·최대 의미가 필요하면 해당 concern owner는 **bounded/fail-closed 요구**만 소유하고, exact numeric 값은 configuration/implementation owner가 정한다. 구현자는 이 자유를 새 owner/package/Port/type을 발명하는 근거로 사용할 수 없다.

## Canonical convention decisions

- Domain organization follows **canonical semantic owner**, not DB aggregate-root grouping.
- Domain lifecycle transitions and guards use **operation-per-file**; broad `commands.py` / `transitions.py` buckets are not final production structure.
- Application command/query use cases use **`<Verb><Object>Handler` classes** with colocated Command/Query + Result in one capability file.
- Contract types are **owner-local**; there is no global catch-all `contracts/` package.
- `_compat` may exist only transiently on a structural-refactor integration branch and must be **zero on `main`**.
- `06 Workflow` / `15 Prompt·Failure`의 current atomic LLM responsibility는 repository에서도 operation-per-file로 표현한다. `work_analysis`, `planning`, `review`의 서로 다른 semantic LLM responsibility를 하나의 `analyze.py`, `planning.py`, `review.py` 같은 broad production module로 다시 합치지 않는다.

## Deterministic spec-to-code rule

```
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

## Canonical repository semantic-owner vocabulary

The following owner names are repository mapping vocabulary for semantics owned by the concern sources; this section does not create independent behavioral authority.

Domain/lifecycle owners:

```
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

Observability persistence owners:

```
trace_event
audit_event
```

Agent owners:

```
request_understanding
tool_routing
retrieval
work_analysis
planning
review
```

Application boundary owners required by the current Local API / Security / Infrastructure contracts (this is a scoped boundary subset, not a second unqualified Application closed set; the exact current union is owned by subordinate `01 Spec → Code Deterministic Mapping`):

```
runtime_status
runtime_mode
connection
llm_credential
setting
backup
diagnostic_bundle
shutdown
attachment
resource
sse_event
trace_event
component_circuit
```

These names are repository owner/package mappings for concern-owned semantics in 07/08/09/10. They do not create new behavioral authority. Structural packages such as `application/tool_registry/`, `application/prompt_runtime/`, and `application/maintenance/` are intentionally excluded from the Application semantic-owner set and are closed by their dedicated structural manifests. Existing Domain owner `run` continues to own Run snapshot/resume Application capabilities.

Do not replace these with synonyms such as `job`, `manager`, `processor`, or generic `runtime` terminology.

## Operation verb taxonomy and closed-manifest rule
The verb families below are **naming taxonomy, not an exhaustive list of every current operation prefix**. The sole repository-side exact closed set of current **Domain/Application/Agent semantic operations** is the Canonical Required-Operation Manifest in subordinate `01 Spec → Code Deterministic Mapping`; 06/15 remain semantic/runtime responsibility owners and are consumed by that manifest. Adapter/runtime structural responsibilities are closed by this Source의 normative subordinate placement grammars—특히 `07 Connector · API · Persistence Grammar`의 Connector Runtime/MCP Server grammar—이며 verb taxonomy 자체로 새 operation을 도출하지 않는다. A precise verb outside the taxonomy is valid only when that exact operation/role is present in one of these 16-owned closed manifests. Future Agents may not invent an unlisted operation/verb; a new operation requires concern-owner contract + 16 manifest mapping update.

External/resource operations:

```
get
list
search
create
update
delete
send
```

Domain lifecycle verbs preserve the state-transition contract:

```
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

System/Application boundary lifecycle verbs:

```
restore
```

Deterministic transform verbs:

```
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

```
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

```
application/use_cases/<owner>/<verb>_<object>.py
<Verb><Object>Command | Query
<Verb><Object>Result
<Verb><Object>Handler
```

Domain transition:

```
domain/<owner>/transitions/<verb>_<object>.py
```

Domain guard:

```
domain/<owner>/guards/<verb>_<object>.py
```

Agent semantic operation:

```
application/agents/<role>/<verb>_<object>.py
→ <verb>_<object>()
```

Each versioned atomic responsibility owned by 06/15 maps to exactly one owner-local operation file unless 06/15 explicitly defines it as deterministic composition rather than an LLM responsibility. Broad role modules such as `analyze.py`, `planning.py`, or `review.py` are not valid production owners for multiple independent responsibilities.

Owner-local contract type:

```
application/agents/<role>/contracts/<artifact_name>.py
→ <ArtifactName>[Vn]
```

There is no global production `contracts/` package. Main/subgraph state types remain in the architecture-role `state.py` files owned by LangGraph.

LangGraph adapter:

```
adapters/langgraph/main/graph.py
adapters/langgraph/main/state.py
adapters/langgraph/main/routing/route_after_<stage>.py

adapters/langgraph/subgraphs/<role>/graph.py
adapters/langgraph/subgraphs/<role>/state.py
adapters/langgraph/subgraphs/<role>/routing/route_after_<stage>.py
adapters/langgraph/subgraphs/<role>/nodes/<verb>_<object>_node.py
```

Routing is operation-per-file. A catch-all production `routing.py` is not a final structure. Router symbol grammar is `route_after_<stage>()`.

LangGraph input projection:

```
adapters/langgraph/main/projections/<scope>_projection.py
adapters/langgraph/subgraphs/<role>/projections/<scope>_projection.py
→ project_<scope>_input()
```

A projection file owns one allowlisted input projection.

Persistence:

```
ports/persistence/<owner>_repository.py
adapters/persistence/sqlite/repositories/<owner>_repository.py
```

Transaction boundary:

```
ports/persistence/unit_of_work.py            → UnitOfWork
adapters/persistence/sqlite/unit_of_work.py → SqliteUnitOfWork
```

`UnitOfWork` owns transaction begin/commit/rollback only. It does not own Domain guards, external calls, or event semantics.

Non-persistence outbound Port:

```
ports/<boundary>/<capability>_port.py
→ <Capability>Port
```

Current canonical boundary package vocabulary is closed to `connector`, `llm`, `keyring`, and `system`. A new boundary package requires an explicit Repository Architecture contract update and Source Guide synchronization before implementation; version numbers are traceability metadata, not an independent Gate. Persistence remains the separate `ports/persistence/<owner>_repository.py` grammar and must not be renamed to a generic Port form.

Connector operation:

```
adapters/connectors/<provider>/<product>/<resource>/<verb>_<resource>.py
```

API transport and launcher special seams:

```
api/routes/<plural_resource>.py
api/schemas/<plural_resource>/<verb>_<object>.py
api/dependencies/<concern>.py
api/security/bootstrap_session.py
launcher/bootstrap_secret.py
launcher/readiness.py
```

`api/security/bootstrap_session.py` is the single bootstrap-to-Local-Session establishment authority. `api/dependencies/local_session.py` only validates established sessions. `launcher/bootstrap_secret.py` and `launcher/readiness.py` are special seam files, **not the exhaustive Launcher manifest**. The exact Launcher operation set plus Windows Installer/Release source roots, files, symbols, and tests are owned by normative subordinate `02 Directory Ownership §Launcher · Installer · Release exact manifest`; no alternate `packaging/`, `build/`, `scripts/release/`, or ad-hoc installer root is canonical.

## Workflow repository naming normalization

Repository semantic owner/package is `Tool Routing` / `tool_routing`; existing contract artifact `ToolRoutePlanV2` remains unchanged.

Versioned runtime Node identifiers and PromptRef IDs remain owned by 06 Workflow / 15 Prompt·Failure and are **not silently renamed by this document**. Repository Architecture maps the same semantic capabilities to canonical repository owner/path/file/symbol labels, but identifier namespaces are distinct. For example `06` may use a runtime Node ID such as `analysis.extract_facts` while repository ownership is `work_analysis.extract_work_facts`; likewise runtime `request.*` identities map to repository owner `request_understanding.*`. This mapping must be explicit in graph/node wiring and tests; string equality across namespaces is not required. `planning.compose_dependencies` does not exist as a Product Prompt/LLM authority; dependency construction is deterministic `planning.build_dependencies`.

The exact current Agent repository operation closed set is defined **only** by subordinate `01 Spec → Code Deterministic Mapping / Canonical Required-Operation Manifest`. This parent Source retains owner vocabulary, namespace-separation rules, and thin-node constraints, but does not duplicate the 43-row operation list. Deterministic supporting operations such as `tool_routing.resolve_policy_preconditions` and `planning.resolve_default_container` are therefore governed by the same single manifest and do not increase LangGraph Node count unless 06 explicitly maps a runtime Node.

A LangGraph node is a thin adapter only: typed projection → application call → typed owner-field patch → optional WorkflowSignal.

## Naming restrictions

Contract symbol versioning is allowed (`RequestIntentV2`, `WorkAnalysisResultV2`). Production implementation module generation/version naming is prohibited.

Final production filenames must not use:

```
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

Explicit architecture-role exceptions: `state.py`, `graph.py`, `model.py`, `composition.py`. `routing.py` is not an exception; routing uses `routing/route_after_<stage>.py`.

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
- Domain transitions use `domain/<owner>/transitions/<verb>_<object>.py → transition_<verb>_<object>()`.
- Domain guards use `domain/<owner>/guards/<verb>_<object>.py → guard_<verb>_<object>()`.
- Validators, resolvers, builders, assemblers, mappers, and normalizers are named by semantic verb, not generic role buckets: `validate_<object>.py`, `resolve_<object>.py`, `build_<object>.py`, `assemble_<object>.py`, `map_<object>.py`, `normalize_<object>.py`, with the same snake_case function name.
- Registries are owner-local noun authorities: `<subject>_registry.py → <Subject>Registry`.
- Errors are owner-local and use `<subject>_<condition>_error.py → <Subject><Condition>Error`; broad `errors.py` buckets are prohibited when they contain unrelated error authorities.
- Configuration modules are owner-local and semantic. Generic `config.py` is not a production naming escape hatch.

## Test and migration grammar

Unit tests mirror production ownership:

```
src/.../<verb>_<object>.py
→ tests/unit/.../test_<verb>_<object>.py
```

Test functions:

```
test_<operation>_<object>__<condition>__<expected>
```

Existing `TST-<AREA>-<NNN>` traceability IDs remain unchanged.

Migrations:

```
NNNN_<semantic_change>.sql
```

Applied migrations are immutable and must never be renamed or rewritten for structural refactoring.

## Repository dependency realization

System/layer dependency semantics are owned by 03 Architecture. This section defines their repository import/export realization and enforcement and may not relax 03.

```
API / LangGraph → Application → Domain + Ports ← Outbound Adapters
Launcher → launcher-local orchestration + system boundaries only; no Application/Domain business ownership
```

Forbidden includes Domain→Application/Adapter/API, Application→concrete Adapter/provider SDK, LangGraph→SQLite implementation/provider SDK/concrete MCP transport/Domain transition implementation, Persistence→Application workflow, Connector→Application workflow, Production→Evaluation; product runtime→`installer/**` or `release/**`.

## Single production authority

A capability migration is complete only when:

```
new canonical owner is live
+ every production caller moved
+ old owner deleted
+ compatibility wrapper deleted
+ tests target canonical owner
```

`_compat` is forbidden on `main`.

## Local Runtime provisioning and model-profile placement

```text
application/use_cases/runtime_status/provision_local_runtime.py
→ ProvisionLocalRuntimeCommandV1 / ProvisionLocalRuntimeResultV1 / ProvisionLocalRuntimeHandler

ports/system/local_runtime_provisioning_port.py
→ LocalRuntimeProvisioningPort

adapters/system/ollama_local_runtime_provisioning.py
→ OllamaLocalRuntimeProvisioningAdapter

installer/windows/local_runtime_provisioning_definition.py
→ WindowsLocalRuntimeProvisioningDefinition

src/google_work_agent/ports/llm/approved_model_manifest.py
→ ApprovedModelEntryV2 / ModelManifestV2

src/google_work_agent/ports/llm/local_model_product_decision.py
→ LocalModelTierBindingV1 / LocalModelProfileV1 / LocalModelProductDecisionV2

release/generate_model_manifest.py
→ generate_model_manifest()

release/generate_local_model_product_decision.py
→ generate_local_model_product_decision()
```

`runtime_status` remains the existing Application owner for local runtime readiness/provisioning. Do not create a new `model`, `ollama`, `provisioning`, `installer` Application owner. Existing `runtime_status.get_runtime_status` projects `RuntimeDetailResponseV2`; no second general runtime-status authority is created.

The two signed artifacts have separate authority:

- `ModelManifestV2`: approved Ollama installer artifact and approved model allowlist.
- `LocalModelProductDecisionV2`: exact active `WORKER | REASONING` profile and evaluated platform/hardware thresholds, bound to canonical `ModelManifestV2` bytes by hash.

`StructuredInferenceRuntimeRouter` is the only production owner of `InferenceTierV1 → concrete runtime/model` resolution. It reads `LocalModelProductDecisionV2.active_profile` and verifies every binding against `ModelManifestV2`. Agent operations, Prompt sources, API routes, Settings, provider leaves and model-name parsing may not own a competing mapping.

`OllamaLocalRuntimeProvisioningAdapter` alone owns download/staging/signature/hash/digest verification, existing-runtime detection, controlled installer invocation, readiness and model preparation. It receives both verified V2 artifacts through `LocalRuntimeProvisioningPort`. Application/API/Frontend never run shell/download/install semantics directly.

The Windows Installer source declares provisioning capability but does not embed Ollama executable or model weights. Product first-run invokes the Application operation after installation. `API_ONLY` has no provisioning side effect; `LOCAL_CAPABLE` requires both verified V2 artifacts.

V1→V2 is a contract migration, not an in-place field extension. Final activation requires V2 parser/generator/caller closure and V1 production authority zero; old V1 artifacts may remain only as explicit migration/test evidence.

## Documentation authority boundary

This source owns **where/how code is named and placed, repository import/export enforcement, and production-authority uniqueness**. It does not redefine behavioral semantics owned by the applicable sources in 01–15, the Domain State Transition Contract, or 04 Domain·DB required DB invariant contract. The State Transition Test Matrix verifies those lifecycle contracts; it is not an independent behavioral owner.

02 continues to own UI·UX behavior. 03 continues to own system/layer dependency semantics. 06/15 continue to own versioned runtime Agent/Node/Prompt identifiers; 16 only maps those semantics to repository owner/path/file/symbol conventions. The current Workflow / Prompt·Failure contracts own the heavy-Agent atomic responsibility topology, so Repository Architecture maps those responsibilities to distinct repository operation files without creating a second behavioral authority.

## Closed-world naming rule

If a production construct does not match a grammar in this Source or its subordinate normative pages, an Agent must not invent a new naming or placement pattern. It must map the construct to an existing taxonomy/grammar or add an explicit Exception Registry entry through a Repository Architecture contract update. Undocumented discretion such as “either form is acceptable” is not allowed for production placement.

Detailed subordinate pages under this Source are normative detail but are not separate Project Source entries.

[00. Authority · Read Order](00-authority-read-order.md)

[01. Spec → Code Deterministic Mapping](01-spec-to-code-deterministic-mapping.md)

[02. Directory Ownership](02-directory-ownership.md)

[03. Naming Grammar](03-naming-grammar.md)

[04. Artifact Taxonomy](04-artifact-taxonomy.md)

[05. Dependency · Import · Export Rules](05-dependency-import-export-rules.md)

[06. LangGraph · State Ownership](06-langgraph-state-ownership.md)

[07. Connector · API · Persistence Grammar](07-connector-api-persistence-grammar.md)

[08. Single Production Authority · Compat](08-single-production-authority-compat.md)

[09. Test · Fixture · Migration Grammar](09-test-fixture-migration-grammar.md)

[10. Error · Event · Configuration Naming](10-error-event-configuration-naming.md)

[11. Structural Refactor Playbook](11-structural-refactor-playbook.md)

[12. Architecture Enforcement](12-architecture-enforcement.md)

[13. Exception Registry](13-exception-registry.md)

## Structural closure contract

Repository Architecture closure is defined by **single live authority plus negative proof of retired authority**.

A structural migration is complete only when the canonical mapping is satisfied and validation proves:

```
canonical authority live
+ required-operation manifest satisfied
+ intended production callers cut over
+ old production callers/imports/concrete exports zero
+ duplicate authority zero
+ forbidden compatibility zero
+ canonical test ownership
+ behavior regression pass
```

Application final-structure consequences:

- `application/` root is not a semantic authority bucket;
- `application/workflows/**` is not a final production semantic owner;
- concrete `read_*` / `write_*` compatibility facades are temporary migration mechanisms only and must be zero after their capability cut-over;
- `__init__.py` remains empty by default and may deliberately re-export only stable public contracts/Ports, never concrete production authority;
- Application cannot own FastAPI transport responsibility, LangGraph routing responsibility, concrete Connector/MCP Adapter implementation, Provider SDK/API client, or concrete SQLite implementation;
- API, LangGraph, composition, and all other intended production consumers must call the canonical Application authority.

The required-operation manifest is maintained by the deterministic Spec → Code mapping and is validated as a closed set. Current implementation presence/absence never defines the required set.

This section clarifies enforcement of the single-authority, dependency, naming, and test-ownership rules in the current Repository Architecture contract; it does not redefine behavioral semantics owned by 01–15, the State Transition Contract/Test Matrix, or 04 Domain·DB invariants.

## Implementation determinism contract

### Canonical naming ledger

아래 이름은 구현·테스트·문서에서 같은 개념의 canonical vocabulary다. repository operation ID와 runtime Node ID는 서로 다른 namespace일 수 있지만 subordinate 01/06의 explicit mapping 없이 제3의 별칭을 만들지 않는다.

| Concept | Canonical name | Do not use as synonym |
| --- | --- | --- |
| user work execution unit | `Run` | Thread, Session |
| workflow checkpoint identity | `langgraph_thread_id` | workflow `thread_id` |
| external provider conversation resource | Gmail `thread_id` | `langgraph_thread_id` |
| planned side-effect unit | `Action` | Operation, Execution |
| immutable user authorization fact | `Approval` | Confirmation, Claim |
| execution-claim lifecycle command | `ClaimExecution` | Approval, Confirmation |
| one-time dispatch authority artifact | `ClaimContextV2` + `claim_token` | Approval token, claim approval |
| external mutation call | `Connector Write` | Google Write as generic core term |
| post-write truth check | `Verification` | Validation, Review |
| indeterminate external outcome | `UNKNOWN_RESULT` | FAILED |
| recovery lifecycle | `Recovery` / `RECOVERY_REQUIRED` | Retry loop |
| product policy decision | `deterministic Policy` | LLM judgement, Domain guard |
| wire validation | `Schema validation` | Semantic validation |
| domain lifecycle precondition | `Domain guard` | Policy validation, Review |
| execution argument integrity | `approval_arguments_hash` + `execution_arguments_hash` | prompt equality |
| connector abstraction | `ConnectorReadPort` / `ConnectorWritePort` | MCP Read/Write Port |
| persistence abstraction | owner-specific Domain Repository | Checkpointer |
| workflow persistence | `CheckpointPort` | Domain Repository |
| diagnostic correlation | `Trace` | Audit |
| security/domain record | `Audit` | Trace |

### One file = one responsibility

Production operation file은 다음 문장을 만족해야 한다: **“이 파일은 `<canonical operation>`만 담당한다.”**

분리 강제 기준:

- policy decision과 execution은 다른 파일
- validation과 mutation은 다른 파일; 단 Domain Command Handler 내부의 command guard + atomic mutation은 하나의 lifecycle command 책임으로 본다
- external connector call과 Domain persistence는 다른 파일/transaction boundary
- orchestration과 Domain rule은 다른 파일
- execution과 verification은 다른 파일
- recovery policy와 normal execution은 다른 canonical owner
- LLM semantic operation과 deterministic assembler/validator는 다른 operation file

`application/agents/<role>/<operation>.py`, `application/use_cases/<owner>/<operation>.py`, `adapters/langgraph/**/nodes/<operation>_node.py`, `adapters/connectors/**/<operation>.py`는 각각 한 operation만 production authority로 가진다. `response_synthesis_node.py`는 terminal response input 생성만, `terminal_commit_node.py`는 closed terminal lifecycle-handler dispatch만, `finalize_node.py`는 terminal post-commit projection orchestration만 담당한다. Message persistence·Trace persistence·SSE buffering의 실제 책임은 각각 owning operation/Port로 분리한다. 여러 독립 operation을 한 class/module facade에 모으는 generic `service.py`, `manager.py`, `processor.py`는 금지한다.

### Deterministic validation production owners

아래 경계는 서로 대체하지 않으며 각각 한 파일만 production authority를 가진다.

| Boundary | Canonical operation | Canonical file/symbol | Responsibility |
| --- | --- | --- | --- |
| Tool argument schema | `action.validate_action_arguments` | `application/use_cases/action/validate_action_arguments.py` → `ValidateActionArgumentsHandler` | current registered Tool Input Schema에 대한 shape/type/closed-field validation만 수행. Policy/Domain mutation/LLM 판단 0 |
| Product policy | `action.evaluate_action_policy` | `application/use_cases/action/evaluate_action_policy.py` → `EvaluateActionPolicyHandler` | 01-B의 deterministic allow/deny/confirmation requirement만 계산. mutation/external I/O 0 |
| Domain guard | lifecycle command별 `guard_<verb>_<object>()` | `domain/<owner>/guards/<verb>_<object>.py` | current aggregate/source state/version/freshness precondition만 판정. Policy를 재정의하지 않음 |
| Agent semantic validation | owner별 `validate_<artifact>()` | `application/agents/<role>/validate_<artifact>.py` | LLM structured artifact semantic consistency만 검증. Policy/Approval/Domain transition 0 |
| Claim context integrity | `claim.build_claim_context` | `application/use_cases/claim/build_claim_context.py` → `BuildClaimContextHandler` | committed Claim/Attempt + approved snapshot + final server-generated dispatch args를 canonicalize하고 `execution_arguments_hash`/signed `ClaimContextV2`를 생성. external Write/DB mutation 0 |

Approval path의 순서는 `validate_action_arguments → evaluate_action_policy → Review freshness 확인 → Domain ApproveAction guard/mutation`이다. Dispatch path는 committed `ClaimExecution` 뒤 `build_claim_context → BeginExecutionAttempt commit → dispatch_connector_write`이며, MCP는 실제 수신 args를 재해시해 claim과 불일치하면 외부 호출 전에 거절한다.

### Workflow binding shared contract ownership

`GraphProfileIdV1`과 `WorkflowBindingV1`의 repository-level schema authority는 `ports/system/contracts/workflow_binding.py` 하나다. 이 파일은 **same-Run workflow binding의 typed data contract만** 담당하며 graph composition, checkpoint I/O, Domain lifecycle, Config 선택을 수행하지 않는다.

- `GraphProfileIdV1 = SINGLE_BASELINE | THREE_STAGE | SIX_ROLE_BASELINE`
- `WorkflowBindingV1 = workflow_key + run_id + langgraph_thread_id + graph_profile + graph_version + requested_mode + created_at_ms`
- `application`과 `adapters/langgraph`는 이 Port contract를 import할 수 있다.
- `CheckpointPort`는 이 contract를 저장/조회할 뿐 profile을 선택하거나 변환하지 않는다.
- `adapters/langgraph/profiles/profile_registry.py`는 binding의 `graph_profile`을 closed lookup해 builder를 선택한다.
- `06`은 profile semantic closed set과 State projection/ownership을 소유하고, `07`은 그 동일 이름의 internal Interface shape를 소유한다. `16`은 두 concern을 구현하는 **하나의 shared contract file placement**만 결정하며 별도 vocabulary를 만들지 않는다.

### Graph Profile composition ownership

세 profile은 같은 semantic operations/Domain/Ports를 재사용하고 **composition만** 달리한다.

| Profile | Canonical file | 단일 책임 |
| --- | --- | --- |
| `SINGLE_BASELINE` | `adapters/langgraph/profiles/single_baseline.py` | six semantic responsibility를 하나의 unified Agent Subgraph composition으로 wire |
| `THREE_STAGE` | `adapters/langgraph/profiles/three_stage.py` | three-stage Subgraph grouping/edges만 wire |
| `SIX_ROLE_BASELINE` | `adapters/langgraph/profiles/six_role_baseline.py` | six owner Subgraph composition/edges만 wire |

- Profile registry: `adapters/langgraph/profiles/profile_registry.py`는 `GraphProfileIdV1 → compiled profile builder` closed lookup만 담당한다.

Physical Subgraph identity is profile-specific and never inferred from the six semantic owner IDs. The exact mapping is the 06 `SemanticAgentOwnerIdV1 × GraphProfileIdV1 → CompiledAgentSubgraphIdV1` table; profile builders and `NodeRegistry` must materialize that table unchanged.

Profile file은 business rule/Prompt/Policy/Domain mutation을 정의하지 않는다. `WorkflowBindingV1`의 stored profile/version과 다른 compiled graph로 resume하는 adapter fallback은 금지한다.

### Main Graph control-stage exact mapping

Main Graph control stages are deterministic LangGraph adapters, not a seventh semantic Agent. They own orchestration only and each file has one stage responsibility.

| Main stage | Canonical adapter file | Calls / single responsibility |
| --- | --- | --- |
| `INITIALIZE` | `adapters/langgraph/main/nodes/initialize_node.py` | invoke `run.start_analysis` and project committed Run into Main State only |
| `DOMAIN_VALIDATION` | `adapters/langgraph/main/nodes/domain_validation_node.py` | invoke schema/policy/Domain guard chain and route result only; no DB/Connector direct call |
| `PREFLIGHT` | `adapters/langgraph/main/nodes/preflight_node.py` | source freshness + `claim.claim_execution` readiness orchestration only |
| `DOMAIN_RECONCILE` | `adapters/langgraph/main/nodes/domain_reconcile_node.py` | consume `current_status + next_allowed_commands` and choose registered deterministic edge only |
| `ACTION_EXECUTION` | `adapters/langgraph/main/nodes/action_execution_node.py` | call `claim.build_claim_context` → `execution_attempt.begin_execution_attempt` → `execution_attempt.dispatch_connector_write` → `execution_attempt.classify_dispatch_result` → closed dispatch to `store_success | mark_failed | mark_unknown_result`; each lifecycle commit precedes external I/O and classification/persistence are separate files |
| `VERIFICATION` | `adapters/langgraph/main/nodes/verification_node.py` | call `verification.verify_effect` then `verification.store_verification`; no corrective write |
| `RECOVERY` | `adapters/langgraph/main/nodes/recovery_node.py` | consume/dispatch registered Recovery operations; no blind resend |
| `RETRIEVAL_ENTRY` | `adapters/langgraph/main/nodes/retrieval_entry_node.py` | external-control/cache-restart re-entry; validate frozen routes, apply BeginRetrieval when required, then enter Retrieval |
| `PLANNING_ENTRY` | `adapters/langgraph/main/nodes/planning_entry_node.py` | corrective-plan/external re-entry into existing deterministic Planning entry operation |
| `REVIEW_ENTRY` | `adapters/langgraph/main/nodes/review_entry_node.py` | Modify/PrepareRetry/RefreshExpiredAction current-plan full Review re-entry |
| `CANCEL_RESOLUTION` | `adapters/langgraph/main/nodes/cancel_resolution_node.py` | call `run.continue_cancel_resolution`; existing cancel/read/verification/recovery commands only |
| `RESPONSE_SYNTHESIS` | `adapters/langgraph/main/nodes/response_synthesis_node.py` | create `TerminalAssistantMessageInputV1` + deterministic `TerminalCommitIntentV1`; cannot decide lifecycle/policy/approval/execution/verification |
| `TERMINAL_COMMIT` | `adapters/langgraph/main/nodes/terminal_commit_node.py` | closed dispatch to one existing terminal lifecycle handler; atomic terminal Message/Audit UoW; no new lifecycle semantics |
| `FINALIZE` | `adapters/langgraph/main/nodes/finalize_node.py` | after terminal UoW commit, call Trace emit + SSE projection and END only; no Domain mutation/Message insert |

`WAITING_CONFIRMATION`, `WAITING_APPROVAL`, failed-retry wait, Reauth/Recovery suspend are **suspend states/edges**, not extra semantic operation files. Their resume commands remain the mapped Application use cases.

### Evaluation implementation ownership

13이 정의한 Dataset/Gold/Grader는 Product Runtime authority와 분리한다. Evaluation은 두 번째 Product architecture를 만들지 않으며 public Product boundary의 소비자다.

| Responsibility | Canonical path | One responsibility |
| --- | --- | --- |
| public Product client | `evaluation/client/http.py` | loopback HTTP request/session/response parsing only |
| strict dataset loading | `evaluation/dataset.py` | JSONL load, duplicate rejection, case selection, artifact hash only |
| deterministic grader | `evaluation/grader.py` | public observation을 Dataset Gold와 비교 only; Product rule 재구현 0 |
| one-case runner | `evaluation/runner.py` | load → public API → normalize → grade → one JSON result only |
| offline Prompt candidate | `evaluation/prompt_candidate.py` | DRAFT candidate/hash/current-contract materialization only; Product Runtime authority 0 |
| experiment plan | `evaluation/experiment_plan.py` | fixed-variable/provenance/binding validation only |
| batch runner | `evaluation/run_experiment.py` | validated Case × repetition → existing `runner.run_case()` → raw trial/summary only |
| result comparison | `evaluation/compare_experiment_results.py` | fixed-dimension validation, case/aggregate delta, hard-gate regression only; promotion decision 0 |

Current repository artifact placement is closed under the same single `evaluation/` root:

```text
evaluation/README.md
evaluation/datasets/retrieval/**
evaluation/datasets/agent/**
evaluation/datasets/e2e/**
evaluation/configs/**
evaluation/prompt_candidates/**
evaluation/scoring-contract-v1.1.json
evaluation/client/**
evaluation/dataset.py
evaluation/grader.py
evaluation/runner.py
evaluation/prompt_candidate.py
evaluation/experiment_plan.py
evaluation/run_experiment.py
evaluation/compare_experiment_results.py
evaluation/results/**                    # local/gitignored unless deliberately curated
```

No `evaluation/contracts|targets|fixtures|projections|reporting|compat` framework exists beyond the exact operations and artifacts listed above. Dataset fixtures belong beneath their dataset category, not in a second executable fixture authority. A top-level `experiments/` directory, Product file:symbol target registry, direct Node/Subgraph invocation, fake Product adapter, and Evaluation→Product Python import are prohibited. Historical artifacts remain in Git history rather than a live compatibility tree.

### Production composition / registry / execution structural authorities

The following structural authorities are repository-owned placement contracts and are not new product semantic owners:

```text
api/composition.py
→ build_production_runtime()                   # only concrete wiring authority

adapters/connectors/runtime/connector_runtime_registry.py
→ ConnectorRuntimeRegistry                    # connector_id → active runtime handle

application/tool_registry/signed_tool_registry.py
→ SignedToolRegistry                          # Tool semantic metadata

application/prompt_runtime/prompt_registry.py
→ PromptRegistry                              # PromptRef/manifest/source/input-contract lookup

application/prompt_runtime/contracts/prompt_runtime_input_contract.py
→ PromptRuntimeInputContractV1 / PromptRuntimeInputContractEntryV1

application/prompt_runtime/load_prompt_input_contract.py
→ load_prompt_input_contract()                # exact PromptRuntimeInputContractV1 loader/validator

adapters/langgraph/registry/node_registry.py
→ NodeRegistry                                # graph_version + profile + semantic owner + node → compiled subgraph lookup

adapters/langgraph/registry/resume_target_registry.py
→ ResumeTargetRegistry                        # AgentNode/MainControl RegisteredResumeTargetRefV2 issue/validation

adapters/langgraph/profiles/profile_registry.py
→ graph profile builder lookup

adapters/llm/runtime/structured_inference_router.py
→ StructuredInferenceRuntimeRouter            # only StructuredInferencePort production binding

adapters/llm/runtime/llm_credential_router.py
→ LlmCredentialRouter                         # only LlmCredentialPort production binding

adapters/llm/runtime/llm_runtime_status_router.py
→ LlmRuntimeStatusRouter                      # only LlmRuntimeStatusPort production binding

adapters/llm/<provider>/structured_inference.py
→ <Provider>StructuredInferenceAdapter        # Router-private external API inference leaf

adapters/llm/<provider>/credential.py
→ <Provider>LlmCredentialAdapter              # Router-private external API credential leaf

adapters/llm/<provider>/runtime_status.py
→ <Provider>LlmRuntimeStatusAdapter           # Router-private external API status leaf

adapters/llm/ollama/structured_inference.py
→ OllamaStructuredInferenceAdapter            # exact P0 local inference leaf

adapters/llm/ollama/runtime_status.py
→ OllamaLlmRuntimeStatusAdapter               # exact P0 local status leaf; no Ollama credential leaf

# <provider> is a release-approved external API provider package parameter.
# Concrete API provider/model identity is release/configuration-owned by 10/13, not a closed Repository Architecture identifier.

adapters/langgraph/runtime/background_run_executor.py
→ BackgroundRunExecutorAdapter                # WorkflowExecutionPort concrete adapter

application/use_cases/run/redrive_workflow_handoffs.py
→ RedriveWorkflowHandoffsHandler              # single Application handoff-reconciliation owner

adapters/system/workflow_handoff_reconciliation_loop.py
→ WorkflowHandoffReconciliationLoop           # process-lifecycle driving adapter only

ports/persistence/workflow_handoff_repository.py
→ WorkflowHandoffRepository                   # durable outbox abstraction

adapters/persistence/sqlite/repositories/workflow_handoff_repository.py
→ SqliteWorkflowHandoffRepository             # workflow_handoffs realization

ports/system/contracts/workflow_handoff.py
→ WorkflowHandoffStageV1 / WorkflowHandoffV1 / WorkflowExecutionBindingV1 / WorkflowExecutionAdmissionV1 / WorkflowExecutionSubmissionV2 / WorkflowControlEnvelopeV1
# StageV1 is pre-persistence intent; WorkflowHandoffV1 is persisted-row projection with run_sequence/version/admission/applied checkpoint evidence; SubmissionV2 carries only the persisted effective admission across WEP
```

These registries are separate because their semantic scopes differ. A generic catch-all `registry.py`, service locator, runtime manager, or second composition root is not a canonical replacement.

Service reconciliation invocation is closed: `api/app.py → create_app()` completes SQLite/migration/checkpoint readiness, starts/validates MCP Connector runtimes and loads the configured LLM Adapter/Router, then invokes injected `ReconcileInflightExecutionsHandler` as a **startup-only state-changing batch Command**. It repeats the handler while `has_more=true` and durable progress is made; the handler itself owns `ExecutionAttemptRepository.list_reconciliation_candidates(limit)`. Only after this orphan reconciliation drain does the lifespan invoke injected `RedriveWorkflowHandoffsHandler` for the initial workflow drain. Each Redrive pass first applies the current Domain/state-specific authority gate. Only for a continuation that is otherwise resumable does it invoke `ReconcileRetrievalCacheRestartHandler` as the typed **pre-resume prerequisite** when the checkpoint declares required retrieval handles; a missing dependency is normalized to the durable restart handoff before semantic owner I/O. It then evaluates CONSUMED/BLOCKED/PENDING/SAFE continuation lanes. Startup completes the bounded orphan drain and bounded initial handoff drain, starts injected `WorkflowHandoffReconciliationLoop`, and only then publishes READY. The live loop drives `RedriveWorkflowHandoffsHandler` only; it never invokes `ReconcileInflightExecutionsHandler`. `api/composition.py` only constructs/binds the handler, loop, and dependencies; neither file owns handoff semantics. The live loop is a driving adapter that repeatedly invokes the same Application handler and never calls WEP/LangGraph directly. `WorkflowHandoffRepository` exposes the only ordering/transition surfaces: stage with server-owned `run_sequence`, dispatch-head/redrive/blocked queries, **pre-WEP `claim_execution_admission`**, authority-aware non-ACCEPTED `release_execution_admission`, NORMAL CONSUMED settlement, recovery-admission settlement, `supersede_unconsumed_for_run`, and SUPERSEDED settlement. NORMAL/recovery settlement is also the pre-owner authority fence: it atomically checks admission expected_run_version against current Run.version. A mismatch is `AUTHORITY_STALE_RETIRED`, not a durable dangling admission: NORMAL is atomically retired to SUPERSEDED, recovery keeps CONSUMED and clears admission. `release_execution_admission` performs the same authority-version check so a newer control cannot cause a stale admitted head to be resurrected as PENDING/BLOCKED. Exact same-admission WEP replay is idempotent ACCEPTED; ALREADY_RUNNING means a different admission slot conflict. No startup helper, executor, loop, or route may invent raw SQL ordering/reset APIs. WEP ACCEPTED is never followed by a required handoff status CAS.

### Dependency-safe implementation order

전체 구현은 아래 순서로 진행한다. Concern-local 문서의 “구현 순서”가 이 순서와 충돌하면 이 repository dependency order가 placement/build sequencing에 우선하고, behavioral semantics는 해당 Concern owner가 유지한다.

```text
1. canonical enums / IDs / Request·Response·State schemas
2. Domain aggregate models + Domain State Transition Contract guards/results
3. abstract Ports + Local API/MCP interface schemas
4. deterministic Policy / Schema / semantic validators
5. Domain Repository interfaces + required DB invariant mapping
6. migration implementation + startup discovery/order/checksum contract
7. structural manifests/contracts: Signed Tool manifest, Prompt manifest/source contracts, WorkflowBinding
8. concrete leaf Adapters (SQLite repositories/UoW/checkpointer, Connector/MCP, Keyring, LLM provider/Ollama, system)
9. Application use cases / agent semantic operations + Prompt Registry/assembler
10. LangGraph Node adapters + exact projections/routers
11. Graph composition + Graph Profile/Node/Resume Target registries + interrupt/resume wiring
12. LLM Runtime Router
13. WorkflowExecutionPort background executor
14. Service entry/composition root wiring (`api/app.py` + `api/composition.py`)
15. FastAPI Routes + SSE projection
16. Frontend feature modules + `/api/v1` transport/projection bindings
17. Trace / Audit emitters and projections
18. unit → contract → migration → integration → E2E → failure-injection tests
19. evaluation runner / release candidate comparison
```

어느 단계도 다음 단계의 concrete implementation을 import하지 않는다. Schema/Port/Domain contract가 정의되지 않은 상태에서 downstream Node/API를 먼저 구현해 placeholder type이나 임시 facade를 만들지 않는다.

### End-to-end implementation coverage mapping

| Flow stage | Semantic owner | Canonical implementation owner | Validation/persistence/side effect boundary |
| --- | --- | --- | --- |
| READ request understanding | 06 Request Understanding | `application/agents/request_understanding/*` | typed `RequestIntentV2`; no external I/O |
| READ tool routing | 06/07 Tool Routing | `application/agents/tool_routing/*` | PolicyPreconditionResolver deterministic; frozen `ToolRoutePlanV2` |
| READ connector execution | 05 Retrieval + 07 Interface | `application/agents/retrieval/execute_read.py` → `ConnectorReadPort` | external read outside SQLite write transaction |
| READ normalization/evidence | 05 Retrieval | retrieval normalize/RAG/select/sufficiency operations | Run-scoped cache/Evidence; no Action/Approval |
| READ response | 06 Planning + Run use case | `run.build_terminal_message` → `run.complete_answer_only_run` (current answer-only) | final ASSISTANT Message + Run/Receipt/required Audit same UoW; Trace/SSE post-commit |
| WRITE intent/route | 06 Tool Routing | tool-routing operations | OUT tool/resource/effect frozen before Planning |
| WRITE argument generation | 06 Planning | per-route objective + argument operations | LLM output은 candidate뿐이며 `action.validate_action_arguments`가 current Tool schema를 결정적으로 검증 |
| WRITE policy validation | 01-B | `action.evaluate_action_policy` | deterministic allow/deny/confirmation requirement; LLM/Domain mutation/external I/O 0 |
| WRITE domain validation | State Contract | owning lifecycle command의 `domain/<owner>/guards/<verb>_<object>.py` | source state/version/review/source freshness guard; policy 결과를 우회하지 않음 |
| Review freshness | 06 Review + 04 persistence | review operations → `plan.record_review_result` | only current PASS opens durable review gate |
| Approval | State Contract | `action.approve_action` | immutable Approval snapshot; no external side effect |
| Claim | State Contract | `claim.claim_execution` | Approval consume + Attempt CLAIMED + Action EXECUTING atomic commit |
| approved-vs-execution args | 07/09 | `claim.build_claim_context` → ConnectorWrite boundary | committed Claim 뒤 final dispatch args hash를 생성하고 MCP가 실제 args를 재해시해 compare; mismatch면 dispatch 0 |
| MCP execution | State Contract + 07 Interface | `execution_attempt.begin_execution_attempt` commit → `application/use_cases/execution_attempt/dispatch_connector_write.py` → `ConnectorWritePort` → connector adapter/MCP client | Attempt CLAIMED→EXECUTING/Audit commit first; external mutation outside SQLite transaction; no persistence in dispatch file |
| execution result classification | 07 Interface | `application/use_cases/execution_attempt/classify_dispatch_result.py` | pure deterministic `STORE_SUCCESS | MARK_FAILED | MARK_UNKNOWN_RESULT`; I/O/mutation 0 |
| execution result persistence | State Contract/04 | `store_success.py | mark_failed.py | mark_unknown_result.py` | classifier decision에 맞는 coupled Action/Attempt mutation을 short UoW로 persist |
| Verification reread | 07 Verification | `application/use_cases/verification/verify_effect.py` → `ConnectorReadPort` | deterministic strategy; external read only |
| Verification persistence | State Contract/04 | `verification.store_verification` | immutable Verification; MISMATCH fact commit 후 별도 `recovery.require_recovery(VERIFICATION_MISMATCH)`만 Recovery entry 수행 |
| UNKNOWN_RESULT | State Contract/07 | `application/use_cases/recovery/lookup_unknown_result.py` → `ConnectorReadPort` → `execution_attempt.recover_existing_result | resolve_as_failed` | no new Attempt/blind resend; recovered result enters Verification only through `BeginVerification` or changed-input `ResolveRecovery(RECHECK)`; unresolved enters/remains Recovery |
| Recovery | State Contract/06 | `recovery.require_recovery/resolve_recovery` | explicit resolution only; bounded RECHECK |
| Terminal output synthesis | 06 | `application/use_cases/run/build_terminal_message.py` → `BuildTerminalMessageQueryV1 / TerminalAssistantMessageInputV1 / BuildTerminalMessageHandler` | deterministic terminal content/result formatting only; no LLM/lifecycle decision/DB mutation/Connector I/O |
| SSE projection | 07/11 | `application/use_cases/sse_event/project_run_event.py` → `SseEventBufferPort` | bounded UI projection only; process-local buffer; snapshot fallback on cursor expiry |
| Run Retrieval Cache | 05/07/10 | `RunRetrievalCachePort → InMemoryRunRetrievalCache` | process-local raw continuation/read-result cache; single instance from composition; terminal `discard_run`; restart starts empty |
| Retrieval cache restart | 05/06/08 | `application/use_cases/run/reconcile_retrieval_cache_restart.py → ReconcileRetrievalCacheRestartHandler` | only producer of durable `RETRIEVAL_CACHE_RESTART`; deterministic trigger + handoff dedupe/stage + existing scheduler |
| Orphan Write reconciliation | 04/State/08/10 | `application/use_cases/execution_attempt/reconcile_inflight_executions.py → ReconcileInflightExecutionsCommand / ReconcileInflightExecutionsResult / ReconcileInflightExecutionsHandler` | startup-only batch after MCP/LLM readiness; `POST_BEGIN_ORPHAN → UNKNOWN_RESULT_UNRESOLVED → EXECUTED_AWAITING_VERIFICATION | FAILED_AWAITING_CONTINUATION` durable phases; blind resend 0; live invocation 0 |
| Trace | 11 | `application/use_cases/trace_event/emit_trace_event.py` → `TraceEventRepository` | non-authoritative diagnostic correlation; post-commit short UoW |
| Audit | 11 + 04 | owning lifecycle handler stages 11-owned AuditEvent in the same `UnitOfWork`; `AuditEventRepository` persists it atomically with Receipt/Domain mutation | durable security/domain event with secret minimization |

이 표의 row가 없는 새 핵심 stage를 구현해야 한다면 Design Freeze를 깨는 새 요구사항으로 취급한다.
