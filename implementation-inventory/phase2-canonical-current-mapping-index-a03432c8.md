# Google Work Agent — Phase-2 Canonical ↔ Current Mapping Index

**Repository:** `solar-ai-dev/google-work-agent`  
**Branch:** `refactor/canonical-architecture-migration`  
**Current reconciled HEAD:** `a03432c8fa6d722c6ef93b54ff8de5aa16eeac0a`  
**Correction revision:** `2026-08-27 exact-set repair + live-head reconciliation`

## Layer status

| Layer | Corrected formal universe | Mapping snapshot | Current-head reconciliation | Mapping artifact | Current implementation interpretation |
|---|---:|---|---|---|---|
| Domain | 61 STR | `453e7f0c...` | #104 closure through `a03432c8` | **CLOSED** | 54 model/transition core rows closed; 5 `*StatusV1` exact-symbol rows still partial; `RecoveryReasonV1` full. |
| Persistence / Repository / UoW / DB | 49 STR + 14 NPA | `453e7f0c...` + `6ec3` delta | materially refactored through `a03432c8` | **CLOSED** | Strongly improved; owner-local Domain records + generic CAS. Persistence-wide negative proof still open. |
| Application | 99 CAP + 1 STR | `6ec3ff49...` | materially refactored through `a03432c8` | **CLOSED** | Strongly improved; approval Plan defect closed; several broad/duplicate paths removed. |
| Agent semantic operations / retrieval contracts | 43 CAP + 2 STR | `6ec3ff49...` | tool-routing changed; retrieval contracts unchanged | **CLOSED** | Tool routing improved; `STR-477/478` exact contract files still open. |
| LangGraph | 139 STR | `6ec3ff49...` | material delta through `a03432c8` | **CLOSED** | Improved; checkpoint target compatibility bridge still open. |
| Ports / outbound adapters / Connector / LLM | 99 STR + 3 NPA | `6ec3ff49...` | small MCP + Domain-record delta | **CLOSED** | Connector MCP bypass, Tool Registry artifacts and LLM leaf split remain open. |
| API / Composition | 22 STR | `6ec3ff49...` | narrow current delta; STR-455 cross-ref only | **CLOSED** | Global composition-root closure open. |
| Frontend | 28 STR | `6ec3ff49...` | unchanged | **CLOSED** | Historical structural gaps remain. |
| Launcher / Installer / Release | 28 STR + 9 NPA | `6ec3ff49...` | marginal launcher delta | **CLOSED** | Broad dev launcher + install/release artifacts remain open. |
| Observability / Evaluation / structural surfaces | 44 STR + 59 NPA | `6ec3ff49...` | Domain architecture proof improved | **CLOSED** | Global prompt/eval/diagnostics/architecture closure open. |
| Global caller/import/duplicate closure | cross-layer negative proof | current | `a03432c8` | **INVENTORY CLOSED** | **GLOBAL RUNTIME CLOSURE OPEN**. |

## Exact-set closure

```text
CAP formal union                  = 142 / 142
STR formal union (effective)      = 473 / 473
NPA formal union                  = 85 / 85
TOTAL FORMAL ENTRIES              = 700 / 700
EXTRA FORMAL IDS                  = 0
DUPLICATE FORMAL IDS              = 0
RETIRED STR-313                   = excluded from effective set by Ledger
STR-455 formal owner              = Launcher only; API cross-reference only
```

## SHA discipline

- `453e7f0c...` / `6ec3ff49...` layer files remain historical code investigations.
- `persistence-delta-reconciliation-6ec3ff49.md` preserves the #100 delta.
- `phase2-mapping-delta-reconciliation-a03432c8.md` is the sole current-head override through `a03432c8fa6d722c6ef93b54ff8de5aa16eeac0a`.
- Current implementation improvements never erase the original preservation source/disposition.

## Current-head headline changes

- **Closed since 93f:** #104 Domain bounded 54-row model/transition authority, broad Domain barrels/tables, `ports/models.py`, duplicate approval use-case, approval Plan activation defect.
- **Still open:** Connector MCP single seam, Tool Registry implementation/projection artifacts, LLM leaf split, Retrieval exact contracts, checkpoint compat bridge, broad dev composition, remaining NPA artifact realization and repository-wide negative proof.

## Final meaning

```text
PHASE-2 CANONICAL ↔ CURRENT FORMAL INVENTORY = COMPLETE
HISTORICAL SNAPSHOT DISCIPLINE                = PRESERVED
CURRENT-HEAD DELTA RECONCILIATION             = COMPLETE THROUGH a03432c8
MAPPING ARTIFACT SAFE AS IMPLEMENTATION INDEX = YES

IMPLEMENTATION COMPLETE                       = NO
SINGLE PRODUCTION AUTHORITY CLOSED GLOBALLY    = NO
STRUCTURAL_CONTRACT_PASS                       = NO
ARCHITECTURE FROZEN                            = NO
```
