# 12. Architecture Enforcement

> Parent: Repository Architecture Source v1.3

Architecture checks must be machine-enforceable where practical.

Required enforcement families:

- forbidden production filename patterns
- forbidden dependency edges/imports
- Provider SDK access outside connector MCP adapters
- multiple semantic-authority detection
- `_compat` zero on `main`
- production→evaluation import ban
- LangGraph node thin-adapter boundary
- unit-test mirror checks for migrated capabilities
- direct concrete-adapter imports from Application
- barrel exports that hide concrete authority
- Workflow v7.22 atomic responsibility ownership: heavy-Agent broad modules must not collapse distinct `facts / relations / gaps / risks`, `action objective / arguments`, or Review inspection dimensions into one production implementation file
- Local SLLM node implementation paths must map one semantic LLM responsibility to one owner-local operation file; deterministic aggregators/builders remain separate from LLM callers

Architecture enforcement complements, but does not replace, behavioral tests.
