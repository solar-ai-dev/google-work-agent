# 05. Dependency · Import · Export Rules

> Parent: Repository Architecture Source v1.4

## Dependency direction

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

## Allowed

```text
Domain      → Domain
Ports       → Domain/stable contracts
Application → Domain + Ports
API         → Application + stable contracts
LangGraph   → Application + stable contracts/explicit Ports
Persistence → Ports + Domain
Connector   → connector Ports + stable contracts
LLM Adapter → LLM Ports
Launcher    → all layers for composition only
```

## Forbidden

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

## Import rule

Cross-owner production imports use absolute package imports so architecture direction and caller tracing remain visible.

## Export rule

`__init__.py` is empty by default.

Only stable public contracts/Ports may be deliberately re-exported. Concrete production implementations are imported from their canonical owner module. Barrel exports must not hide or redirect production authority.
