# 08. Single Production Authority · Compat

**Normative detail of the current Repository Architecture Source.**

Every semantic capability has exactly one live production owner.

Migration completion requires:

```
new canonical owner live
+ every production caller moved
+ old owner deleted
+ compatibility wrapper deleted
+ tests target canonical owner
```

`_compat` may exist transiently only on the structural-refactor integration branch. `_compat` on `main` is prohibited. Public exports must never permanently target `_compat`.

Patch-stack inheritance or permanent wrapper chains are structurally invalid.

## Structural closure contract

Structural refactor completion is a **negative-proof closure**, not a declaration that canonical files exist.

For each migrated capability, final production closure requires all of the following at the same target revision:

```
canonical authority live
+ intended production callers cut over
+ old production callers = 0
+ old production imports = 0
+ old concrete exports = 0
+ duplicate live authority = 0
+ forbidden compatibility path = 0
+ tests target canonical owner
```

A capability is **not migrated** merely because a canonical directory, file, Handler, Agent operation, Port, or Adapter exists.

### Compatibility lifecycle

Temporary compatibility is allowed only when all conditions are true:

- it exists on a structural-refactor integration branch, not final `main`;
- it has one bounded migration purpose and no independent business semantics;
- production callers are actively being moved away from it;
- it is not a public concrete-authority barrel export;
- its deletion is part of the same closure gate.

Final compatibility rule:

```
main: _compat = 0
legacy production wrapper = 0
read_* / write_* compatibility facade = 0 when it exposes migrated concrete authority
patch-stack / inheritance wrapper chain = 0
```

A stable public **contract or Port** re-export is not a compatibility violation. A concrete Handler, workflow runtime, service object, Adapter, or legacy facade re-export is.

### Application root and legacy workflow closure

`application/` root is not a semantic authority bucket. Final production root modules may not own use-case or Agent semantics. The root `__init__.py` is empty by default and may export only stable public contracts/Ports permitted by the dependency/export rules.

`application/workflows/**` is a legacy ownership island for the structural refactor. Final closure requires its production semantic authorities and production callers to be migrated to canonical `application/use_cases/**` or `application/agents/**` ownership, after which the legacy production tree is absent. Historical test fixtures or migration evidence may retain old path strings only as explicit architecture-enforcement negatives, never as importable production authority.

### External caller closure

Migration of Application authority is incomplete until every intended production boundary uses the canonical Application authority:

```
FastAPI routes/dependencies
LangGraph nodes/subgraphs
launcher/composition/dependency wiring
other production orchestrators
```

No boundary may retain a parallel legacy service/facade path after final closure.

### Closure verdict

Repository-level completion for a capability requires:

```
STRUCTURAL_CONTRACT_PASS
AND CALLER_CLOSURE_PASS
AND TEST_OWNERSHIP_PASS
AND BEHAVIOR_REGRESSION_PASS
```

A missing implementation is Implementation Work. Ambiguous or contradictory closure criteria are Documentation Blockers.
