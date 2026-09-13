# Resident OS UI primitives

This package intentionally owns only the visual semantics that carry operational
meaning:

- `StatusLamp` renders every priority as a coloured lamp **and** a written label.
- `EvidenceRail` connects claim fragments and citation chips through shared
  pointer/focus state; claims can be focused with the keyboard.
- `DecisionMarker` labels a blue machine proposal separately from a brass human
  authorisation, so colour is never the only cue.

Use the application-local shadcn components for ordinary buttons, fields, cards,
badges, and layout. Keep this package presentational: it must not fetch data,
hold credentials, invent API-shaped models, or make an operational decision.

The package declares React as a peer dependency. Its source is transpiled by the
web application; use the public `@resident-os/ui` entry point rather than importing
files from `src` directly.
