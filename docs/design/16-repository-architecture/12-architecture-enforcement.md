# 12. Architecture Enforcement

> Parent: Repository Architecture Source v1.4

Architecture checks must be machine-enforceable where practical.

Required enforcement families:

- forbidden production filename patterns, including generic `runtime.py`, `service.py`, `manager.py`, `processor.py`, `engine.py`, `handler.py`, `helpers.py`, `utils.py`, `common.py`, `shared.py`, `misc.py`, `config.py`, and broad multi-authority `errors.py` unless explicitly registered
- forbidden dependency edges/imports
- Provider SDK access outside connector MCP adapters
- multiple semantic-authority detection
- `_compat` zero on `main`
- production→evaluation import ban
- LangGraph node thin-adapter boundary
- routing operation-per-file: final production `routing/route_after_<stage>.py`, no catch-all `routing.py`
- Domain transition/guard operation-per-file; no broad multi-capability `commands.py`, `transitions.py`, or `guards.py`
- Agent semantic responsibility operation-per-file under `application/agents/<role>/`
- owner-local contract package rule; no global catch-all production `contracts/` package
- unit-test mirror checks for migrated capabilities
- direct concrete-adapter imports from Application
- barrel exports that hide concrete authority
- Workflow v7.22 atomic responsibility ownership: heavy-Agent broad modules must not collapse distinct `facts / relations / gaps / risks`, `action objective / arguments`, or Review inspection dimensions into one production implementation file
- Local SLLM node implementation paths must map one semantic LLM responsibility to one owner-local operation file; deterministic aggregators/builders remain separate from LLM callers

Architecture enforcement complements, but does not replace, behavioral tests.

Enforcement allowlists may only encode exceptions already present in the Repository Architecture Exception Registry. An enforcement-only exception is itself a contract violation.
