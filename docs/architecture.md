# DiffSentry — architecture

## Pipeline

```
diff text ──► diffparse ──► chunking ──► engine ──► CodeReviewResult ──► render
 (PR API,      files,        structure-   static AST    Pydantic schema     terminal /
  file, git)   hunks,        aware,       rules or      (the contract)      JSON /
               line nos      token        LLM per                          Markdown /
                             budget       chunk                            PR comment
```

## Why the schema is the centre

Every engine — deterministic rules today, an LLM tomorrow, a hybrid in
production — returns the same `CodeReviewResult`. That one decision makes
the rest of the system possible: renderers don't care which engine ran,
the eval harness scores engines identically, the GitHub Action's pass/fail
is a pure function of severities, and an LLM can be swapped or upgraded
without touching anything downstream.

## Chunking

Segments are cut at hunk boundaries and at top-level `def`/`class`
boundaries, then greedily packed under the token budget. A segment bigger
than the budget is hard-split at line boundaries (the only lossy case, and
it is reported in the chunk metadata). Each chunk carries its file,
new-file line range, and enclosing function when uniform.

## Static engine notes

- AST rules run per hunk: context+added lines are reconstructed into a
  parseable block (dedented), and node line numbers map back through the
  block's line table to new-file line numbers.
- Rules track lexical context — a `requests.get` inside a `try:` is fine,
  the same call outside one is a finding; `re.compile` is only flagged
  inside loops.
- Line rules cover what ASTs can't (other languages, fragments that don't
  parse): AWS key shapes, private-key markers, generic secret assignments.
- The missing-tests rule is diff-level by design: it asks whether the
  *change as a whole* ships tests, which no per-file analysis can answer.

## LLM engines

One schema-bound call per chunk. OpenAI: `response_format` JSON Schema
from `CodeReviewPayload.model_json_schema()`. Anthropic: forced tool use
with the same schema as `input_schema`. Validation failure → the error is
returned to the model for exactly one repair attempt → loud failure.
LLM results are merged with the static engine's diff-level findings
(secrets, missing tests), deduplicated on (file, line, rule).

## Evaluation discipline

The golden set is small on purpose: every case is hand-labelled with the
exact rules that must fire, including a clean file where *nothing* may
fire (precision matters as much as recall — a reviewer that cries wolf
gets muted). Adding a rule without adding its golden case fails the
recall gate's spirit even when it passes its letter; both are updated
together.
