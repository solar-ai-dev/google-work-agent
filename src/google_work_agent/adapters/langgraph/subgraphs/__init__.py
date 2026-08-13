"""SIX_ROLE_BASELINE native LangGraph subgraphs.

Each module in this package owns exactly one subgraph: its ``StateGraph``
wiring plus its node bodies. Moved out of the monolithic
``adapters.langgraph.runtime`` (Stage 5 of the LangGraph module cleanup) with
no behavior change -- only the module/class each subgraph's code lives in
changed, plus the removal of the now-redundant ``<subgraph>_subgraph_``
prefix on node method names (the class name already carries that context).
"""

from __future__ import annotations
