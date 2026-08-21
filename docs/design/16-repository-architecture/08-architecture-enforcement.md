# Architecture Enforcement Rules

Documentation alone is insufficient. Add automated release gates.

## Import boundary checks

Fail if:

```text
domain imports application/adapters/api
application imports concrete adapters
langgraph imports persistence concrete
langgraph imports provider SDK
langgraph imports concrete MCP transport
persistence imports application
connector imports application workflow
production imports evaluation
```

## Naming checks

Fail final production modules matching:

```text
canonical_*
production_v*
legacy_*
*_v2.py
*_r2.py
*_r21.py
helpers.py
utils.py
common.py
misc.py
```

Generic names such as `runtime.py`, `manager.py`, `service.py` require an explicit allowlist exception.

## Capability ownership check

Maintain a machine-readable capability manifest.

Fail if a semantic capability has:
- zero owner where required,
- more than one live production owner.

## State writer check

Fail when a canonical Main State business field has multiple writers.

## LangGraph purity check

Fail when LangGraph adapter imports or invokes:
- concrete repository implementation,
- DB connection helper,
- provider SDK,
- concrete MCP transport.

## Barrel import check

Disallow broad package imports that make unrelated/evaluation modules production dependencies.

## File-size guardrail

Recommended:

```text
<= 300 LOC  normal
301–500     architectural review
> 500       fail unless explicit exception
```

LOC is an alarm, not the definition of responsibility.

## Required CI outputs

Architecture CI should produce:

```text
IMPORT_BOUNDARY_STATUS
FORBIDDEN_FILENAME_STATUS
CAPABILITY_AUTHORITY_STATUS
STATE_WRITER_STATUS
LANGGRAPH_PURITY_STATUS
BARREL_IMPORT_STATUS
OVERSIZED_MODULE_STATUS
```
