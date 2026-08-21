# 02. Directory Ownership

> Parent: Repository Architecture Source v1.4

## Top-level ownership

```text
src/google_work_agent/
├─ domain/
├─ application/
├─ ports/
├─ adapters/
├─ api/
└─ launcher/
```

## Domain

Domain organization follows canonical semantic owner, not persistence-table layout or historical aggregate buckets.

Examples:

```text
domain/run/
domain/plan/
domain/action/
domain/approval/
domain/claim/
domain/execution_attempt/
domain/verification/
domain/recovery/
domain/resource_ref/
domain/conversation/
```

Lifecycle transitions and guards are operation-per-file:

```text
domain/run/transitions/block_run.py
domain/run/transitions/finalize_cancel.py
domain/action/guards/claim_execution.py
```

Final production must not use broad `commands.py`, `transitions.py`, `guards.py`, or equivalent multi-capability buckets. Domain model types that share one cohesive invariant set may remain in `domain/<owner>/model.py`.

## Application

```text
application/agents/
  request_understanding/
  tool_routing/
  retrieval/
  work_analysis/
  planning/
  review/

application/use_cases/<semantic_owner>/
application/orchestration/
```

Application semantic owner packages are singular.

Agent semantic implementation is operation-per-file:

```text
application/agents/<role>/<verb>_<object>.py
```

Owner-local contract types live under:

```text
application/agents/<role>/contracts/<artifact_name>.py
```

A global catch-all production `contracts/` package is prohibited.

## Ports

Ports represent stable boundaries, not implementation folders.

```text
ports/persistence/
ports/connectors/
ports/llm/
ports/events/
```

## Adapters

```text
adapters/langgraph/
adapters/persistence/sqlite/
adapters/connectors/
adapters/llm/
```

Concrete adapter code may depend on stable Ports/contracts but does not become Application authority.

LangGraph routing is operation-per-file:

```text
adapters/langgraph/main/routing/route_after_<stage>.py
adapters/langgraph/subgraphs/<role>/routing/route_after_<stage>.py
```

A catch-all `routing.py` is not final production structure.

LangGraph input projections are owner-local:

```text
adapters/langgraph/main/projections/<scope>_projection.py
adapters/langgraph/subgraphs/<role>/projections/<scope>_projection.py
```

## API

```text
api/routes/
api/schemas/
api/dependencies/
```

REST collection/resource names are plural where natural.

## Launcher

```text
launcher/composition.py
```

Composition only. No business semantic owner is placed in Launcher.
