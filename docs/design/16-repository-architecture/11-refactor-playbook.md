# 11. Structural Refactor Playbook

> Parent: Repository Architecture Source v1.4

Refactoring preserves behavior unless a separate concern-specific canonical contract explicitly requires a semantic change.

For each capability:

```text
DISCOVER
→ CLASSIFY
→ MAP CANONICAL OWNER
→ MOVE / SPLIT / MERGE
→ REWIRE ALL CALLERS
→ DELETE OLD AUTHORITY
→ MOVE TESTS
→ RUN STRUCTURAL + BEHAVIOR REGRESSION
```

Do not create a new canonical file and leave the old caller alive. A structural task is incomplete until old production authority and transient wrapper are gone.

Workflow v7.22 atomic responsibility refactor additionally requires broad heavy-Agent modules to be split without changing Agent ownership. For Work Analysis / Planning / Review, move one semantic LLM responsibility at a time, rewire its caller, preserve Typed Local Candidate boundaries, then delete the old broad responsibility. A temporary facade may exist only on the integration branch and must not survive on `main`.

When a capability cannot be mapped to the closed-world v1.4 naming/placement grammar, do not improvise a filename or directory. Record and version an explicit architecture exception before implementation.
