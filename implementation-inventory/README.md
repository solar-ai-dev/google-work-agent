# READ THIS FIRST

CURRENT MAPPING BASELINE:
a03432c8fa6d722c6ef93b54ff8de5aa16eeac0a

THIS PACKAGE IS:
A validated Phase-2 Canonical ↔ Current implementation mapping baseline.

FORMAL UNIVERSE:
CAP 142/142
STR 473/473
NPA 85/85
MISSING 0
EXTRA 0
DUPLICATE 0

READ ORDER:

1. phase2-canonical-current-mapping-index-a03432c8.md

2. target layer mapping
   Domain
   → Persistence
   → Application
   → Agent
   → LangGraph
   → Ports/Connectors
   → API/Composition
   → Frontend
   → Launcher/Installer/Release
   → Observability/Evaluation/Structural

3. persistence-delta-reconciliation-6ec3ff49.md
   when Persistence historical mapping is involved

4. phase2-mapping-delta-reconciliation-a03432c8.md
   ALWAYS apply this after historical layer mappings

5. global-caller-import-duplicate-authority-closure-a03432c8.md
   for cross-layer caller/duplicate-authority closure

IMPORTANT SHA RULE:

A filename containing 453e7f0c or 6ec3ff49 does NOT mean the mapping is obsolete.

Those files preserve evidence at their investigation SHA.

Do not overwrite historical mapping facts with current HEAD.

Resolve current state as:

historical mapping
→ applicable intermediate delta
→ a03432c8 delta reconciliation

AUTHORITY:

Canonical documents remain the design authority.
These mapping files are implementation/evidence indexes.

DO NOT treat current code as design authority.
DO NOT treat mapping COMPLETE as implementation COMPLETE.

PRESERVATION ORDER:

KEEP
→ MOVE / RENAME / MOVE_RENAME
→ SPLIT / MERGE
→ TARGETED_CORRECTION
→ REWRITE only when preservation is unsafe
→ DELETE only after caller cut-over
→ CREATE only after proving reusable implementation is absent

CURRENT STATUS:

MAPPING ARTIFACT = PASS
SAFE AS IMPLEMENTATION MAPPING INDEX = YES

IMPLEMENTATION COMPLETE = NO
SINGLE PRODUCTION AUTHORITY CLOSED = NO
ARCHITECTURE FROZEN = NO