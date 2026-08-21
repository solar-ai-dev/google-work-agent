# 12. Architecture Enforcement

> Parent: Repository Architecture Source v1.1

Architecture rules should be machine-enforced where practical.

## Required enforcement families

- forbidden production filename patterns
- forbidden dependency/import edges
- direct Provider SDK/API access outside Connector MCP adapters
- multiple live semantic-authority detection
- `_compat` zero on `main`
- Production → Evaluation import ban
- thin LangGraph node boundary
- concrete Adapter imports from Application
- barrel exports that hide concrete authority
- migrated unit-test path mirror checks
- mixed-responsibility connector operation files

## Enforcement result

Architecture enforcement does not replace behavioral tests. A refactor lane must pass both:

```text
STRUCTURAL_CONTRACT_PASS
BEHAVIOR_REGRESSION_PASS
```

## Main merge gate

Before structural-refactor work can merge to `main`:

```text
NO_SEMANTIC_AUTHORITY_COLLISION
NO_COMPAT_ON_MAIN
NO_FORBIDDEN_IMPORT_EDGE
NO_FORBIDDEN_PRODUCTION_FILENAME
PRODUCTION_CALLERS_CANONICAL
TESTS_TARGET_CANONICAL_OWNER
```

Any exception must exist in the explicit exception registry.
