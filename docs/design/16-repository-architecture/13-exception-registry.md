# 13. Architecture Exception Registry

> Parent: Repository Architecture Source v1.1

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

## Built-in filename-role exceptions

The following generic-looking filenames are allowed only because they represent explicit architecture roles:

```text
state.py
graph.py
routing.py
model.py
composition.py
```

This exception does not permit those files to become mixed-responsibility buckets.

## Current frozen exceptions

No exception permits:

- `_compat` on `main`,
- duplicate semantic production authority,
- Application direct Provider SDK access,
- Production imports from Evaluation,
- permanent version-wrapper chains,
- a global catch-all `contracts/` package.
