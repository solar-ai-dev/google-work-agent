# Compatibility evaluation artifacts

This directory preserves non-current experiment inputs and replay tooling for
historical reproduction. Nothing under `evaluation/compat/` is a current
dataset, grader, scoring, result, Product policy, or Product runtime authority.

Current Evaluation code consumes only the versioned contracts and artifacts at
their exact paths under `evaluation/` outside this directory. Product runtime
must never import this package.
