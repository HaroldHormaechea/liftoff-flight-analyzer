---
schema_version: 1
project:
  name: liftoff-flight-analyzer
  maturity_target: mvp
stack:
  languages: [python, javascript, html, css, svg, markdown]
  frameworks: []
  runtimes: [desktop, browser]
  versions: {python: ">=3.9", unitypy: "optional; only for liftoff_scene.py and liftoff_props.py"}
  data_stores: ["filesystem (replay archive, generated reports)", "json files (pb history, track index, scene/prop geometry caches)"]
build:
  tool: none
  commands: {test: null, lint: null, format: null}
paths:
  production: ["scripts/**", "SKILL.md"]
  test: []
  api_boundary: []
test:
  framework: none
  levels: []
  coverage_target: none
profiles: []
deployment:
  provider: local
  iac: none
  environments: [local]
vcs:
  enabled: true
  already_initialized: true
  default_branch: "main"
  remote: "https://github.com/HaroldHormaechea/liftoff-flight-analyzer.git"
---

# Project Brief

> Reverse-derived on 2026-08-30 from the existing, working codebase — this
> project was not scaffolded from this brief. Everything recorded below was read
> off `README.md`, `SKILL.md`, `scripts/README.md` and the nine modules in
> `scripts/`, except the items listed under **Open questions**, which are
> inferences or proposals awaiting the author's decision. No source file was
> modified in producing this brief.

## Open questions

These were derived from the code rather than stated by the author. All six were
settled by the author on 2026-08-30 and are recorded below as decisions; each is
also reflected in the section it belongs to. Nothing in this brief is an
unconfirmed inference.

**Settled 2026-08-30.**

1. **Maturity target — `mvp`, confirmed.** Complete feature surface and a
   published worked example, but no automated tests and a single-sim scope. Not
   claimed as production.
2. **Tests, linting and CI — deliberately none.** The current absence is
   intentional, not an oversight, and is not to be "fixed" by a dev-team run.
   Introducing `pytest` or `ruff` would make this project depend on something,
   which is the one thing it has chosen not to do. Verification of a change is
   running the real pipeline against a real replay and reading the report. See
   **Quality & Standards → Testing**.
3. **Other sims — a planned restructure, not a non-goal.** The author intends to
   support sims beyond Liftoff by separating sim-specific logic from the
   sim-agnostic analysis, with a common intermediate data format between them.
   This is a direction the architecture should move toward, not something to
   design against. See **Architecture → Planned direction**.
4. **Accessibility — WCAG AA adopted.** Now a binding standard for the generated
   report, not an aspiration. See **Quality & Standards → Accessibility**.

5. **Commercial intent — none, confirmed.** No paid tier, hosted service or
   donations, now or planned. The project stays free and MIT-licensed. See
   **Monetization**.
6. **Outside contributions — accepted.** The project is open to contributions
   from others. No `CONTRIBUTING.md`, issue template or code of conduct exists
   yet; writing them is worthwhile but is not a precondition. See
   **Monetization → Contributions**.

## Overview

**Name.** liftoff-flight-analyzer — distributed and invoked as the Claude Code
skill `fpv-review`.

**Problem.** A pilot can feel that a lap went badly but cannot tell *why*:
whether time was lost by turning too late, by overshooting a gate and doubling
back, or by yawing the quad around instead of banking it. The decisive evidence
is in the stick inputs, and those are invisible both in the goggles and in the
replay.

**Users.**

1. *The pilot who owns this repo* — a Liftoff player who wants a measured
   debrief after a session rather than an impression, and who wants to know
   whether the last fix actually landed. Primary and, today, the only confirmed
   user.
2. *Other Liftoff pilots using Claude Code* — install by cloning into
   `~/.claude/skills/fpv-review` and ask for a review in natural language. No
   Python knowledge assumed; they never invoke a script directly.
3. *A language model picking the work back up* — an explicit consumer. The
   pipeline emits `analysis.json` as a deliberate superset of the report so a
   later reader never re-derives from the CSV and never guesses which threshold
   produced a number.

**Value proposition.** *More capable and more private than the alternatives.*
Watching a replay back is guesswork; a telemetry dashboard is a wall of numbers.
This names the cause of each time loss — overrun, corner, hesitation or crash —
and separates the mistakes that belong to the pilot from the ones the track
asked for, then reduces the session to one fix and one drill. It runs entirely
on the local machine against files the game already wrote, with nothing running
during the flight.

**Maturity target.** `mvp` — usable by early adopters beyond the author. The
feature surface is complete and a real generated report is committed as a worked
example, but there is no automated test suite, no CI and a single-sim scope, so
it is not claimed as production. *Confirmed by the author, 2026-08-30.*

**In scope.**

1. Decode Liftoff saved in-game replay XML (10 Hz position, attitude, stick
   positions, track/race IDs, drone configuration, lap times) to CSV, archiving
   before decoding because the game overwrites replay filenames.
2. Measure flight geometry — sideslip, tilt, turn radius, per-corner throttle
   delta, yaw-only time — and locate every stall, classifying each as overrun,
   corner or hesitation via a deterministic decision table.
3. Extract track, race and collision geometry from the game's own Unity bundles
   so gate positions and world obstacles can be compared against the flown path
   in a shared coordinate frame.
4. Emit an illustrated report — `report.md` plus a double-clickable
   `report.html` with hand-drawn SVG figures, SMIL animations and an in-page 3D
   incident playback of every crash and stall — plus `analysis.json` as the full
   record.
5. Track personal bests per track across sessions, snapshotting the game's
   ratcheting time files before they are overwritten.
6. Coach: drive the whole flow from a natural-language request via the
   `fpv-review` skill, written against a persistent pilot profile so each
   debrief is measured against the last one.

**Non-goals.**

1. **Screen recording, HUD scraping or OCR.** This path existed and was removed:
   71–79% OCR read rate and stick positions estimated from a 170 px overlay,
   versus exact values at 10 Hz from the replay. A flight with no saved replay
   is simply not analysable.
2. **Writing the Debrief automatically.** `## Debrief` is left empty by
   `fpv_report.py` on purpose — a generated sentence can say a number is large,
   but only a reader who knows what the pilot was told last session can tell
   coaching from nagging.
3. **Third-party dependencies on the analysis path.** No matplotlib, Pillow,
   ffmpeg, numpy or OpenCV. Figures are hand-written SVG and animations are
   SMIL.
4. **Redistributing game assets.** Extracted track XMLs and geometry caches are
   gitignored, never committed, never hand-edited.
5. **Storing personal data in the toolkit.** Pilot profiles, replays, reports
   and history belong to the user's own project;
   `refuse_inside_toolkit()` hard-stops writes under a link-mounted toolkit
   root.

**Deferred — planned, not in scope today.**

1. **Sims other than Liftoff.** Uncrashed, VelociDrone and DCL expose different
   data, or none. The author intends to support them eventually, and the route
   is a structural one: sim-specific ingestion isolated per sim, a common
   intermediate data format between ingestion and analysis, and the analysis,
   scoring and report layers written against that format rather than against
   Liftoff's replay XML. Today only the Liftoff ingestion exists. The
   restructure is described in **Architecture → Planned direction**; until it
   lands, nothing should be generalised speculatively.

**Success criteria.**

1. A pilot asks "review my last flight" in plain language and gets back an
   illustrated report without naming a file, a track or a script.
2. Every stall and crash carries a cause, not just a timestamp, and the cause is
   reproducible — same replay in, same verdict out, with every threshold
   exposed as a CLI flag.
3. The numbers are trustworthy at the edges: stale track geometry fails loudly
   via `--check` rather than producing confident wrong answers, and missing
   collision geometry degrades to a path-only recording that says what it is
   missing.
4. Session-over-session, the debrief can state whether the previously prescribed
   fix landed, measured rather than guessed.
5. A clone runs immediately on a machine with only Python installed.

## Monetization

**Commercial intent.** None (author, 2026-08-30). Not merely absent today —
there is no intent to monetize this project at all, so proposals that assume a
paid tier, a hosted service or a donations funnel are out of scope by
definition.

**Model.** `none` — open-source personal tool, published publicly so other
Liftoff pilots can use it. No paid tier, no hosted service, no donations link
present in the repository today.

**License.** MIT (`LICENSE`, © 2026 Harold Hormaechea). Permissive, consistent
with distribution-as-clone: the user copies the repository into their own
`~/.claude/skills/` folder, so anything more restrictive would be friction
without purpose.

**Target market.**

- Liftoff: FPV Drone Racing players who already use Claude Code.
- Sim racers who want measured coaching rather than a telemetry dump.
- Secondarily, developers interested in the reverse-engineered Liftoff replay
  format and the dependency-free Unity bundle reader, both of which are
  documented in the repository as reusable knowledge.

**Tiers.** None. The whole tool is the free tier.

**Constraints.**

- **Game assets must not be redistributed.** Track XMLs, scene caches and prop
  tables are extracted from the user's own Liftoff install at runtime and are
  gitignored. Only the extractor is versioned.
- **No personal data in the repository.** Pilot profiles, replays, reports and
  PB history are gitignored *and* enforced at runtime by
  `refuse_inside_toolkit()`, on the reasoning that an ignore rule is one
  `git add -f` away from being wrong.
- **No telemetry, analytics or network egress.** The tool is entirely local; the
  only socket in the codebase is the loopback UDP receiver for Liftoff's own
  telemetry feed.
- Contributions from outside the author are **welcome** (author, 2026-08-30).
  The scaffolding for them does not exist yet — no `CONTRIBUTING.md`, issue
  template or code of conduct — so adding it is a legitimate piece of work
  rather than an open question. Whatever gets written has to state the two
  constraints a newcomer would otherwise breach: the analysis path takes no
  third-party dependency, and no game asset, replay or pilot profile is ever
  committed. It should also say how a change is verified here, since there is
  no test suite to point at — see **Quality & Standards → Testing**.

## Technologies

**Constraints.**

1. **The analysis path must stay standard-library only.** This is a design
   value, not an accident: "nothing to install, nothing to pin, portable as a
   folder copy". It is also a reliability argument — the moment the extractor is
   needed most (the game just patched and the gates are stale) is the worst
   possible moment to discover a missing dependency.
2. **Exactly one optional third-party dependency is tolerated, and only at the
   edge.** `UnityPy` is imported by `liftoff_scene.py` and `liftoff_props.py`
   alone, guarded by a local `import` inside a function so the module still
   loads without it. Those scripts run once per environment per game patch and
   emit plain JSON, so every consumer of the cache needs nothing.
3. **No rendering or numerics libraries.** No matplotlib, Pillow, numpy, OpenCV
   or ffmpeg. Figures are hand-written SVG text and animations are SMIL, so
   output is diffable, scales to any size, and themes itself via
   `prefers-color-scheme`.
4. **Output must render everywhere without JavaScript being required.** Progressive
   enhancement is mandatory: tabs and expand-all are gated on a `.js` class, and
   `@media print` restores every panel.

**Team familiarity.** Single author, Python.

**Runtimes.**

- *Desktop / CLI* — Python 3.9+ on the local machine. Windows 11 is the primary
  environment because Liftoff is a Windows game; paths are handled through
  `pathlib` and the Steam lookup includes a Windows registry path, so the code is
  not gratuitously POSIX- or Windows-only, but Windows is the tested target.
- *Browser* — the generated `report.html` is a self-contained page (SVG + SMIL +
  vanilla JS for tabs, expand-all and the 3D incident viewer). No framework, no
  build step, no bundler.
- *Claude Code agent host* — `SKILL.md` is the orchestration layer, executed by
  Claude Code as an installed skill.

**Languages.** Python (all tooling); HTML/CSS/SVG and vanilla JavaScript
(generated report output, emitted as strings from `fpv_report.py` and
`liftoff_view.py`); Markdown (`SKILL.md`, `report.md`).

**Frameworks.** None, deliberately. The only "framework" in the sense of an
external contract is the Claude Code skill format (YAML frontmatter with `name`
and `description`, plus procedural Markdown).

**Data stores.**

| store | purpose |
|---|---|
| Filesystem — `replays/` | timestamped archive of decoded replays; the durable record, because the game's `Recordings/` folder is scratch space that overwrites itself |
| Filesystem — `reports/<replay-stem>/` | generated deliverables: `report.md`, `report.html`, `analysis.json`, `flight.csv`, `assets/*.svg` |
| JSON — `data/liftoff_history.json` | personal-best snapshots per track with history, because the game ratchets and overwrites its own time files |
| JSON + XML — `trackdata/` | extracted track/race geometry plus `index.json`, the join table from a replay's `localID` GUIDs to a track |
| JSON — scene cache and prop table | environment collision geometry and per-prop collider shapes, built once per environment per game patch |

No database engine of any kind. Every store is a plain file, gitignored, and
regenerable except the replay archive and the PB history.

**Auth strategy.** None, and none needed — a single-user local tool with no
server, no accounts and no network service. The only access-control mechanism is
the `refuse_inside_toolkit()` guard, which is a data-placement boundary rather
than authentication.

**External services.**

- **Liftoff: FPV Drone Racing** (LuGus Studios) — the sole data source. Read via
  its saved replay XML, its `RaceTimes`/`LapTimes` XML, its `Player.log` content
  catalogue, and its Unity asset bundles.
- **Steam** — used only to locate the Liftoff install, via the Windows registry
  and `libraryfolders.vdf`; overridable with `--game-dir` or `$LIFTOFF_DIR`.
- **Liftoff UDP telemetry endpoint** (`127.0.0.1:9001`, configured by the game's
  `TelemetryConfiguration.json`) — dormant but deliberately retained; the only
  source of gyro, battery and motor RPM.

No hosted API, no cloud service, no network egress beyond loopback.

**AI/ML dependency.** No model is embedded, trained or called by the code. The
*product*, however, is an LLM-driven workflow: `SKILL.md` directs a Claude Code
agent to run the scripts, read the figures and write the `## Debrief` section
that `fpv_report.py` deliberately leaves empty. The Python layer is fully
deterministic and usable standalone; the model supplies judgement, not numbers.

**Build tooling.** None — there is no `pyproject.toml`, `requirements.txt`,
`setup.py`, `Makefile` or lockfile, and this is intentional per constraint 1.
Scripts are invoked directly with `python <script>.py`. Consequently
`build.commands.test`, `.lint` and `.format` are `null` in the frontmatter
rather than guessed; see **Quality Standards**.

## Architecture

**Platforms.** CLI (Python scripts, Windows-primary) + browser (the generated
self-contained `report.html`) + Claude Code skill host (`SKILL.md`). No server,
no mobile, no packaged desktop binary.

**Service shape.** *Modular monolith, expressed as a set of cooperating CLI
modules.* Nine single-purpose Python modules in `scripts/`, each independently
runnable with its own `argparse` CLI and `main()`, and each also importable as a
library. `fpv_report.py` is the composition root: it imports the others rather
than shelling out to them or re-deriving their results.

The load-bearing rule is **embed, never duplicate**. `fpv_report.py` calls
`analyze_flight.build_parser()` for the thresholds and `analyze_flight.analyse()`
for the numbers, so a figure and a table can never disagree and a threshold added
once reaches both. Likewise the 3D viewer has exactly one implementation —
`liftoff_view.build()` cuts the window and `VIEWER_JS` draws it — used by both
the standalone page and the in-report recordings, so there is one projection, one
playback loop, and one place to fix either.

**Components.**

| component | runtime | responsibility |
|---|---|---|
| `SKILL.md` | Claude Code agent | Orchestration and coaching policy. Pilot-profile lookup, mandatory track-data check, report build, figure reading, Debrief authorship, persistence. The only component that exercises judgement. |
| `scripts/fpv_report.py` | Python CLI | Composition root. Archives, decodes, analyses, draws every figure and animation, builds recordings, emits `report.md` / `report.html` / `analysis.json`, opens the browser. ~2100 lines; the largest module by far. |
| `scripts/analyze_flight.py` | Python CLI + library | Flight geometry and verdicts: sideslip, tilt, turn radius, corner detection, yaw-only time, stall detection and the overrun/corner/hesitation decision table. The measurement authority. |
| `scripts/liftoff_replay.py` | Python CLI + library | Locates and archives the volatile in-game replay, decodes `statesByte` to CSV. Also owns `refuse_inside_toolkit()`, imported by the other modules purely for that guard. |
| `scripts/liftoff_tracks.py` | Python CLI + library | Finds the Liftoff install, extracts track and race XML from Unity bundles, writes `index.json`, answers `--for-replay`, `--gates`, `--check`. |
| `scripts/liftoff_scene.py` | Python CLI + library | Static environment collision geometry from a scene bundle, and the cull to one incident. Needs `UnityPy`. |
| `scripts/liftoff_props.py` | Python CLI + library | Collider shapes for track props, in each prop's own frame. Needs `UnityPy`. |
| `scripts/liftoff_view.py` | Python CLI + library | The 3D incident view: geometry assembly, path, orbit, scrub. Standalone page and embedded recordings share it. |
| `scripts/liftoff_pbs.py` | Python CLI | Snapshots the game's ratcheting PB files to `data/liftoff_history.json`. The only module importing nothing else in the project. |

**Communication.** In-process Python imports only. No HTTP, no RPC, no queue, no
IPC. The dependency graph is acyclic and shallow:

```
              fpv_report.py  (composition root)
              /     |      \        \
   analyze_flight  liftoff_replay  liftoff_tracks  liftoff_view
                        ^                ^            /   |
                        |                |     liftoff_scene (UnityPy)
                        +----------------+            |
                                          liftoff_props (UnityPy)
   liftoff_pbs.py       (standalone)
   liftoff_telemetry.py (standalone, dormant)
```

`liftoff_replay` is the leaf everything depends on — including
`liftoff_tracks.py`, which imports it for `refuse_inside_toolkit()` *and nothing
else*, a dependency the source annotates explicitly.

The one external protocol is **UDP on loopback** (`liftoff_telemetry.py`
receiving `127.0.0.1:9001` at 100 Hz), dormant by default.

**Async workloads.** None. Every run is synchronous, batch, and terminates.
There is no scheduler, daemon, worker or queue. The single long-running mode is
`liftoff_telemetry.py -o flight.csv`, which records until Ctrl+C, and it is not
part of the normal flow. Caching is manual and explicit — the scene and prop
caches are built by the user when an environment is first flown, not lazily
populated behind a request.

**Integrations.** The Liftoff game install (Unity asset bundles, replay XML,
race/lap time XML, `Player.log`); the Steam client (install discovery via
registry and `libraryfolders.vdf`); the OS default browser (`webbrowser.open` on
the finished report); Liftoff's UDP telemetry endpoint.

**Data flow.**

1. The pilot saves a replay in-game. Liftoff writes
   `<LocalLow>/LuGus Studios/Liftoff/Recordings/<GameMode>/<name>.xml`, naming it
   after track and total time — so repeated attempts collide and overwrite.
2. `liftoff_replay.py` **copies to a timestamped name first, then decodes the
   copy.** The archive is the durable record; `Recordings/` is scratch. Decoding
   base64-unpacks `statesByte` into fixed 48-byte records (12 little-endian
   floats: position, attitude quaternion, throttle/yaw/pitch/roll, timestamp) at
   10 Hz, emitting `flight.csv`, with `lapTimes` and `lapStartIndices` from the
   metadata giving lap boundaries with no guesswork.
3. `liftoff_tracks.py --check` gates the whole run: bundle filenames are content
   hashes, so it compares the recorded fingerprint and Steam build id against
   what is installed and **fails rather than analysing against stale gates**.
4. `analyze_flight.py` measures the flight. Sample rate is the *median* interval,
   never the first difference, because Liftoff's timestamps are irregular
   (0.003–0.197 s observed) and a first-difference estimate silently scaled every
   duration by up to 1.9×. It finds corners, stalls, and classifies each stall.
5. Geometry, best-effort: the scene cache supplies the static world, the prop
   table supplies each placed item's collider shape, and the track XML supplies
   where each item sits and its yaw. All three are needed — track props are
   instantiated at runtime and are *not* in the scene bundle, so scene-only
   geometry shows a crash happening in clear air.
6. `fpv_report.py` composes: figures as hand-written SVG, per-lap animations as
   SMIL, crash and stall recordings via `liftoff_view.build()` with pooled,
   index-referenced geometry (incidents cluster, so neighbouring impacts cull
   nearly the same geometry twice). It writes `reports/<replay-stem>/` and opens
   `report.html`.
7. `report.md` is the argument; `analysis.json` is the record — a deliberate
   superset carrying every statistic, every threshold that produced it, the
   measured sample rate, the lap boundaries, and a `not_in_report` list naming
   what was omitted and where it lives instead.
8. The agent reads the figures and writes `## Debrief` by hand.
   `existing_debrief()` carries it forward across regenerations, stopping at the
   next `## ` heading so the `### Recommendations` subsection travels with it.
9. `liftoff_pbs.py --save` snapshots the personal bests before the game
   overwrites them.

**Trust boundaries.**

- **Untrusted-ish input.** Replay XML and Unity bundles come from the local game
  install — not hostile, but structurally unstable across patches. The system
  defends by *failing loudly* (`--check`) rather than degrading silently, and by
  degrading *visibly* where partial answers are still useful (a recording without
  cached geometry still draws path, attitude and impacts, and prints what is
  missing in its own footer).
- **Sensitive data: the pilot profile.** It holds personal notes and standing
  diagnoses. It is found via `$LIFTOFF_PILOT` or `liftoff-pilot.md` in the
  working directory, is gitignored, and must live in the *user's* project rather
  than the toolkit. This is enforced at runtime, not just by convention:
  `refuse_inside_toolkit()` hard-stops any write of reports, replays or history
  under the toolkit root — but **only when the toolkit is mounted via a link**,
  so it never obstructs the ordinary clone-and-run case.
- **Never leaves the machine.** Everything. There is no outbound network path;
  the only socket binds loopback.
- **Never enters the repository.** Extracted game assets (licensing) and pilot
  data (privacy).

**Multi-tenancy.** Not applicable — single user, single machine, no shared
state. The nearest analogue is the pilot profile, which makes the tool
per-person by pointing it at a different profile and data root.

**Planned direction — multi-sim structure.** *Decided by the author,
2026-08-30. Not built; nothing below describes the code as it stands today.*

The project is intended to grow beyond Liftoff, and the author's chosen route is
structural separation rather than per-sim branching inside the existing modules:

1. **Sim-specific logic lives apart from sim-agnostic logic.** Everything that
   knows about a particular sim's file formats, coordinate conventions, asset
   bundles and lap semantics is confined to that sim's own ingestion layer.
   Today that is `liftoff_replay.py`, `liftoff_tracks.py`, `liftoff_scene.py`,
   `liftoff_props.py` and `liftoff_telemetry.py` — already the natural seam,
   since they are the only modules that parse game-owned bytes.
2. **A common intermediate data format sits between ingestion and analysis, in
   a shared folder.** Ingestion emits it; nothing downstream reads a sim's
   native format. It must carry what the analysis actually consumes — a
   time-indexed state series (position, attitude, velocity, stick positions),
   track and gate geometry, collision geometry where available, lap boundaries
   and times, and a per-field statement of what this sim does *not* provide.
3. **Analysis, scoring and reporting are written against that format only.**
   `analyze_flight.py`, `fpv_report.py`, `liftoff_view.py` and `liftoff_pbs.py`
   become sim-agnostic consumers; a new sim is added by writing one ingestion
   module plus a declaration of its gaps, not by touching the analysis.
4. **Degradation is explicit, not silent.** A sim that exposes no stick
   positions must produce a report that says which findings are unavailable —
   never one that infers them. This is the same rule the project already applies
   to missing collision geometry.

Constraints on getting there: no speculative generalisation ahead of a second
real sim (the format should be designed against Liftoff's data plus one
concrete other sim's actual capabilities, not against a hypothetical one); no
new third-party dependency; the module-is-both-CLI-and-library convention holds
for the new layout; and the naming will need revisiting, since a `liftoff_`
prefix on a sim-agnostic module would be actively misleading.

**Path scopes for the dev-team.** `paths.production` is `scripts/**` plus the
root `SKILL.md`, since the skill definition is a first-class deliverable and not
documentation. `README.md`, `scripts/README.md`, `examples/**`, `LICENSE` and the
banner images are deliberately outside the production scope: they are
human-authored or committed artifacts and should not be rewritten as a side
effect of a code change. `paths.test` is empty — see **Quality Standards**.

## Quality & Standards

> **Current state, verified 2026-08-30.** There is no test directory, no test
> framework, no linter config, no formatter config and no CI — `.github/` does
> not exist. **The author confirmed on 2026-08-30 that this is deliberate and
> stays that way**, so it is the standard, not a gap: do not add a test suite,
> a linter or a CI workflow as a side effect of another change. Accessibility
> (WCAG AA) is the one standard here that *is* binding and measurable.

**Style guide.** No enforced style guide. Observed house style, applied
consistently across all nine modules and worth preserving:

- Standard library only on the analysis path; a third-party import is a design
  decision, not a convenience.
- Every module is both a CLI (`build_parser()` / `main()`) and an importable
  library.
- Short, lowercase function names; module-level functions over classes (only
  three classes exist across 5,950 lines: `Proj`, `Strip`, `Pool`).
- Cross-module imports are aliased to short capitals (`AF`, `LR`, `LT`, `LV`,
  `LS`).
- **Rationale is written down at the point of the decision.** Docstrings and the
  two READMEs record *why* a choice was made and what the rejected alternative
  broke — e.g. why `animateMotion` is not used, why sample rate is a median, why
  the `isCrashed` flag is ignored. This is the project's strongest quality
  mechanism and should not be traded away for terseness.
- Rejected designs are named as rejected, so they are not re-added by a later
  contributor (no per-lap track figure, no whole-flight animation, no HUD
  scraping).

**Linters / formatters.** None, by decision (author, 2026-08-30). The house
style below is upheld by review against the existing modules, not by a tool. If
this is ever revisited, `ruff` run as a developer-side tool (`ruffx`/`uvx`)
rather than a committed dependency is the only form that would not breach
constraint 1 in **Technologies** — but it is not planned.

**Testing.** *No automated tests, by decision (author, 2026-08-30).*

- *Levels:* none automated.
- *Coverage target:* none.
- *Framework:* none. `paths.test` stays `[]` and `build.commands.test` stays
  `null` — they describe reality, and there is nothing pending to fill them in.

The reasoning is the project's own constraint: a test framework would be this
repository's first mandatory dependency, and "nothing to install, nothing to
pin, portable as a folder copy" is a feature the tool sells, not an accident.
`pytest` and `ruff` are both ruled out on that basis; standard-library
`unittest` is not ruled out in principle, but is not planned either.

**How a change is verified instead.** Running the real pipeline end to end
against a real replay and reading what comes out:

```
python liftoff_tracks.py --check     # geometry present and current?
python fpv_report.py --latest        # full run: decode, analyse, draw, write
```

The committed example report under `examples/` is the reference: a change that
alters it should alter it in a way the author can point at and explain, and a
change that should not have touched it must leave it identical. Where a fault's
classification or a threshold is touched, re-run the affected replay and compare
the verdict, not just the exit code. This is the standard the dev-team is held
to — "the tests pass" is not available here and must not be claimed.

The list below is kept because it records where the real risk sits, and is worth
reading before touching any of it — not as a backlog of tests to write.

The highest-value first tests, given what the code actually does:

1. **Stall classification** — the overrun/corner/hesitation decision table is
   pure logic over sampled geometry and is the project's core claim. Golden-file
   tests against the committed example flight would pin it.
2. **Replay decoding** — the 48-byte record layout, base64 unpacking, and the
   median sample-rate calculation (a regression here silently scaled every
   duration by up to 1.9× once already).
3. **`analysis.json` as a contract** — it is explicitly written for a later
   machine reader, which makes it a public interface deserving a schema check.
4. **`existing_debrief()`** — it must carry hand-written prose across
   regenerations and stop at the next `## ` heading; losing a pilot's debrief is
   unrecoverable data loss.

**Quality mechanisms that already exist** (and substitute for tests today —
these are real and should be credited rather than replaced):

- **Empirical calibration.** Stall thresholds were fixed against a reference
  flight (Rustline 2-lap, 2026-08-26) where the two populations separated
  cleanly — overruns at 0.3–0.4 m retrace with 172–178° reversal versus 7.4 m+
  and ≤104° for everything else — and each default sits in the gap between them.
- **Cross-source validation.** The replay axis order was confirmed, not guessed,
  by capturing one flight simultaneously as a replay and as a 100 Hz UDP
  telemetry stream: across 1,575 moving samples with exact position matches, the
  yaw/pitch/roll channels agreed to within 0.04.
- **Byte-identical verification.** The hand-written UnityFS reader's output was
  checked against UnityPy across all 184 assets.
- **Determinism by construction.** Every threshold is a CLI flag; measurement
  windows are clamped to neighbouring stalls so an answer never depends on how
  far apart two events happened to fall; where clamping leaves too few samples
  the field prints `-` rather than inventing a number.
- **Fail-loud staleness detection.** `liftoff_tracks.py --check` exits non-zero
  when the bundle fingerprint or Steam build id has moved, on the explicit
  principle that stale gates are worse than no gates.
- **A committed worked example.** `examples/20260828-140705_BardwellsYard_Race_3lap/`
  holds one unedited real report and functions as a de facto golden output.

**Security.** No dependency scanning, and little to scan — the analysis path has
no dependencies and `UnityPy` is optional and unpinned. No secrets exist: no
credentials, tokens, accounts or network egress. The live security controls are
privacy controls: the gitignore of `liftoff-pilot.md`, `replays/`, `reports/`,
`data/` and `trackdata/`, and the `refuse_inside_toolkit()` runtime guard which
exists precisely because "an ignore rule is one `git add -f` away from being
wrong". No threat-model document, and none proposed — the attack surface is a
local read-only tool with no untrusted input path.

*One residual risk worth naming:* the generated `report.html` embeds values
derived from game data into HTML and JavaScript. `esc()` exists for escaping, so
the concern is already recognised; a regression there would be a
self-inflicted-only injection, but it is the single place where quoting matters.

**Accessibility — WCAG AA (binding).** Adopted by the author on 2026-08-30 as a
standard for the generated report, not an aspiration: a change that regresses
any of the following is a defect, and new report UI is held to AA (contrast,
keyboard reachability, non-colour-dependent meaning) on the same terms. The
existing behaviour, all of which must be preserved:

- The speed ramp is red → amber → teal, **deliberately not red → green**, so it
  stays separable under common colour-vision deficiencies and both ends hold
  contrast on either background.
- One SVG file works on light and dark backgrounds via CSS custom properties
  inside a `prefers-color-scheme` query.
- Tabs implement `role="tablist"` with arrow-key, Home and End navigation.
- Everything JavaScript-driven is gated on a `.js` class, so with scripting off
  the page degrades to a single scroll with nothing unreachable, and
  `@media print` restores every panel.
- Where SMIL does not play, every animation still reads as a static picture
  because the line and annotations are drawn underneath it.

*Verification:* by inspection against the AA criteria, since there is no
automated checker in the toolchain — contrast ratios on both
`prefers-color-scheme` branches, keyboard-only traversal of every tab and
control, and a scripting-off read of the page. Any finding that colour alone
carries meaning is a defect.

**Performance budgets.** No formal budgets. Observed and asserted in the
documentation: full track extraction (184 assets) ≈ 5 seconds; animations capped
at `--anim-max` (default 40 s) with the speed-up factor printed on the figure;
frame counts decimated via `decimate()` to bound SVG size; recording geometry
pooled and referenced by index because clustered incidents would otherwise cull
near-identical geometry repeatedly. The real budget is implicit: a review must
feel interactive inside a conversation.

**Documentation.** README-plus, and unusually thorough for the size: a
pilot-facing root `README.md`, a 350-line engineering `scripts/README.md` that
doubles as design-rationale documentation, a 17 KB procedural `SKILL.md`, and a
committed example report. No ADR directory — the rationale lives inline in the
READMEs and docstrings instead, which is a legitimate choice at this size. *If
the project grows, ADRs would be the natural next step;* the material already
exists in prose.

**Observability.** Stdout only, and appropriately so for a local batch CLI. No
logging framework, metrics or tracing, and none warranted. The relevant
observability is in the output artifacts: `analysis.json` carries the thresholds
that produced each number and a `not_in_report` list, and a degraded recording
prints what geometry was missing in its own footer.

## Profiles

None

*No profile in the session workspace applies: `profile-java-database-access`,
`profile-java-server-architecture` and `profile-java-call-graph-tool` are
Java-specific, and `profile-aws-deployment` is irrelevant to a local,
cloud-free tool.*

## Deployment

There is no server, so "production" here means **the end user's machine**. The
whole deployment story is a clone.

### Production (i.e. distribution)

**Hosting.** The user's own Windows PC — the same machine that runs Liftoff.
Nothing is hosted. Install is:

```bash
git clone https://github.com/HaroldHormaechea/liftoff-flight-analyzer \
  ~/.claude/skills/fpv-review
```

Claude Code discovers `SKILL.md` in that folder and the skill becomes callable.
This is why the standard-library constraint matters operationally as well as
aesthetically: the install step is a clone, with no `pip install` following it.

**Cloud provider.** None.

**IaC.** None. Nothing to provision.

**CI/CD.** None, by decision (author, 2026-08-30). `.github/` does not exist;
there is no build, no packaging step and no artifact to publish — the repository
*is* the artifact. With no test suite there is nothing for a workflow to run, so
none is planned.

**Environments.** One: the user's machine. No staging, no preview.

**Secrets.** None exist. No credentials, tokens or accounts anywhere in the
system. The closest analogue is the pilot profile — personal, not secret —
located via `$LIFTOFF_PILOT` or `liftoff-pilot.md` in the working directory,
gitignored, and kept out of the toolkit by `refuse_inside_toolkit()`.

Configuration is by environment variable and CLI flag only:

| variable / flag | purpose |
|---|---|
| `$LIFTOFF_PILOT` | path to the pilot profile |
| `$LIFTOFF_DIR` / `--game-dir` | Liftoff install location, overriding Steam discovery |
| `--track-dir`, `--scenes`, `--props` | cache locations |
| `--archive-dir`, `-o` | replay archive and output paths |

**Observability.** Stdout. See **Quality & Standards**.

**Backup / DR.** No formal policy, but the system is explicitly designed around
the fact that **the game destroys its own data**, and that is the real DR
concern:

- Liftoff names a replay after track and total time, so every abandoned attempt
  on a track lands on the same filename and each save destroys the previous one.
  `liftoff_replay.py` therefore copies to a timestamped archive *before*
  decoding. `replays/` is the durable record; the game's `Recordings/` is
  scratch.
- `raceTimes.xml` and `lapTimes.xml` are overwritten in place, so a beaten time
  is gone. `liftoff_pbs.py --save` snapshots them to
  `data/liftoff_history.json`, and it is the only way to see flights that were
  never saved as replays. **Run it every session.**

Consequently `replays/` and `data/liftoff_history.json` are the only
irreplaceable state on the machine and are the two things a user should back up.
Everything else — `reports/`, `trackdata/`, the scene and prop caches — is
regenerable. All of it is gitignored, so **the repository is not the backup**.

### Development

**Environment.** Native toolchain: a Python 3.9+ interpreter and a checkout.
Nothing else — no virtualenv is required, though `.venv/` is gitignored for
anyone who wants one, and one is needed if `UnityPy` is installed for the two
cache-building scripts. Windows 11 is the primary and tested environment because
Liftoff is a Windows game; paths go through `pathlib`, so the code is not
gratuitously platform-locked, but only Windows is exercised.

**Containerization.** Not used and not appropriate — the tool reads a local game
install, a Windows registry hive and Steam library files, and opens a browser.
Containerizing it would isolate it from everything it needs.

**Hot reload.** Not applicable. The inner loop is: re-run the script; it takes
seconds. `--no-open` exists specifically so a regeneration during iteration does
not spawn a browser tab each time.

**Seed data.** Real replays, archived under `replays/`. The committed example
report in `examples/20260828-140705_BardwellsYard_Race_3lap/` is the shared
reference output — the closest thing to a fixture — and the Rustline 2-lap race
of 2026-08-26 is the calibration flight the stall thresholds were fixed against.
No synthetic generator, no anonymization needed (the data is one person's own
flying).

**Migrations.** Not applicable — no database. Schema change is handled by
regeneration: caches carry a bundle fingerprint and Steam build id, and
`liftoff_tracks.py --check` fails when they disagree with the installed game, so
the "migration" is a rebuild.
