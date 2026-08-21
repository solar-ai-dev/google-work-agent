# Semantic Naming Grammar

## Principle

Naming must identify semantic responsibility.

Do not encode migration history in production module names.

## Use cases

```text
<verb>_<object>.py
<Verb><Object>Command
<Verb><Object>Result
<Verb><Object>Handler
```

Examples:

```text
block_run.py
approve_action.py
claim_action.py
verify_action.py
recover_unknown_result.py
```

## Queries

```text
get_run.py
list_conversations.py
search_messages.py
```

## Connector effects

```text
create_message.py
get_message.py
search_messages.py
update_message.py
delete_message.py
send_message.py
```

Each file owns exactly that operation.

## LangGraph

```text
classify_request_node.py
validate_relations_node.py
route_after_review.py
graph.py
state.py
routing.py
request_projection.py
```

## Repositories

```text
run_repository.py
plan_repository.py
action_repository.py
approval_repository.py
claim_repository.py
execution_attempt_repository.py
verification_repository.py
resource_ref_repository.py
```

## Forbidden final production names

```text
runtime.py
manager.py
service.py
helpers.py
utils.py
common.py
misc.py

canonical_*.py
production_v*.py
legacy_*.py
new_*.py
old_*.py
final_*.py
*_v2.py
*_r2.py
*_r21.py
```

A generic name may exist only with an explicit architectural exception and one responsibility.

## Versioning

Allowed in DTO/contract type names:

```text
RequestIntentV2
WorkAnalysisResultV2
```

Not allowed as parallel production implementation filenames.
