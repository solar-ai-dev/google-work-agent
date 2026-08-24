# 13. Exception Registry

**Normative detail of the current Repository Architecture Source.**

Architecture exceptions are closed-by-default. A new exception requires an explicit registry entry containing:

```
rule being excepted
exact path/symbol
semantic reason
authority owner
scope
removal condition or permanent rationale
approval date
```

Undocumented exceptions are violations. `state.py`, `graph.py`, `model.py`, and `composition.py` are explicit architecture-role filename exceptions; this does not permit them to become mixed-responsibility buckets. Routing is not exempt: final production routing uses `routing/route_after_<stage>.py`.

Adding, widening, or making permanent an exception is a Repository Architecture contract change and requires explicit Source Guide synchronization before implementation. Repository Architecture version numbers are traceability metadata, not an independent Gate. An exception must never be introduced only in code or only in an enforcement allowlist.
