---
name: Tool proposal
about: Propose a new Tool (spec-before-code — this form IS the spec draft)
title: "[tool] "
labels: ["type:tool", "type:feature"]
---

<!-- This mirrors the Phase 7 spec template (docs/07 §1). A completed form can be pasted
     into docs/07-tool-specifications.md nearly as-is — that's the point. -->

## Purpose

<!-- What does it do, and what does it teach? One sentence each. -->

## Spec

| Field | Value |
|---|---|
| `name` | <!-- snake_case --> |
| `title` | <!-- shown in the pipeline --> |
| `sensitive` | <!-- true if it modifies files/system state → confirmation gate. Deletion is not possible: no tool may delete (S-1). --> |
| `icon` | <!-- lucide icon name --> |
| `detail_template` | <!-- child-readable, ≤10 words: "Doing X on your PC" --> |

## Description (written for the LLM)

<!-- When should the model pick this tool? Include 1–2 example user phrasings. -->

## Inputs

<!-- Each parameter: name, type, constraints, description. These become a Pydantic model. -->

## Outputs

<!-- JSON shape; must include a "summary" string NOVA can speak. -->

## Errors

<!-- Declared error codes + when each occurs. -->

## Future improvements

<!-- Optional -->

## Author checklist (docs/07 §10)

- [ ] Read-only where possible; moves, never deletes
- [ ] Stays inside user-scoped folders (S-4)
- [ ] No new dependency — or TD entry proposed (P-6)
- [ ] I'd like to implement this myself: yes / no
