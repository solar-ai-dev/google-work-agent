# 03. Naming Grammar

> Parent: Repository Architecture Source v1.4

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

## Deterministic and Domain operations

```text
<verb>_<object>.py
<verb>_<object>()
```

Domain lifecycle uses explicit symbols:

```text
domain/<owner>/transitions/<verb>_<object>.py → transition_<verb>_<object>()
domain/<owner>/guards/<verb>_<object>.py      → guard_<verb>_<object>()
```

Validator, resolver, builder, assembler, mapper, and normalizer operations use their semantic verb as both filename and function prefix:

```text
validate_<object>.py   → validate_<object>()
resolve_<object>.py    → resolve_<object>()
build_<object>.py      → build_<object>()
assemble_<object>.py   → assemble_<object>()
map_<object>.py        → map_<object>()
normalize_<object>.py  → normalize_<object>()
```

## Agent semantic operation

```text
application/agents/<role>/<verb>_<object>.py
<verb>_<object>()
```

One versioned atomic semantic responsibility owned by 06/15 maps to one owner-local operation file unless the owning runtime contract explicitly defines deterministic composition instead. Broad modules such as `analyze.py`, `planning.py`, and `review.py` may not own multiple independent semantic responsibilities.

Owner-local contract types use:

```text
application/agents/<role>/contracts/<artifact_name>.py
<ArtifactName>[Vn]
```

A global catch-all production `contracts/` package is prohibited.

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
routing/route_after_<stage>.py  route_after_<stage>()
graph.py                        build_<scope>_graph()
state.py                        <Scope>State
projections/<scope>_projection.py project_<scope>_input()
```

Routing is operation-per-file. Catch-all final-production `routing.py` is prohibited.

## Registry / error / configuration

```text
<subject>_registry.py                 <Subject>Registry
<subject>_<condition>_error.py        <Subject><Condition>Error
<concern>_config.py                   owner-local runtime/build configuration
<concern>_settings.py                 persisted/user settings only when the owning contract distinguishes settings
```

Generic `config.py` and broad multi-authority `errors.py` are prohibited.

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

Generic production filenames are prohibited unless explicitly exempted by the parent architecture role grammar or Exception Registry:

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
config.py
errors.py
```

Architecture-role filename exceptions are exactly:

```text
state.py
graph.py
model.py
composition.py
```

These exceptions do not permit mixed semantic responsibilities. `routing.py` is not an exception.

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

## Closed-world rule

If a production construct does not match a grammar in Repository Architecture Source v1.4 or its normative subordinate pages, do not invent a new pattern. Map it to an existing grammar or add an explicit, versioned Exception Registry entry first.
