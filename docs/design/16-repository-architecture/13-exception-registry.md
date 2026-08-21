# 13. Architecture Exception Registry

> Parent: Repository Architecture Source v1.4

Architecture exceptions are closed-by-default.

A new exception requires an explicit entry containing:

```text
rule being excepted
exact path/symbol
semantic reason
authority owner
scope
removal condition or permanent rationale
approval date
```

Undocumented exceptions are violations.

Adding, widening, or making permanent an exception is a Repository Architecture contract change and requires a Repository Architecture version increment plus Project Source Guide synchronization. An exception must never be introduced only in code or only in an enforcement allowlist.

## Built-in filename-role exceptions

The following generic-looking filenames are allowed only because they represent explicit architecture roles:

```text
state.py
graph.py
model.py
composition.py
```

This exception does not permit those files to become mixed-responsibility buckets.

Routing is not exempt. Final production routing uses:

```text
routing/route_after_<stage>.py
```

## Current frozen exceptions

No exception permits:

- `_compat` on `main`,
- duplicate semantic production authority,
- Application direct Provider SDK access,
- Production imports from Evaluation,
- permanent version-wrapper chains,
- a global catch-all `contracts/` package,
- a catch-all final-production `routing.py`,
- undocumented naming or placement discretion.
