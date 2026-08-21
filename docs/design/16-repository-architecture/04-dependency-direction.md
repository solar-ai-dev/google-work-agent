# Dependency Direction Contract

## Canonical direction

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

Launcher → all layers for composition only
```

## Allowed dependency table

| Layer | May depend on |
|---|---|
| Domain | Domain, stdlib |
| Ports | Domain, typing/stdlib |
| Application | Domain, Ports, Application |
| API | Application, stable contracts |
| LangGraph Adapter | Application, Ports, LangGraph-local modules |
| Persistence Adapter | Persistence Ports, Domain |
| Connector Adapter | Connector Ports, stable Domain contracts |
| LLM Adapter | LLM Ports |
| Launcher | all layers for wiring only |
| Evaluation | public production contracts |

## Forbidden edges

```text
Domain      → Application
Domain      → Adapters
Domain      → API

Application → concrete Adapters
Application → provider SDK
Application → concrete MCP transport

LangGraph   → SQLite repository concrete
LangGraph   → provider SDK/API
LangGraph   → concrete MCP transport
LangGraph   → Domain transition implementation

Persistence → Application use case
Connector   → Application workflow

Production  → Evaluation
```

## Composition root exception

`launcher/composition.py` may instantiate and connect concrete implementations.

It must not contain rules such as:

```text
if approval.status ...
if action.status ...
if review.status ...
```

Those belong to inner semantic owners.
