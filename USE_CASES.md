# Use Cases

Status ledger for use cases under `use-cases/`. Machine-maintained — the `define-use-case` skill appends rows; the dev-team orchestrator updates the `Status` and `Updated` columns as it works. Do not hand-edit those two columns unless you know why; edit the use-case file or re-run the skill instead.

Statuses:
- `pending` — saved but not yet picked up by the dev-team
- `in-progress` — the dev-team has started analysis
- `done` — implementation and tests completed
- `blocked` — the dev-team escalated (6-round cap hit, user abort, or infeasibility)

| # | File | Title | Status | Updated |
|---|------|-------|--------|---------|
| 01 | [use-cases/01-multi-sim-architecture-adr.md](use-cases/01-multi-sim-architecture-adr.md) | Restructure into a multi-sim architecture and record the ADR | done | 2026-08-30 |
| 02 | [use-cases/02-contributing-extension-points.md](use-cases/02-contributing-extension-points.md) | Contributor guide for the new extension points | in-progress | 2026-08-30 |
