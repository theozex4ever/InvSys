# Domain docs

## Layout

This repository uses a single context:

- GLOSSARY.md at the repository root
- Architecture decision records under docs/adr/

## Consumer rules

Before exploring domain behavior, read GLOSSARY.md and any
ADRs relevant to the area being changed.

If these documents do not exist, proceed silently.
Domain-modeling work creates them when terms or decisions
need recording.

Use the glossary's vocabulary when naming domain concepts
in issues, proposals, code, and tests.

If a needed concept is absent, check existing project usage
before identifying a glossary gap.

If a proposal contradicts an ADR, cite the ADR and explain
why the decision should be revisited.
