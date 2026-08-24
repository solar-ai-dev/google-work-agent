# 05. Dependency · Import · Export Rules

**Normative detail of the current Repository Architecture Source.**

03 Architecture owns system/layer dependency semantics. This page owns their **repository import/export realization and enforcement** and cannot relax 03.

```
API / LangGraph → Application → Domain + Ports ← Outbound Adapters
Launcher → launcher-local orchestration + system boundaries only; no Application/Domain business ownership
```

Forbidden repository edges: Domain→Application/Adapter/API; Application→concrete Adapter/provider SDK; LangGraph→SQLite implementation/provider SDK/concrete MCP transport/Domain transition implementation; Persistence→Application workflow; Connector→Application workflow; Production→Evaluation; product runtime→`installer/**` or `release/**`.

Cross-owner production imports use absolute imports. `__init__.py` is empty by default. Only stable public contracts/Ports may be deliberately re-exported. Concrete production authority is imported from its owner module so caller tracing remains explicit.

## Application dependency boundary

Final Application production code depends on Domain abstractions and Ports, not transport/runtime/concrete infrastructure responsibility.

Repository enforcement must fail if `application/**` imports, constructs, or owns:

- FastAPI transport responsibility or transport framework types used as use-case authority;
- LangGraph graph/routing responsibility (`StateGraph`, node/edge registration, interrupt routing);
- concrete Connector/MCP Adapter implementations or concrete Connector transport;
- Provider SDK/API clients;
- concrete SQLite adapters or direct `sqlite3` access.

Application may coordinate outbound work only through declared Ports/contracts. Composition may inject concrete implementations from the outer boundary; that does not transfer concrete ownership into Application.
Connector-specific rule: Application may use its structural `SignedToolRegistry` to materialize `ValidatedConnectorToolBindingV1` before invoking a Connector Port. Outbound Connector adapters may depend on that **shared validated contract value**, `ConnectorRuntimeRegistry`, and `MCPClientPort`, but may not import/call `application/tool_registry/SignedToolRegistry`. A reverse `adapters/** → application/**` import is an architecture violation.

For migrated capabilities, import closure also requires old production import paths to be zero. `__init__.py` or another barrel may not preserve an old concrete import path by re-exporting the new authority. Stable public contract/Port exports remain allowed only when explicitly intended and do not hide a concrete production owner.
