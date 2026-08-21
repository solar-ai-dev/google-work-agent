# 02. Directory Ownership

> Parent: Repository Architecture Source v1.1

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

Lifecycle operations and guards are operation-per-file:

```text
domain/run/transitions/block_run.py
domain/run/transitions/finalize_cancel.py
domain/action/guards/claim_execution.py
```

A broad `commands.py` or `transitions.py` file is not accepted final production structure when it owns multiple independent lifecycle capabilities.

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
