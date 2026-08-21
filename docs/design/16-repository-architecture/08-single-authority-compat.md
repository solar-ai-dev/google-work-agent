# 08. Single Production Authority · Compat

> Parent: Repository Architecture Source v1.4

## Single authority

Every semantic capability has exactly one live production owner.

For each capability the repository must answer:

```text
What is the one production owner module?
Who calls it?
Which Domain fact/owner does it mutate?
Which Port does it depend on?
Which Adapter implements the Port?
```

If two live modules implement equivalent semantics, the repository is structurally invalid even if only one is intended to be canonical.

## Migration completion

A structural migration is complete only when:

```text
new canonical owner is live
+ every production caller moved
+ old owner deleted
+ compatibility wrapper deleted
+ tests target canonical owner
```

“New implementation exists” is not completion.

## `_compat`

`_compat` is allowed only as a transient migration tool on the structural-refactor integration branch.

Final rule:

```text
_COMPAT_ALLOWED_ON_REFACTOR_INTEGRATION = YES, transient only
_COMPAT_ALLOWED_ON_MAIN                 = NO
```

Public production exports must not permanently point to `_compat`.

Patch-stack inheritance, version wrapper chains, and permanent canonical→legacy delegation are not accepted final architecture.
