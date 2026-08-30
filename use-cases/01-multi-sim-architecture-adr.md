# Use Case 01: Restructure into a multi-sim architecture and record the ADR

## Summary

Restructure the project so that sims other than Liftoff can be added, and record
the reasoning and the rejected alternatives as an Architecture Decision Record.
The code moves to a `src/fpv_review/` package containing `sources/<sim>/` — each
sim implementing the same required module surface, starting with
`map_geometry_generator.py`, alongside its own extractors for flight paths,
shapes and lap data — and `common/`, holding the sim-agnostic analysis, the
report templates, and the Python dataclasses that define every artifact crossing
a stage boundary. Those dataclasses are the contract: a sim is pluggable when it
emits them, and each sim additionally declares which fields it cannot supply so
downstream stages name a missing finding instead of inferring one. A
`pyproject.toml` carrying `requires-python` and an empty dependency list declares
the zero-dependency promise to tooling without introducing an install step, since
the project ships by being cloned into `~/.claude/skills/` and run in place. This
use case performs the first migration, not just the design: all nine modules
relocate, the `sys.path` shims are replaced with absolute package imports, the
toolkit-root calculation behind `refuse_inside_toolkit()` is relocated
deliberately rather than incidentally, and Liftoff-tuned constants move out of
the shared analysis into per-sim calibration. The pipeline's output must be
identical afterwards, proven against a saved replay.

## Acceptance Criteria

1. An ADR exists at an agreed path, numbered, with Status / Context / Decision /
   Consequences sections; its Status is `Accepted`.
2. The ADR records each decision **with the alternative it beat and why**: the
   `src/` layout, the metadata-only `pyproject.toml`, dataclasses over JSON
   Schema, the per-sim folder contract, the invocation model, the toolkit-root
   relocation, and where per-sim calibration lives.
3. The tree is `src/fpv_review/{sources/<sim>/, common/}`, with `SKILL.md`
   remaining at the repository root; `common/` contains at least the schemas
   (dataclasses), the report templates and the sim-agnostic analysis.
4. All nine current modules are relocated; nothing executable remains in
   `scripts/`; the ADR's mapping table matches what is actually on disk, rename
   for rename.
5. No `sys.path.insert` remains anywhere in the codebase; every cross-module
   import is an absolute package import.
6. `pyproject.toml` exists with `requires-python = ">=3.9"` and
   `dependencies = []`. UnityPy appears only as an optional extra, never as a
   runtime requirement.
7. The documented invocation works from a bare clone with nothing installed, on
   Windows and on POSIX, and the ADR states which mechanism was chosen and why.
8. `common/` defines dataclasses for every inter-stage artifact — world/track
   geometry, flight state series (position, attitude, velocity, stick
   positions), and lap/session data — with each field carrying its unit and
   coordinate frame.
9. A capabilities declaration is specified and implemented; Liftoff's is
   populated. A stage that receives a declared gap names it in the report and
   never infers the value.
10. Every module under `common/` is free of imports from `sources/*` —
    verifiable by grep.
11. Per-sim calibration (stall thresholds and any other Liftoff-tuned constant)
    lives under `sources/liftoff/`; the shared analysis receives them as
    parameters and hardcodes none.
12. `refuse_inside_toolkit()` lives in `common/`, the toolkit root is resolved
    explicitly rather than by counting `.parent` levels, and an attempted write
    under the toolkit root is still refused after the move — demonstrated, not
    assumed.
13. `.gitignore` covers the new paths; no replay, report, extracted game asset or
    pilot profile can be committed from the new layout.
14. Every command printed in `README.md`, `SKILL.md` and the `scripts/README.md`
    successor is updated and verified to run as printed.
15. A saved replay is processed end to end before and after the migration, and
    the two `analysis.json` outputs are compared field for field. Any difference
    is explained, not waved through.
16. The committed report under `examples/` is byte-identical afterwards, unless a
    difference is explained and accepted.
17. No third-party runtime dependency is introduced.

## Potential Pitfalls & Open Questions

- **Ambiguity** — The exact invocation mechanism under a `src/` layout is not
  settled: working directory set to `<clone>/src` (recommended — `cwd` is on
  `sys.path` for `python -m`, so it behaves identically on Windows and POSIX),
  `PYTHONPATH=src` (bash-only syntax; silently wrong in PowerShell, which is the
  primary environment), or requiring `pip install -e .` (breaks clone-and-go).
  The ADR must settle this.
- **Risk** — The `src/` layout was chosen knowing it costs the one-command
  clone-and-run install. Its whole purpose is to make the package non-importable
  until installed, and this project ships by being the repo. If the invocation
  mechanism is got wrong, the skill breaks for anyone installing it fresh, and
  no test would catch it.
- **Risk** — `TOOLKIT_ROOT` is currently `Path(realpath(__file__)).parent.parent`
  in `liftoff_replay.py`, correct only because the file sits one level below the
  root. The new depth differs, and a wrong value disables the
  `refuse_inside_toolkit()` guard silently rather than loudly.
- **Risk** — This moves every file in the project with no test suite to fall back
  on. Correctness rests entirely on criterion 15 and on reading the diff.
- **Missing input** — No second sim's data has been inspected, so the dataclasses
  are designed against Liftoff plus assumptions, which `PROJECT_BRIEF.md`
  explicitly warns against ("no speculative generalisation ahead of a second real
  sim"). Mitigation: keep the contract minimal and derived strictly from what the
  analysis consumes today.
- **Edge case** — `liftoff_pbs.py` is half sim-specific (it reads Liftoff's
  ratcheting time files) and half generic (PB tracking and snapshot history); it
  likely splits across both trees rather than moving whole.
- **Edge case** — `liftoff_view.py` is sim-agnostic despite its name — it
  consumes geometry and path data, not game files — and needs renaming as it
  moves.
- **Edge case** — Stale `__pycache__/*.pyc` from the old flat layout can mask
  import errors during the move.
- **Assumption** — No stub `velocidrone/` or `uncrashed/` folders are created;
  the required per-sim surface is documented in the ADR instead, since empty
  directories are speculative and git does not track them.
- **Assumption** — `scripts/` disappears entirely, and the content of
  `scripts/README.md` moves into the ADR or a docs successor.

## Original Description

My use case is basically define the ARCHITECTURE and an ADR about it. The ide is to have this sort of format:
 - SKILL.MD
 - sources
 -- liftoff
 --- map_geometry_generator.py (the script that generates the geometry when passing it coordinates or whatever, to render the map later)
 --- other script sliftoff specific, like the ones to extract shapes, read flight paths from savegames etc
 -- velocidrone (example)
 --- map_geometry_generator.py (example, all implementations should have it)
 -- uncrashed (example)
 --- map_geometry_generator.py
 - common
 -- common scripts, that consume geometry files plust path files
 -- templates
 -- schemas (for data transfer between stages)

Or something similar. Feel free to advise

## Clarifications

- Q: What does this use case actually produce — ADR only, ADR plus schemas and an
  empty skeleton, or ADR plus schemas plus moving the Liftoff code?
  A: ADR + schemas + move the Liftoff code too.

- Q: Where does the new tree live — repo root beside `SKILL.md`, or under the
  existing `scripts/`?
  A: Repo root.

- Q: How do modules import each other once they are no longer in one flat folder?
  (Today: `sys.path.insert` plus flat `import liftoff_replay as LR`.)
  A: "I want this to be as much as a normal python project as possible."

- Q: Schemas — JSON Schema files with a hand-rolled stdlib validator, JSON Schema
  as unenforced documentation, or Python dataclasses?
  A: Python dataclasses as the schema.

- Q: Package namespacing — top-level `sources/` and `common/` squat common import
  names. Wrap them in a package, use a full `src/` layout, or keep the original
  sketch?
  A: `src/fpv_review/` — full src layout, accepted knowing it costs the
  one-command clone-and-run install and requires the invocation mechanism to be
  settled explicitly.

- Q: Add a `pyproject.toml`? (Runtime behaviour is identical either way; this is
  purely whether the metadata file exists.)
  A: Yes — metadata only, zero dependencies.

- Q: With no test suite, verification means running a real replay before and
  after. What is available?
  A: Replays are already saved, so a genuine before/after `analysis.json`
  comparison is possible (criterion 15).
