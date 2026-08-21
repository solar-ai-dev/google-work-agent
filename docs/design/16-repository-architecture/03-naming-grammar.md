# 03. Naming Grammar

> Parent: Repository Architecture Source v1.1

## Python grammar

```text
package/module/function/variable → snake_case
class/type                       → PascalCase
constant/enum value/error code   → UPPER_SNAKE_CASE
```

## Application capability

```text
<verb>_<object>.py
<Verb><Object>Command | <Verb><Object>Query
<Verb><Object>Result
<Verb><Object>Handler
```

Command/Query + Result + Handler for one capability are colocated in that capability file.

## Domain lifecycle

```text
domain/<owner>/transitions/<verb>_<object>.py
domain/<owner>/guards/<verb>_<object>.py
```

## Connector operation

```text
<verb>_<resource>.py
<Verb><Resource>Operation
```

## LangGraph node

```text
<verb>_<object>_node.py
<verb>_<object>_node()
```

## Router / graph / state / projection

```text
routing.py                   route_after_<stage>() or explicit routing function
graph.py                     build_<scope>_graph()
state.py                     <Scope>State
<scope>_projection.py        project_<scope>_input()
```

## Package singular/plural

- Domain/Application owner package: singular.
- REST route collection: plural.
- Provider resource package: Provider-natural plural is allowed.

## Field suffixes

```text
<entity>_id
*_ref / *_refs
*_handle / *_handles
*_hash
*_version
*_at_ms
```

New booleans prefer `is_`, `has_`, `can_`, or `should_` when applicable. Existing canonical fields such as `applied` remain unchanged.

## Versioning

Contract type versioning is allowed:

```text
RequestIntentV2
ToolRoutePlanV2
WorkAnalysisResultV2
CommandResponseV1
```

Production implementation module generation/version naming is prohibited:

```text
canonical_*.py
production_*.py
legacy_*.py
new_*.py
old_*.py
final_*.py
*_v2.py
*_v3.py
*_r2.py
*_r21.py
```

Generic production filenames are prohibited unless explicitly exempted:

```text
runtime.py
service.py
manager.py
processor.py
engine.py
handler.py
helpers.py
helper.py
utils.py
util.py
common.py
shared.py
misc.py
```

Architecture-role exceptions:

```text
state.py
graph.py
routing.py
model.py
composition.py
```

These exceptions do not permit mixed semantic responsibilities.

## Ambiguous operation names

Do not use the following as semantic operation verbs:

```text
handle
process
manage
perform
do
run
helper
util
common
```
