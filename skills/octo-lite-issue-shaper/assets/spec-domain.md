# <Domain Name>

Follow the target repo's `AGENTS.md` format signal. This Markdown template is
the default for unsignaled or `Spec format: markdown` repos. In a
`Spec format: spec-chat` repo, create the corresponding `*.spec.html` document
with these same sections, a unique `data-anchor` on every section and
meaningful block, one sentence per prose line, and pretty-printed semantic
islands for visual state.

## Intended behavior

TBD

## Domain concepts

TBD

## Rules and invariants

TBD

## Interfaces/contracts

TBD

## Edge cases

TBD

## Constraints

TBD

## Non-goals

TBD

## Open questions about system behavior

TBD

## Decision log or links to ADRs

TBD

## References to source issues

TBD

For spec-chat documents, review the rendered HTML through the serve → annotate
→ hand off → drain → edit → reply loop before marking shaping ready. The HTML
is canonical and no domain Markdown counterpart is regenerated.
