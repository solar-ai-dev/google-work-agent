# READ THIS FIRST

CURRENT MAPPING BASELINE:
`a03432c8fa6d722c6ef93b54ff8de5aa16eeac0a`

THIS DIRECTORY IS:
The operational Phase-2 Canonical ↔ Current implementation mapping baseline.

This directory intentionally contains only the files required to operate the mapping.
Validation reports, temporary audit notes, cycle reports, and artifact manifests are not operational authority and are excluded.


## Authority read order

Operational reads MUST follow this order:

1. `README.md` — operating entry point and snapshot discipline
2. `ledger.md` — Phase-1 canonical implementation universe authority (`142 CAP + 473 STR + 85 NPA = 700`)
3. applicable layer mapping file — historical current→canonical evidence and disposition
4. `phase2-mapping-delta-reconciliation-a03432c8.md` — mapping-relevant current-HEAD reconciliation
5. `global-caller-import-duplicate-authority-closure-a03432c8.md` — remaining production closure / negative-proof status

`README.md` is the single entry point, but it does **not** replace `ledger.md`.
The Ledger remains the exact-set authority used to prove missing/extra/duplicate = 0.

## FORMAL UNIVERSE

```text
CAP 142/142
STR 473/473
NPA 85/85
TOTAL 700/700

MISSING   0
EXTRA     0
DUPLICATE 0
```

`FORMAL INVENTORY CLOSED / PASS` means the Phase-1 Ledger universe is represented exactly once in the mapping set.
It does **not** mean implementation, caller cut-over, negative proof, or global single-production-authority closure is complete.

## READ ORDER

1. `phase2-canonical-current-mapping-index-a03432c8.md`
2. target layer mapping, in closure order when doing full migration work:
   - Domain
   - Persistence
   - Application
   - Agent
   - LangGraph
   - Ports / Connectors / LLM
   - API / Composition
   - Frontend
   - Launcher / Installer / Release
   - Observability / Evaluation / Structural
3. `persistence-delta-reconciliation-6ec3ff49.md` when Persistence historical mapping is involved
4. `phase2-mapping-delta-reconciliation-a03432c8.md` — always apply after historical layer mappings
5. `global-caller-import-duplicate-authority-closure-a03432c8.md` — use for cross-layer caller/import/duplicate-authority closure

## SHA DISCIPLINE

A filename containing `453e7f0c` or `6ec3ff49` does **not** mean the mapping is obsolete.
Those files preserve evidence at their investigation SHA.

Never overwrite historical evidence with later code state.
Resolve implementation state as:

```text
historical mapping
→ applicable intermediate delta
→ a03432c8 mapping-relevant delta reconciliation
→ actual current production caller/import/test/negative-proof verification
```

Current-head mapping-relevant delta is reconciled through `a03432c8`.
Full production-wide closure validation is **not** complete.

## AUTHORITY

Canonical documents remain the design authority.
These mapping files are implementation/evidence indexes.

- DO NOT treat current code as design authority.
- DO NOT treat mapping closure as implementation closure.
- DO NOT infer CREATE from file absence alone.
- DO NOT delete reusable code before caller cut-over and negative proof.

## PRESERVATION ORDER

```text
KEEP
→ MOVE / RENAME / MOVE_RENAME
→ SPLIT / MERGE
→ TARGETED_CORRECTION
→ REWRITE only when preservation is unsafe
→ DELETE only after caller cut-over
→ CREATE only after proving reusable implementation is absent
```

## CURRENT HIGH-RISK OPEN ITEMS

- Connector Read and Write adapters still directly depend on `GoogleWorkspaceGateway` / provider-operation paths.
  `ValidatedConnectorToolBindingV1 → ConnectorRuntimeRegistry → MCPClientPort` is therefore not yet the sole production connector seam.
- Signed Tool Registry implementation mirror / connector descriptor projection remains open.
- Exact LLM provider/Ollama leaf authority split remains open.
- Retrieval `STR-477/478` exact owner-local contract files remain open.
- Repository-wide caller/import/duplicate-authority/test negative proof remains open.

## CURRENT STATUS

```text
FORMAL MAPPING INVENTORY             = PASS
SAFE AS IMPLEMENTATION MAPPING INDEX = YES

CURRENT-HEAD MAPPING-RELEVANT DELTA  = RECONCILED THROUGH a03432c8
FULL PRODUCTION CLOSURE VALIDATION   = NOT COMPLETE
IMPLEMENTATION COMPLETE              = NO
SINGLE PRODUCTION AUTHORITY CLOSED   = NO
STRUCTURAL CONTRACT PASS             = NO
ARCHITECTURE FROZEN                  = NO
```
