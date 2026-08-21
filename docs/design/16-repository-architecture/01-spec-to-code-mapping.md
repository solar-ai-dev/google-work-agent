# 01. Spec → Code Deterministic Mapping

> Parent: Repository Architecture Source v1.1

## Rule

Implementation lookup is deterministic:

```text
SPEC TERM
→ CANONICAL TERM
→ SEMANTIC OWNER
→ LAYER
→ OPERATION
→ PATH
→ FILE
→ SYMBOL
→ TEST PATH
```

Do not begin from an existing filename or from grep results that merely look similar.

## Examples

### BlockRun

```text
BlockRun
→ run
→ Application Use Case
→ block
→ application/use_cases/run/block_run.py
→ BlockRunCommand / BlockRunResult / BlockRunHandler
→ tests/unit/application/use_cases/run/test_block_run.py
```

Domain transition/guard implementation, if separate from the Application handler:

```text
domain/run/transitions/block_run.py
domain/run/guards/block_run.py
```

### Work Analysis relation validation node

```text
Work Analysis / validate relations / LangGraph node
→ work_analysis
→ adapters/langgraph/subgraphs/work_analysis/nodes/validate_relations_node.py
→ validate_relations_node()
```

The node only projects typed input, calls Application semantics, and returns the typed owner-field patch/workflow signal.

### Gmail draft create

```text
Google / Gmail / Draft / CREATE
→ adapters/connectors/google/gmail/drafts/create_draft.py
→ CreateDraftOperation
```

### API approve action

```text
ApproveAction wire request
→ api/routes/actions.py
→ api/schemas/actions/approve_action.py
→ application/use_cases/action/approve_action.py
```

## Semantic search before implementation

After calculating the target location, search the repository for every equivalent capability by inspecting:

- writers of the same Domain fact/owner,
- writers of the same Main State owner field,
- callers of the same repository mutation,
- implementations of the same external effect,
- handlers of the same transition/result,
- equivalent exported symbols,
- production caller chains,
- tests asserting the same semantic outcome.

If an implementation already exists outside the canonical location, migrate it. Do not create another implementation.
