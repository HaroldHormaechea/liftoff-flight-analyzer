---
plan_for: use-cases/01-multi-sim-architecture-adr.md
work_branch: feat/uc-01-multi-sim-architecture-adr
team: session-5db7517b
approved: 2026-08-30
---

# APPROVED IMPLEMENTATION PLAN — UC-01: Multi-sim architecture and ADR

**Verdict: Approve**, after 2 rounds. Round 1 was Request revision (1 Critical, 4 Major, 2 Minor); v2 accepted all of them, extended two beyond what the challenger found, and its new load-bearing claims verified empirically. Three Minor amendments (M1–M3) are folded into the text below.

**What the challenger verified itself, rather than taking on trust:** (1) `python "<clone>\src" <cmd>` works from an unrelated cwd, leaves cwd untouched, and — run through a real Windows junction — leaves `__file__` unresolved so `mounted_via_link()` still returns `True` and the marker-search `toolkit_root()` still returns the real clone root; the safety guard survives the relocation. (2) The precision-parity equivalence, across 310,637 values including adversarial 6-decimal ties and random 64-bit patterns, compared as packed doubles: zero mismatches. (3) All cited line numbers and both positional-index locations.

**Amended by the author, 2026-08-30, after the plan preview.** The precision-parity
quantisation is no longer deferred indefinitely: it is removed in **commit F of this
same run**, once the migration has been verified clean, so the project ends this run
with one precision on the analysis path instead of two. `flight.csv` keeps its
6-decimal serialisation permanently. See §4 (Precision parity), §14 commit F, and
§15's second comparison pass.

All paths relative to the worktree root `C:\dev\liftoff-flight-analyzer-uc-01-multi-sim-architecture-adr`.

## 1. Findings that shape the work

1. **`liftoff_view.py` is NOT sim-agnostic**, contrary to the use case's pitfall list. `props_near()` (`:79-115`) opens the Liftoff track XML via `LT.parse_xml` at `:94`, and `build()` calls it at `:491-493`. A straight move into `common/` breaks criterion 10. Resolved by moving `props_near` to the Liftoff source and passing props into `build()` as data.
2. **The use case's recommended invocation (cwd = `<clone>/src`) would break the project's privacy guarantee** and is rejected. Every output default is bare-relative to cwd — `--archive-dir replays` (`fpv_report.py:1885`), `-o reports` (`:1887`), `--history data/liftoff_history.json` (`:1891`), `--track-dir trackdata` (`:1917`) — and `refuse_inside_toolkit()` returns early unless link-mounted (`liftoff_replay.py:102-103`), so an ordinary clone would silently accumulate replays, reports and PB history inside the toolkit with the guard never firing. `liftoff_pbs.py:121` states the rule in the codebase's own words: paths are "relative to the working directory - never the script's own folder, which may be shared or public".
3. **Per-sim calibration is real and locatable** — ~18 hardcoded defaults in `analyze_flight.build_parser()` (`:395-467`), empirically fixed against one Liftoff flight (Rustline 2-lap, 2026-08-26).
4. **`liftoff_tracks.py` holds a general UnityFS/LZ4 reader** that `liftoff_scene.py:146,151,152,161,170` reaches into by private name (`LT._cstr`, `LT.lz4_block`). It is deliberately **not** hoisted to a shared engine layer — the brief forbids speculative generalisation ahead of a second real sim. Recorded in the ADR as a named deferred decision.
5. **`analyze_flight.py` imports only stdlib today** (argparse, csv, json, math, sys) and has no Liftoff import at any line. Its sole sim coupling is the threshold default *values*. The analysis was already sim-agnostic in its dependencies; this migration makes that structural rather than accidental.

## 2. Target tree

```
<root>\SKILL.md                                    (stays at root, commands rewritten)
<root>\README.md                                   (install section updated)
<root>\pyproject.toml                              NEW
<root>\docs\adr\0001-multi-sim-architecture.md     NEW
<root>\docs\engineering.md                         successor to scripts\README.md
<root>\src\__main__.py                             NEW - front door / dispatcher
<root>\src\fpv_review\__init__.py                  NEW
<root>\src\fpv_review\cli.py                       NEW - the wiring layer
<root>\src\fpv_review\common\...
<root>\src\fpv_review\sources\liftoff\...
<root>\scripts\                                    DELETED entirely
```

**Three-layer import rule — the whole architecture in one sentence:** `common/` may import only `common/` and the stdlib; `sources/<sim>/` may import `common/` and its own siblings, never another sim; `cli.py` is the only module allowed to import both trees, and it does the wiring. Criterion 10 is then satisfied by construction. A string-based plugin registry inside `common/` was considered and rejected precisely because it would pass criterion 10's grep while violating its intent — recorded in the ADR as a rejected alternative.

## 3. Module mapping (goes in the ADR verbatim; criterion 4 requires it to match disk rename for rename)

| from `scripts\` | to |
|---|---|
| `liftoff_replay.py` | `sources\liftoff\replay.py` (decode, archive, discovery, `DEFAULT_ROOT`) — **split**: `mounted_via_link` / toolkit root / `refuse_inside_toolkit` → `common\toolkit.py`; `add_velocity` → `common\kinematics.py`; `COLUMNS` → `common\schema.py` |
| `liftoff_tracks.py` | `sources\liftoff\tracks.py` — **split**: bundle reader (`lz4_block`, `_cstr`, `bundle_payload`, `text_assets`, `_serialized_text_assets`, `normalise_xml`, `_root_tag`, `locate`) → `sources\liftoff\unityfs.py` |
| `liftoff_scene.py` | `sources\liftoff\scene.py` — **split**: `qmul`, `qrot`, `bounds_of`, `contains_point`, `path_inside`, `cull` → `common\geometry.py` |
| `liftoff_props.py` | `sources\liftoff\props.py` (moves whole) |
| `liftoff_view.py` | `common\incident_view.py` (`impacts`, `window_indices`, `build`, `page`, `VIEWER_JS`, `PAGE`) — **split**: `props_near` → `sources\liftoff\map_geometry_generator.py`; `IMPACT_DROP_KMH`, impact debounce, `PROP_NOMINAL` → `sources\liftoff\calibration.py`; `main()` → `cli.py` |
| `analyze_flight.py` | `common\analysis.py` — **split**: the ~18 threshold default *values* → `sources\liftoff\calibration.py` |
| `fpv_report.py` | `common\report.py` — **split**: `main()` + argparse → `cli.py`; `pb_context` (`:840`) → `common\pbs.py`; **`geometry_for` → `sources\liftoff\map_geometry_generator.py`** (added 2026-08-30 during B6 — it calls `LT.for_replay`, so leaving it in `common/` would fail criterion 10; the ADR's table must carry this row) |
| `liftoff_pbs.py` | `sources\liftoff\pbs.py` (`DEFAULT_ROOT`, `track_names`, `parse_times`, `snapshot`) — **split**: `fmt`, `diff_line`, history load/append → `common\pbs.py` |
| `liftoff_telemetry.py` | `sources\liftoff\telemetry.py` (moves whole) |

New with no predecessor: `common\schema.py`, `common\capabilities.py`, `sources\liftoff\{source,capabilities,calibration,map_geometry_generator}.py`, `cli.py`, `src\__main__.py`.

`map_geometry_generator.py` is a **façade**, not a rename of `tracks.py`. "The map" is assembled from tracks (gates/route/blueprints), scene (world colliders) and props (collider shapes); making it the single geometry surface that delegates to all three is what makes the per-sim contract stateable. Renaming `tracks.py` would name a third of the job.

### `main()` destinations (all nine)

`fpv_report`→`cli.py report`; `analyze_flight`→`cli.py analyse` (`build_parser(calibration)` and `default_args(csv_path, calibration)` stay in `common/analysis.py`, now parameterised; the one caller at `fpv_report.py:1952` changes); `liftoff_view`→`cli.py view` — **must not travel with the module**, since `main()` (`:546-591`) calls `LR.parse`, `LR.add_velocity`, `LT.for_replay`, `LS.load_scene` and would fail criterion 10's grep inside `common/`; `liftoff_replay`→`replay`; `liftoff_tracks`→`tracks` (its `cmd_*` handlers travel with `sources/liftoff/tracks.py`); `liftoff_scene`→`scene`; `liftoff_props`→`props`; `liftoff_pbs`→`pbs`; `liftoff_telemetry`→`telemetry`.

**Stated consequence:** nine modules lose runnability-by-path. `build_parser()`/`main()` survive as the house convention; the nine front doors become one. Goes in the ADR's Consequences and in `docs/engineering.md`, whose module table currently prints nine invocations.

## 4. The dataclass boundary (criterion 8) — the core of the change

`common/schema.py` owns `FlightSample`, `FlightSeries`, and **the CSV serialisation of them**. `COLUMNS` moves out of `sources/liftoff/replay.py` into `common/schema.py`, where it is no longer Liftoff's record layout but the serialisation of `FlightSample` — which is what makes it a contract a second sim can read.

**`load_flight` returns a 4-tuple, not the 3 named above** (recorded during D): `(SessionMeta, FlightSeries, LapSet, meta)`. The raw `meta` dict still travels because `report.py` writes it verbatim into `analysis.json`'s `meta` key and `race_name(meta)` reads it — reshaping it would change the **published record**, which criterion 15 would correctly flag. `SessionMeta` is the typed view of the same data and `LapSet` drives the lap-range computation, so both have real consumers. **The ADR must record the 4-tuple**, and `source.py`'s own docstring must describe it — it is the first thing a second-sim implementer reads.

**One genuine behaviour change, on the dormant telemetry path only:** for a CSV lacking `vel_*` columns (a `liftoff_telemetry.py` capture), velocity is derived in `read_csv` and then quantised by `analysis.load`, where before it was derived unrounded. No verification replay reaches it, and **F removes the quantisation**, after which that path matches today exactly. `read_csv` deliberately stays tolerant of missing columns: a strict 17-column reader would silently break `analyse` on telemetry captures, which is documented behaviour exercised by no replay in the set.

**`FlightSeries.sample_dt` is declared but not populated as of D.** `analysis.sample_dt(data)` remains the authority. Unifying them would move where the measured median comes from — a behaviour change in the commit that must stay readable — so it is deferred. In E it must either be populated from the *existing* implementation (plumbing only, one function and two callers, nothing consuming it yet) **or** documented in the field comment and the ADR as a declared part of the contract that Liftoff measures downstream. An undocumented `None` is a trap for the one person the contract exists for.

| stage | today | after |
|---|---|---|
| construct | `LR.parse` → list of float lists (`fpv_report.py:1938`) | `source.load_flight(path)` → `(SessionMeta, FlightSeries, LapSet)` |
| transport to analysis | write `flight.csv`, read it back (`:1946-1953`) | the `FlightSeries` object, passed directly |
| `analysis.load()` | `load(path, speed_floor)`, `csv.DictReader` (`analyze_flight.py:92-93`) | `load(series, speed_floor)` — takes the dataclass |
| nose bearing | a second `DictReader` over the same file (`fpv_report.py:246`) | one pass over the series; the second open disappears |
| `scene.path_window` | a **third** independent `DictReader` (`liftoff_scene.py:535-546`) | routed through `schema.read_csv()` — **[M1]** |
| `flight.csv` | the transport | **a side output**, serialised from `FlightSeries` by `common/schema.py` |
| `incident_view.build/impacts/window_indices` | `r[0]`, `r[1:4]`, `r[16]` | `FlightSeries`, fields by name |
| crash table `report.py:953-1009` | `rows[i][16]`, `rows[i][2]`, `rows[i][1:4]` | `FlightSeries`, fields by name |

`flight.csv` survives unchanged as a deliverable — linked from `report.md` (`fpv_report.py:1322` via `figs["csv"]` at `:1999`), named in `analysis.json`'s `not_in_report` (`:2099`), listed in the brief's data-stores table. It is now written *from* the dataclass rather than being what the dataclass is decoded into. The standalone `analyse` CLI still takes a CSV path: `cli.py` calls `schema.read_csv(path) → FlightSeries`, so `python "<clone>\src" analyse reports\<stem>\flight.csv` behaves exactly as `analyze_flight.py flight.csv` does today, and the CSV becomes a genuine round-trippable interchange format rather than an internal pipe.

**Scope, approved as narrowed:** `analysis.load()` still *emits* the same per-sample working dicts (`spd`/`vh`/`slip`/`turn`/`radius` — all derived, none emitted by a sim) and the ~470 lines downstream are untouched. The change is confined to `load()`'s 44-line body, the ~12 positional-index sites, `load_samples()`, and `path_window`.

### Dataclasses in `common/schema.py`

Frame documented once at module level: **Unity world space, left-handed, +Y up, metres** (the frame the replay and track XML already share). Every field carries its unit.

`FlightSample` — `t` s on the session clock; `pos` (x,y,z) m; `attitude` quaternion (x,y,z,w); `velocity` (x,y,z) m/s; `throttle` 0..1; `yaw`/`pitch`/`roll` −1..+1. `FlightSeries` — samples, `sample_dt` s (the **measured median**, never a first difference), source name, capabilities. `SessionMeta` — track id, race id, environment, gamemode, drone config, created, total time s, game version, source file. `LapSet` — lap times s, lap start indices, segment names. `Gate` — position m, yaw deg, aperture m, route order. `TrackGeometry` — gates + placed blueprint items + provenance. `Collider` / `PropPlacement` — half-extents m, local offset m, local rotation quaternion, `trigger` flag, item name, kind. `WorldGeometry` — colliders + bounds + provenance. `PbSnapshot` — taken_at, per-track best race s / best lap s. `Capabilities` — see §6.

Every field is traced to a reader that exists today in `analysis.py`, `incident_view.py` or `report.py`. Nothing is added because a hypothetical sim might have it.

### Precision parity — a deliberate, temporary compatibility measure

The pipeline currently runs at **two precisions simultaneously**: `fpv_report.py:1950` writes the CSV with `round(x, 6)` so the analysis sees 6-decimal values, while `LV.build` (`:990`) and the crash table receive the in-memory `rows` from `:1938-1939` at full double precision. Collapsing both onto one `FlightSeries` shifts one of them, producing 7th-significant-digit differences across most of `analysis.json` — which criterion 15 would surface as dozens of unexplained deltas at the exact moment the diff must be clean.

**Resolution:** `FlightSeries` carries full precision (matching what the view and crash table see today), and `common/analysis.load()` quantises each field with `round(v, 6)` as it reads, exactly reproducing the CSV round-trip. The equivalence is exact, not approximate: `csv.writer` emits `repr` of the rounded float and `float()` of that string returns the identical double. **Verified across 310,637 values** — real magnitudes, adversarial 6-decimal ties, signed zero, denormals, 1e±15, and 20,000 random finite 64-bit patterns — compared as packed doubles, zero mismatches.

**Placement is load-bearing and must not be "cleaned up".** The quantisation belongs in `common/analysis.load()` — the analysis path **only**. Hoisting it into `common/schema.py` or `source.load_flight()` "for consistency" would change the crash-table and incident-view numbers, which see full precision today, and fail criterion 15 in the opposite direction. It carries a comment at the call site naming that trap.

Doing it inside the migration would make the one thing the migration must prove — that nothing changed — untrue for reasons no reviewer could separate from a real regression.

**The quantisation is temporary, and it is removed in this run (author's decision, 2026-08-30).** It exists for commits A–E only. **Commit F** deletes it, and that commit's entire diff *is* the precision change.

**Corrected 2026-08-30 during D: the parity measure lives in TWO sites, not one.**
1. `common/analysis.load()` — the contiguous block quantising each field on read.
2. `common/report.py`'s `load_samples()` — the nose bearing's `round(v, 6)` on the attitude quaternion. It **must** be quantised for A–E, because the code it replaces opened `flight.csv` a second time and therefore computed the nose from the 6-decimal values. This is exactly why D's nose comparison came out bit-identical.

**F removes both**, and afterwards the whole pipeline is at full precision. Any description of F as a one-line change is wrong. QA then runs the criterion-15 comparison a **second** time (§15) so every resulting delta is attributable to that single line and to nothing in the migration.

Two things about commit F that must not be got wrong:

- **`flight.csv` keeps `round(x, 6)`.** Only the in-memory analysis path goes to full precision. The CSV stays a stable, readable interchange artifact with a byte-clean diff, and it remains the direct check that `FlightSample` serialises to the same 17 columns. Full precision in the CSV was explicitly declined.
- **Expect categorical changes, not only numeric ones.** Stall classification is a deterministic decision table with thresholds (`analysis.py`). A 7th-significant-digit shift on a value sitting exactly on a threshold can flip a verdict — an overrun becoming a corner, or a stall appearing or disappearing. That is rare and unpredictable, and it is the substantive reason commit F is separate: on its own diff, such a flip is visible and explicable; buried in the migration it would be indistinguishable from a regression. QA reports any classification change explicitly rather than folding it into a numeric summary.

The ADR records the parity measure, its purpose during A–E, and its removal in F — as a decision that was taken and completed within this change, not as an open wart.

## 5. Per-sim calibration (criterion 11)

**The line, stated in the ADR so a later reader can place a new constant: physical constants are calibration; presentational ones are not.**

To `sources/liftoff/calibration.py`: the 18 `analyze_flight.build_parser()` defaults; `IMPACT_DROP_KMH = 20.0` and the `i - last > 3` impact debounce (`liftoff_view.py:73` — both tuned to Liftoff's 10 Hz rate); `PROP_NOMINAL = (0.6, 1.0, 0.6)`; `--rec-radius 25.0` (`fpv_report.py:1922`) and `--cam-span 45.0` (`:1909`), both metres of track scale.

Staying in `common/`: `--anim-max 40.0`, `--anim-frames 380`, `--stall-pad 4.0` — seconds of animation and frames of SVG, properties of the report, not the sim. `liftoff_scene.py`'s constants (`DEFAULT_RADIUS`, `MIN_COLLIDERS`, `NEAR_GATE_M`, `NEED_FRACTION`, `MAX_PATH_INSIDE`) need no treatment; they are already inside what becomes `sources/liftoff/scene.py`.

## 6. Capabilities (criterion 9)

`common/capabilities.py` defines the `Capabilities` dataclass and exposes the declared-gap lookup as a **single function** that both produces the named `not available from <sim>: <reason>` line and records the gap for `analysis.json` — so a stage cannot consume a gapped field without the report learning about it. The existing degraded-recording footer (`incident_view.build()`'s `note`) becomes its first caller rather than a parallel mechanism.

`sources/liftoff/capabilities.py` populates it: stick positions available (throttle 0..1, three axes −1..+1); attitude available (quaternion); velocity **derived, not measured** (central difference at 10 Hz); sample rate 10 Hz nominal with irregular timestamps, measured median; lap boundaries available (`lapTimes` + `lapStartIndices`); gate/route geometry available, conditional on the `trackdata` cache; collision geometry conditional on the scene and prop caches; gyro / battery / motor RPM unavailable from a replay (live UDP telemetry only); PB history available via snapshots.

**Surface, deliberate:** the declaration is written into `analysis.json` as one new top-level `capabilities` key and produces **no change to `report.md` or `report.html` for Liftoff**, because Liftoff declares no gap that suppresses a finding the report currently makes. That keeps criterion 16 clean and reduces criterion 15's diff to exactly one additive, pre-declared key.

## 7. Toolkit root (criterion 12)

Today `TOOLKIT_ROOT = Path(os.path.realpath(__file__)).parent.parent` (`liftoff_replay.py:92`), correct only because the file sits one level below the root. At the new depth a wrong count silently disables the guard.

`common/toolkit.py` exposes `toolkit_root()`, which walks upward from `Path(os.path.realpath(__file__))` and returns the first directory containing **both `SKILL.md` and `pyproject.toml`**, raising at the filesystem root if it finds neither. Two markers so a user's own project containing a `pyproject.toml` cannot be mistaken for the toolkit; depth-independent, so a future move cannot silently break it; loud failure. Computed once into a module constant. `mounted_via_link()` is unchanged.

**Verified end to end on this machine:** invoked as `python "<junction>\src" …`, `__file__` comes back unresolved so `mounted_via_link()` → `True`, `realpath` resolves to the real clone, and `toolkit_root()` returns the real clone root. The guard still arms after the move.

## 8. Invocation (criterion 7) — `python "<clone>\src" <command>`

CPython prepends a directory passed as the script argument to `sys.path` and executes its `__main__.py`. With `src\__main__.py` beside `src\fpv_review\`:

```
python "<clone>\src" report --latest
```

`<clone>\src` lands on `sys.path[0]`, `import fpv_review…` resolves, **cwd is untouched**, no `PYTHONPATH`, no `pip install`, and no `sys.path` line in our own code (CPython does it, so criterion 5 stays clean). One string, identical in PowerShell, cmd and bash — which is exactly what `PYTHONPATH=src` fails at.

**Verified on this machine** from an unrelated cwd: `sys.path[0]` = the `src` dir, cwd unchanged, absolute package import resolved; and again through a junction with the guard behaviour above.

`src\__main__.py` is a thin front door; `cli.py` holds the subcommand table (`report`, `analyse`, `replay`, `tracks`, `scene`, `props`, `view`, `pbs`, `telemetry`), `--sim liftoff` as the default source, each subparser setting `prog` explicitly so `--help` does not print `__main__.py`.

*Fallback if criterion 7 fails at QA:* a launcher script at `src\fpv.py` invoked by path — identical `sys.path` mechanism, one more file.

## 9. `pyproject.toml` (criterion 6)

`[project]` only: `name`, `version`, `requires-python = ">=3.9"`, `dependencies = []`, plus `[project.optional-dependencies] unity = ["UnityPy"]`. **No `[build-system]`, no `[tool.setuptools]`, no `[project.scripts]`.**

Rationale, and what the ADR may claim: the file exists to **declare** the zero-dependency promise to tooling and to a reader. This project is **not an install target** — it ships by being cloned and run in place; `pip install .` is out of scope and untested. That is what the use case asked for ("metadata only… without introducing an install step"), and no criterion requires an install path — criterion 7 requires the opposite. (An earlier draft carried a `[build-system]` block; it was dropped because `package-dir` is not a `[build-system]` key, src-layout auto-discovery would trip over the top-level `src/__main__.py`, and **this machine's Python 3.14.3 has no `setuptools` installed at all** — so the claim could not be backed. Dropping it removes an untestable assertion rather than adding untested configuration to a project that has chosen to have no tests.)

**3.9 floor:** no `dataclass(slots=True)` (3.10+); new modules using `list[X]` / `X | None` annotations need `from __future__ import annotations` (as `liftoff_pbs.py:28` already does). Existing code is clean — the `match` at `liftoff_tracks.py:217-225` is a local variable in the LZ4 decoder, not a match statement.

## 10. ADR

`docs\adr\0001-multi-sim-architecture.md`, Status **Accepted**, sections Status / Context / Decision / Consequences. Seven decisions, each **with the alternative it beat and why** (criterion 2):

1. `src\fpv_review\` layout — beat top-level `sources\`/`common\` (squats two of the most common import names on `sys.path`) and beat keeping flat `scripts\` (the flat-import trick only works while all modules share one directory).
2. Metadata-only `pyproject.toml` — beat no metadata file (nothing declares the zero-dependency promise to tooling) and beat a full installable distribution (breaks clone-and-go, and cannot be verified here).
3. Python dataclasses as the schema — beat JSON Schema with a hand-rolled stdlib validator (a validator is code with no tests behind it) and beat JSON Schema as unenforced documentation (drifts).
4. Per-sim folder contract, documented in the ADR rather than as empty stub folders (git does not track empty directories; stubs for sims whose data nobody has inspected are the speculative generalisation the brief forbids).
5. **Invocation `python "<clone>\src" <command>`** — beat cwd-set-to-`src` (writes user data into the toolkit; quote `liftoff_pbs.py:121` as the justification), beat `PYTHONPATH=src` (bash-only, silently wrong in PowerShell), beat `pip install -e .` (breaks clone-and-go).
6. Toolkit root by two-marker search — beat counting `.parent` levels (silently wrong at a new depth) and beat an env var (one more thing to forget; the guard must work with zero configuration).
7. Per-sim calibration under `sources\liftoff\calibration.py` — **every physically-calibrated constant, wherever it currently sits** — beat leaving Liftoff-tuned constants as `common\analysis.py` defaults (they would silently apply to a sim they were never calibrated against).

Plus: the module mapping table; the rejected string-import registry; the deferred "hoist UnityFS when a second Unity sim lands"; the precision-parity measure — why it existed for commits A–E and why it was removed in commit F within the same change, including the `flight.csv`-stays-at-6-decimals decision; the nine-modules-lose-runnability-by-path consequence; the note that `analyze_flight.py` was already stdlib-only with no Liftoff import, so criterion 10 is achievable rather than aspirational; and the plain statement that the first real second sim **will** change this contract, and that is expected rather than a failure.

## 11. Documentation (criterion 14)

`README.md` — install block unchanged (it is the clone), plus a short "running it directly" line with the new invocation. It prints no commands today, so this is an addition, not a rewrite.

`SKILL.md` — stays at root. Its two command blocks (`:55-59`, `:117-121`) use `S=scripts`, bash syntax in a PowerShell-primary project, plus a bare relative `scripts` correct only when cwd happens to be the clone. Both are replaced with the skill folder spelled out once and the new subcommands, **PowerShell first and bash second, both verified to run as printed**. `:207`'s cross-reference to `scripts/README.md` retargets to `docs\engineering.md`. `SKILL.md:21` ("Only Liftoff is handled") and the Liftoff-framed prose at `:8-23` stay as they are — still true, since the restructure adds no second sim. Only the commands generalise.

`docs\engineering.md` — receives `scripts\README.md` whole, with module table, paths and commands updated. It is rationale the brief calls the project's strongest quality mechanism: retargeted, not summarised away.

## 12. `.gitignore` (criterion 13)

Current patterns (`__pycache__/`, `*.py[cod]`, `*.csv`, `replays/`, `reports/`, `liftoff-pilot.md`, `data/`, `trackdata/`, `.venv/`, `.DS_Store`) are unanchored so they already match at any depth and cover the new tree — but this must be **verified with `git check-ignore -v`, not assumed**. One justified addition now that a `pyproject.toml` exists: `build/`, `dist/`, `*.egg-info/`.

## 13. `PROJECT_BRIEF.md` reconciliation (use-case criterion 12 / lead's adaptation 2)

Frontmatter `paths.production` from `["scripts/**", "SKILL.md"]` to the new layout (`src/**`, `SKILL.md`, `pyproject.toml`, `docs/**`). Prose in `## Architecture`: the components table (nine `scripts/*.py` rows), the ASCII dependency graph, the "Path scopes for the dev-team" paragraph, and **"Planned direction — multi-sim structure"**, whose opening "*Not built; nothing below describes the code as it stands today*" becomes false on merge and must be rewritten to point at the ADR. Also the "No ADR directory" sentence under `## Documentation`.

## 14. Execution sequencing — a correctness control, not project management

The use case's own risk list says correctness rests entirely on criterion 15 and on reading the diff. A single commit moving ~6,900 lines is not reviewable. Only `props.py` and `telemetry.py` move whole; the other seven split.

- **A** — whole-file `git mv` of all nine to their primary destinations. No content edits. The tree is broken here; that is expected.
- **B1…B7** — one commit per origin file for its extraction (`replay`→toolkit+kinematics+COLUMNS; `tracks`→unityfs; `scene`→geometry; `view`→`props_near` out and `main()` out; `analysis`→calibration values out; `report`→`main()` and `pb_context` out; `pbs`→generic half out). Each diff has exactly one origin, so `git diff -M -C --find-copies-harder` can attribute the moved hunks.
- **C** — import rewrites across the tree. Mechanical and uniform.
- **D** — the boundary rewrite: `analysis.load()` taking `FlightSeries`, the positional-index sites, `path_window`, the precision quantisation. **The only commit containing behaviour-bearing edits, and the one a reviewer must read line by line.**
- **E** — new files (schema, capabilities, calibration, cli, `__main__`, pyproject, ADR, docs); delete `scripts\`.
- **F** — **remove the precision-parity quantisation from BOTH sites**: the block in `common/analysis.load()` and the nose-bearing `round(v, 6)` in `common/report.py`'s `load_samples()`. Delete the comments that guarded them. Behaviour change only — no other edit permitted in this commit. Lands only after QA has verified A–E clean; if A–E do not verify, F does not happen and the run stops at E for the user to decide.

Delete `scripts\__pycache__\` explicitly before the first run — stale `.pyc` from the flat layout can mask an import error.

**Standing review instruction (this substitutes for the test suite).** In A, that no line changed. In B1–B7, that each moved hunk is identical to its origin and only imports differ. In C, that every hunk is an import line or an `AF.`/`LR.`/`LT.`/`LV.`/`LS.` prefix change — anything else in this commit is a mistake. In D, that each replaced positional index reads the field the old index held: `[0]`=t, `[1:4]`=pos, `[4:8]`=quat, `[8:12]`=sticks, `[12:15]`=vel, `[15]`=speed_ms, `[16]`=speed_kmh, per `liftoff_replay.py:72-74`. **[M2]** Find those sites by grepping `rows\[` and `r\[` across the whole file and classifying each hit — `rows` is shadowed at `fpv_report.py:588`, `:1145` (`md_table`), `:1280`, `:1286`, `:1789-1791` (markdown tables), none of which are flight samples, so the 953-1009 span must not be trusted as the full list. In E, that nothing pre-existing was smuggled in.

**One PR, not two.** Criterion 1 requires Status `Accepted` and criterion 4 ties the mapping table to disk, so an ADR-first PR would land a document that is false until the second merges. The commit sequence is the unit of staging.

## 15. QA verification (no test files — criterion by criterion)

| # | check |
|---|---|
| 1,2 | read the ADR; Status `Accepted`; all seven decisions name their rejected alternative |
| 3 | list the tree; `SKILL.md` at root; `common/` holds schema, report and analysis |
| 4 | `scripts/` absent; the ADR's mapping table checked line by line against the tree |
| 5 | `grep -rn "sys.path" src\` returns nothing |
| 6 | `pyproject.toml`: `requires-python = ">=3.9"`, `dependencies = []`, UnityPy only under optional-dependencies, **no `[build-system]`**; the ADR says installation is out of scope |
| 7 | `git clone` the branch to a fresh temp dir, install nothing, run the documented command **in PowerShell and in bash** from a third unrelated working directory. On a **3.9 interpreter if one is present on the machine; if not, record the floor as unverified** rather than implying it was tested |
| 8 | read `common/schema.py`; every field carries a unit; the frame is stated once at module level |
| 9 | `analysis.json` carries the `capabilities` block, populated for Liftoff |
| 10 | `grep -rn "sources" src\fpv_review\common\` returns nothing |
| 11 | `grep -n "default=" src\fpv_review\common\analysis.py` shows no magic numbers; values live in `sources/liftoff/calibration.py` and match the current ones; `IMPACT_DROP_KMH`, the impact debounce, `PROP_NOMINAL`, `--rec-radius`, `--cam-span` are there too |
| 12 | **demonstrate, do not assume**: `New-Item -ItemType Junction` (or `mklink /J`; no admin needed), run a command through the link with an output path inside it → expect non-zero exit and the refusal message; **and the negative control** — the same command through the real path must NOT refuse |
| 13 | `git check-ignore -v` on a replay, a report, a `trackdata` file and `liftoff-pilot.md` under the new layout; `git status --porcelain` clean after a full run |
| 14 | run every command printed in `README.md`, `SKILL.md`, `docs/engineering.md`, as printed, in both shells |
| 15 | see below |
| 16 | `git diff --stat main -- examples/` is empty |
| 17 | `pyproject.toml` dependencies empty; no non-stdlib import outside `scene.py`/`props.py`, where UnityPy stays function-local |

**Criterion 15 method.** Run both pinned replays — `01 - Over The Horizon - 01_31_727 - 2026-08-30.xml` and `03 - Pipeline - 00_00_000 - 2026-08-30 - crash on 3rd.xml` — before and after. Four traps that would otherwise produce noise:

- Pass the **archived replay path explicitly, not `--latest`**, on both runs. `--latest` re-archives and re-picks the newest file.
- Use the **same working directory, `--track-dir`, `--history` and `--archive-dir`** on both runs, differing only in `-o`. `pb_context()` reads `data/liftoff_history.json` relative to cwd, so a different cwd changes the "best ever" bar.
- Expect `meta["_source"]` (`fpv_report.py:1940`, the absolute input path) to differ, and any run-time or snapshot timestamp likewise.
- Expect **exactly one** intentional structural difference: the new top-level `capabilities` key.

**Because of precision parity, there must be no numeric difference at all** — any float that differs, in any field, is a regression, not rounding and not noise. Also diff `flight.csv` before and after: it is now an output of the schema layer, and this is the most direct check that `FlightSample` serialises to the same 17 columns in the same order as `COLUMNS` does today. Open `report.html` once for each — a broken template or asset path yields a valid `analysis.json` and an unreadable page.

**Second pass, after commit F.** Re-run both replays and compare **E vs F** (not `main` vs F). This is the only comparison in the run that is *expected* to differ, and its diff is the deliverable: report which fields moved and by how much, and — separately and prominently — **whether any stall or crash classification changed**, since a threshold sitting on a boundary can flip a verdict categorically. `flight.csv` must be **byte-identical** across E and F, because the CSV keeps its 6-decimal serialisation; if it is not, the quantisation was removed from the wrong place. Also confirm `report.html` still renders for both replays.

## 15a. Baseline as actually captured (QA, 2026-08-30) — supersedes the assumptions above

The baseline exists and the numbers below were measured, not predicted. **The canonical command lines live in `C:\dev\liftoff-uc01-baseline\COMMANDS.txt` — copy from that file rather than retyping.** Frozen outputs: `C:\dev\liftoff-uc01-baseline\baseline\` with `baseline-sha256.txt`. Fixed run directory for **every** run in this engagement, before and after: `C:\dev\liftoff-uc01-baseline\run` (holds `trackdata\` incl. `props.json` and `scenes\`, `data/liftoff_history.json`, `replays\`). The `main`-branch clone is `C:\dev\liftoff-uc01-baseline\repo` at `a432be3`.

**The verification set is three replays, not two.** The two the use case pins, plus one QA added for cause:

| archived path (relative to the run dir) | pinned as | what it exercises |
|---|---|---|
| `replays/20260830-183818_TheRussianWoodpecker_Race_1lap.xml` | "01 - Over The Horizon…" | clean race; 1 impact, 1 recording, **scene not cached** → degrades to path-only with a named footer note. The after run must degrade *identically*, same note. |
| `replays/20260830-125608_Rustline_Race_nolap.xml` | "03 - Pipeline… crash on 3rd" | **0 impacts** — see below |
| `replays/20260829-205847_LiftoffArena_Race_3lap.xml` | QA addition ("01 - Mexican Wave…") | 2 impacts, 2 recordings, geometry **found**: 4,652 pooled colliders, 196 pooled props. The only replay that runs the cull, the collider Pool and incident assembly. |

Archive names do not resemble the pinned filenames because `liftoff_replay.py` names by `<creationTime>_<environment>_<gamemode>_<laps>`: the pinned "Pipeline" replay is in the *Rustline* environment and "Over The Horizon" is in *TheRussianWoodpecker*. Archiving is idempotent (stamped from `creationTime`), so these paths are stable.

**Why the third replay is mandatory.** The pinned "crash on 3rd" replay produces **zero impacts** — detection requires ≥20 km/h lost in one 0.1 s sample (`liftoff_view.IMPACT_DROP_KMH`) and that flight never drops that fast. With the pinned pair alone, `liftoff_scene.py`'s `cull`, the geometry `Pool`, index-referenced colliders and the whole incident-recording assembly are **never executed** — precisely the code commits B4 and D touch most. The use case's own words: "A migration verified only on a clean flight has not been verified."

**The fourth replay — the canary — is required in BOTH passes, and it is the most valuable of the four.** `replays/20260830-122843_Rustline_Race_nolap.xml` (from `03 - Pipeline - 00_00_000 - 2026-08-30.xml`, *without* the `- crash on 3rd` suffix). It was added as a knife-edge probe for commit F, but capturing its baseline revealed a second coverage hole of the same shape as the crash-path one:

> **It is the only replay of the four that exercises the stall decision table at all.** It produces **10 stalls — 3 corner, 5 hesitation, 2 overrun**, hitting all three verdicts. The other three replays produce **zero** stall recordings between them. Without it, the overrun/corner/hesitation classifier — which `PROJECT_BRIEF.md` calls the project's core claim, and which §4 warns is exactly what a 7th-digit shift can flip — was **completely dark in both passes**, not merely in F.

It is also the first replay in the set where the geometry `Pool`'s clustered-incident deduplication does real work (8,748 colliders and 27 props pooled from 17,765 and 98 summed across 11 recordings — a 2.0× dedup), which is precisely what commit B4 moves. Its scene resolves (Rustline is cached; the "no mesh, terrain geometry" line is the cache's normal partial skip, not a miss), its `hit: null` branch exercises the no-prop-in-range path, and its `report.html` is 1,022,679 bytes — 26× the pinned crash replay's.

**Baseline stall verdicts, for attributing any flip in the E-vs-F pass:**

| # | t (s) | verdict | retrace | turn | min |
|---|---|---|---|---|---|
| 1 | 29.0 | corner? | 10.9 | +132 | 8.8 |
| 2 | 35.2 | hesitation? | 12.9 | — | 5.2 |
| 3 | 36.8 | hesitation? | 0.3 | — | 7.5 |
| 4 | 43.9 | overrun | 0.1 | — | — |
| 5 | 52.0 | corner? | 35.7 | — | 6.7 |
| 6 | 70.3 | corner? | 8.5 | | |
| 7 | 86.9 | hesitation? | 6.8 | | |
| 8 | 98.4 | hesitation? | 1.2 | | |
| 9 | 100.7 | hesitation? | 3.0 | | |
| 10 | 105.5 | overrun | 0.1 | | 6.2 |

**Check these two values before anything else in the E-vs-F pass.** QA ranked every classified value across all four baselines by its margin to the threshold it is compared against; the two tightest are both here:

- **Margin 0.00 — stall #9 (t=100.7).** `retrace_m` serialises as exactly `3.0` against the `3.0` retrace threshold. `analysis.json` rounds `retrace_m` to one decimal, so the true unrounded margin is unknown but is **at most 0.05**. Tighter than the crash this replay was chosen for. Its verdict is `hesitation?` with `why="no cross-lap evidence"` and `turn_deg` null, so a flip moves it across the corner/hesitation boundary.
- **Margin 0.20 — crash #1 (t=115.2).** Drop 20.2 vs `IMPACT_DROP_KMH` 20.0. A flip here deletes the impact, takes `crash-1` and its recording with it, drops the recording count from 11 to 10, and re-pools the geometry.

Next tightest is 1.10 (the Woodpecker crash, 21.1 vs 20.0); everything else is 1.2 or wider.

**⚠ Filename trap.** The pinned crash replay and the canary archive to names differing only in a 6-digit time field — `20260830-125608_Rustline_Race_nolap.xml` (pinned, 0 impacts) versus `20260830-122843_Rustline_Race_nolap.xml` (canary, 1 impact + 10 stalls). Misreading one for the other silently swaps the input and invalidates the comparison with no error. `COMMANDS.txt` carries a CAUTION block naming both; copy paths from that file rather than retyping.

## 15b. The comparison is a FULL-TREE diff, not `analysis.json` field-for-field

**Criterion 15's own wording — "the two `analysis.json` outputs are compared field for field" — is insufficient, and an identified bug walks straight through it.** Amended 2026-08-30 after QA demonstrated the gap.

The entire viewer payload lives **only** in `report.html`. `analysis.json`'s `recordings` key holds just `{in, ids, titles}` — no geometry at all. In the canary's outputs, `dist0`, `target`, `startFrame`, `vref`, `propSize` and `colliders` each appear once in `report.html` and **zero times** in `analysis.json`. So any defect confined to the rendered report is invisible to the criterion as written. Two known candidates:

- **A mis-bound `bounds_of`.** `report.py` defines a *local* `bounds_of(samples)` unrelated to the `geometry.bounds_of(points)` that moved in B3. A blind requalification in C repoints three call sites at the wrong function. It feeds the camera framing (`dist0`/`target`), so it changes `report.html` **only** — `analysis.json` is untouched, the static prefix scan does not see it (it is a Python-side wrong-function bind, not a module prefix in JS), and the behavioural probe probably passes too, since a badly-framed scene still draws plenty of colours.
- **The JavaScript `qmul`/`qrot` corruption** (see below) — likewise `analysis.json`-invisible.

**Therefore the A–E comparison is specified as a full-tree diff:** `analysis.json` **+ `report.md` + `report.html` + `flight.csv` + `assets/*.svg`**, for every replay. Exactly two differences are excused: the `generated` timestamp line, and the new top-level `capabilities` key. Everything else is a regression. This is what QA already measured the noise floor against, so it costs nothing extra — it just has to be *stated*, because the criterion's literal wording licenses a weaker check.

### The JavaScript corruption check — built and proven, not planned

QA built a faithful mutant of the trap the developer found in B3 (call sites rewritten to `geometry.qrot(...)`, `function qrot(...)` declarations left intact — which is precisely what a blind sweep produces) and measured what each check does with it:

| check | mutant result |
|---|---|
| `analysis.json` vs baseline | **byte-identical** — criterion 15 sees nothing |
| `node --check` on inline JS | **passes cleanly** — the syntax is valid |
| HTML structure / refs | **passes** |
| **Layer 1 — static prefix scan** | **CAUGHT** (6 hits, all `geometry.q`) |
| **Layer 2 — behavioural probe** | **CAUGHT** — `ReferenceError: geometry is not defined`, thrown from `draw()` ← `resize()` ← `ResizeObserver` ← `fpvViewer` ← `open()` |

**Layer 1** greps inside `<script>` blocks for any Python module prefix (`geometry`, `analysis`, `schema`, `props`, `tracks`, …). The naive form **false-positives on every replay with recordings**, because the viewer legitimately contains `it.props.map(i => FPV_REC.props[i])`; a negative lookbehind excluding `.`, identifier characters, `$` and quotes fixes it, since a bare module reference is never preceded by a dot. Calibrated against all four pre-migration reports: zero hits. Runs on every after-run, including the replays with no recordings.

**Layer 2** opens each recording by a real click (`[data-rec="<id>"]`), via headless Chrome over the DevTools protocol with no third-party dependency, collecting `Runtime.exceptionThrown`, console errors and Log entries. Its second, independent assertion is sharper than "no error logged": the viewer draws into a **2D canvas** and `draw()` paints the background *first*, so a throw inside the geometry loop leaves a canvas of exactly **one distinct colour**. Colour count is therefore a direct liveness signal. Baseline references: Woodpecker 1 recording, 714×257, 629 colours; canary 11 recordings, 1,610–3,064 colours each, all opening without error; LiftoffArena's 2 to be captured at verification time. Both signals fired independently on the mutant.

### Layer 2 must be told how many recordings to expect

A probe that only checks what a page *offers* is silent when the page offers nothing. Run against the pinned Rustline replay — which legitimately has zero recordings — layer 2 opened zero, found no error and reported **PASS**. Correct for that replay, and useless as a guarantee: if the migration made recordings *vanish* from a report that should have them, the check would have passed. That is the same failure shape as the JavaScript trap itself — a check that is quiet exactly where it should be loud.

**Closed by passing the baseline recording count as an argument; a mismatch fails.** Verified in both directions (told to expect 5 where there are 0, it fails with `RECORDING COUNT CHANGED: page offers 0, baseline had 5`; given the true counts 1 / 0 / 2 / 11, all four pass). **Always pass the expected count.**

**Baseline viewer references** (canvas 714×257 throughout; all opened by a real click, no exceptions, no console errors):

| replay | recordings | distinct colours |
|---|---|---|
| TheRussianWoodpecker | 1 | crash-1 629 |
| LiftoffArena | 2 | crash-1 4401, crash-2 2131 |
| Rustline canary | 11 | crash-1 2398; stall-1-1…-10: 2038, 1610, 1869, 2330, 1875, 1947, 3018, 2941, 3064, 2412 |
| Rustline pinned | 0 | — |

The *ordering* is itself a check: LiftoffArena's `crash-1` has the richest scene (1,870 culled colliders) and draws the most colours; the Woodpecker's degraded path-only recording draws the fewest. **If those relationships invert after the migration, something is wrong even if nothing throws.** But treat the numbers as a shape, not a fingerprint — the failure signal is a count of **1** (background only, scene never drew) or a large collapse, never a small drift. 2398 versus 2401 is not a regression.

**Both checks are durable artifacts beside the baseline**, not session-scoped snippets: `C:\dev\liftoff-uc01-baseline\check-script-prefixes.py` (layer 1) and `C:\dev\liftoff-uc01-baseline\viewer-probe.mjs` (layer 2, usage `<report.html> <port> <expected-count>`). Each carries a comment block explaining what it catches and why the obvious simpler version fails. `COMMANDS.txt` holds the full verification contract — both invocations, the colour table, the expected-count rule, the comparison scope, and an explicit note that **neither layer catches a mis-bound `bounds_of`**, with what does.

### 15c. The comparison harness, calibrated against a known-clean run

`C:\dev\liftoff-uc01-baseline\compare-tree.py` performs the full-tree diff. It was **dry-run against the unchanged `main` clone** — all four replays, canonical commands, `-o reports-dryrun` — and came back clean on every axis: full-tree diff, layer 1, layer 2, and **every viewer colour count reproducing exactly**. So the instrument is calibrated: a difference reported after the migration is a real difference, not harness noise.

It was then **broken on purpose**. Seven defects were seeded into a copy of the clean run and all seven were caught and named: a 7th-significant-digit float (the commit-F shape), a stall verdict flip, an added top-level key, an SVG attribute change, a `dist0` change buried at column 534,856 of a 1 MB line in `report.html` (the `bounds_of` shape), a deleted asset, and a line-endings-only change.

**Three harness defects that exercise exposed — each would have corrupted a real verdict:**

1. **Line-ending blindness, and it is a live migration risk rather than a toy.** `splitlines()` normalises newlines away, so a file differing *only* in line endings was reported as different and then described as "0 differing lines". Worse: `flight.csv` is written by `csv.writer`, whose terminator is already `\r\n` (2,820 CRs in the Woodpecker file), so a writer that **loses `newline=""`** emits `\r\r\n` — which `splitlines()` reads as thousands of phantom blank lines. **The file writers move in commits B–D**, and `common/schema.py` takes over serialising `flight.csv` in D, so this is a real possibility on this run. The harness now strips every CR and reports `LINE ENDINGS changed only (CR count X → Y, content identical) — check for a lost newline="" on the writer`. **`flight.csv` is CRLF today and must stay CRLF** — the plan's own "byte-identical across E and F" condition depends on it.
2. **Useless excerpts on long lines.** `report.html` carries the whole viewer payload on one ~1 MB line, so a 160-character excerpt showed two identical-looking strings. It now windows on the first differing *column*, which is the only reason the `dist0` mutation was legible.
3. **Inflated counts.** Detail lines were counted as separate problems, overstating the damage.

**Two hedges that measurement removed:**

- **Colour counts reproduce exactly** for identical code and identical geometry. The earlier caveat ("the signal is 1 or a large collapse, not a small drift") therefore applies **only to the E-vs-F pass**, where geometry may legitimately shift. For **A–E, any change in a colour count is investigable.** That is a materially sharper check than first specified.
- **`--allow-capabilities` excuses the new top-level key for A–E only.** It must **not** be passed for the E-vs-F pass: both sides have the key by then, so any difference there is real.

### 15d. Pre-declared output differences, and the standalone page

**Three differences beyond `capabilities` are declared IN ADVANCE.** Found during B6 by inventorying strings that name old script filenames. Two of them are *runtime output*, not comments, and they instruct a user to run files that will not exist after the migration — so they must be fixed, and fixing them changes committed output. Declaring them before the comparison is the whole discipline; explaining them afterwards is what an undeclared regression looks like.

| # | change | where it shows, verified against the frozen baseline |
|---|---|---|
| 1 | the `capabilities` key | `analysis.json`, all four |
| 2 | footer attribution — `generated … by \`fpv_report.py\`` | **8 occurrences — 4 `report.md` AND 4 `report.html`** (corrected 2026-08-30) |
| 3 | uncached-scene note — `scene is not cached (liftoff_scene.py)` | **the Woodpecker's `report.html`** only — never `report.md`, since it lives in the html-only recording payload |
| 4 | uncached-props note — `prop shapes are not cached (liftoff_props.py)` | **0 — does not fire on this set**, `props.json` is cached for every environment flown. Nothing to expect. |

**The footer count was originally recorded as 4 and that was wrong.** The lead's grep matched only the markdown backtick form; in HTML the backticks render as `<code>` tags, so `by <code>fpv_report.py</code>` did not match. A comparison expecting 4 would have flagged the other 4 as real regressions — the exact shape of the false alarm that erodes trust in a check.

**The standalone pages are NOT affected.** They contain no script filename at all, so they remain a strict `cmp` with nothing excused. What changes is the Woodpecker **refusal message on stderr**, and that case writes no file — so the two checks do not collide. The message text is pre-declared; **the exit code 1 and the fact of refusing are not, and must hold.**

### `--declared` enforces the declarations rather than merely excusing them

`compare-tree.py` takes `--declared` alongside `--allow-capabilities`. It normalises the declared strings to placeholders on **both** sides, so it needs no advance knowledge of the replacement, and it **prints every before → after token** rather than swallowing it (`attribution ['fpv_report.py'] → ['fpv-review']`). An excused difference is precisely where a real regression hides, so it also enforces two things:

- **The fixed-string constraint, mechanically.** If the new attribution looks like a path, the comparison **fails**. Tested with `C:/dev/…/common/report.py` — caught, with the reason given. The constraint below is therefore enforced by the tool, not left resting on the developer's care.
- **Vanishing is not renaming.** If a declared string is present before and absent after, it **fails**. Deleting the uncached-scene note would otherwise sail straight through `--declared`, and that note *is* the project's stated "degrade visibly" guarantee. Also tested and caught.

Both flags are **A–E only**. On the E-vs-F pass both trees carry the new strings, so any difference there is real.

**Hard constraint on the new footer text: a fixed string, never a path.** If it embeds the clone location or anything machine-dependent, every generated report becomes irreproducible across machines and the baseline comparison breaks for a reason unrelated to this migration.

Other stale names are comments and docstrings (17 files), plus `cli.py`'s `--history` help text — all E obligations, none affecting output.

### The standalone incident page — a fourth artifact, and it refuses where the report degrades

`scripts/README.md:262` prints `python liftoff_view.py --replay replays/<crash>.xml -o crash.html`, so criterion 14 puts this artifact in scope. It **had no baseline** until now, and the viewer probe would have passed it **vacuously** — it shares `VIEWER_JS`, so the JavaScript bug does reach it, but the page around it has no `[data-rec]` triggers and no `#recmodal`; `page()` emits a `#wrap` div and calls `fpvViewer` at load. The probe looked for `[data-rec]`, found zero, and reported PASS. **Third instance of the same hole shape** (after the zero-recording report and the un-calibrated harness). The probe now auto-detects the standalone shape and inspects that canvas directly; do not pass an expected count for these pages.

**Frozen at `baseline-standalone\`** with checksums. These pages carry **no timestamp and regenerate byte-identically**, so they compare with a plain `cmp` — stricter than the report tree, nothing to excuse:

| replay | result | canvas | colours |
|---|---|---|---|
| LiftoffArena | exit 0 | 764×429 | 5667 |
| Rustline canary | exit 0 | 764×429 | 2884 |
| Rustline pinned | exit 0 | 764×429 | 3265 |
| TheRussianWoodpecker | **exit 1, no page written** | — | — |

**The refusal contract, which must survive the migration.** On an uncached scene the standalone path **refuses** — exit 1, no file, `no cached scene for TheRussianWoodpecker. Build it: python liftoff_scene.py --environment TheRussianWoodpecker` — where `fpv_report.py` **degrades** to a path-only recording with a footer note. Same missing input, two deliberately different responses, and they sit either side of a seam this migration moves: `main()` leaves `incident_view.py` entirely under §3, so the refusal lives in relocated code. After the migration it must still be exit 1 with that guidance. Every plausible regression here is silent — a page that builds empty, or a bare traceback instead of the instruction — and **none would be caught by the report-tree comparison**, because that replay's *report* degrades rather than refusing. (Note the message itself names `liftoff_scene.py`, so its text is a pre-declared change too.)

Also existing behaviour to reproduce rather than "fix": the pinned crash replay has no impacts, so its standalone page renders the `t=0.0` window rather than an incident, and still builds at exit 0.

Both check layers were proven on this shape as well: the same faithful mutation gives 6 layer-1 hits, and layer 2 gives both a `ReferenceError` **and a canvas of exactly one colour** — the background-fills-first prediction landing exactly, which is the strongest confirmation that the colour heuristic measures what it claims to.

**Measured noise floor.** The same command run twice against unchanged code, into two different `-o` directories, differs **only** in `analysis.json`'s `generated` (second granularity) and the `report.md` / `report.html` footer timestamp (minute granularity). **Every SVG asset and `flight.csv` were byte-identical.** Anything else that differs is a regression.

**Two corrections to §15's expectations:**
- There is **no `meta["_source"]` key**. The field is top-level `source_replay`, and because the input is passed as a path relative to a fixed cwd it comes out as the stable string `replays\<name>.xml` — so it is **not** expected to differ. Do not wave a change there away.
- `personal_bests` is stable **only while nobody runs `liftoff_pbs.py --save` in the run directory** — that rewrites the history and moves the "best ever" bar. Prohibited for the duration; recorded in `COMMANDS.txt`.

**Use forward slashes in every path argument.** A first baseline attempt used `--history data\liftoff_history.json` unquoted in bash; the backslash was eaten, the argument became `dataliftoff_history.json`, the file was not found, and `pb_context()` silently returned `{}` — **exit code 0 and a perfectly valid-looking `analysis.json` with empty `personal_bests`**. That baseline was discarded and recaptured. This is the failure mode most likely to produce a confidently wrong comparison, and it is silent.

**Python floor.** 3.14.3 is the only interpreter on this machine, so criterion 7's ">=3.9" claim must be recorded as **unverified** rather than implied. `liftoff_tracks.py --check` reports "track data READY: 92 tracks, 92 races, build 24687907" — no staleness gate.

**After runs must differ from the baseline in exactly two ways:** the entry point (`repo/scripts/fpv_report.py` → whatever the ADR settles) and `-o`. Everything else byte-identical, run from the run directory, never from inside the worktree — output defaults are bare-relative to cwd and the `refuse_inside_toolkit` guard does not fire on a plain clone.

**Baseline logistics.** The "before" run needs a checkout on `main`. Do **not** touch `C:\dev\liftoff-flight-analyzer`. Use `git clone <worktree> <temp>` then `git checkout main` there (`git worktree add` writes metadata into the original repo's `.git`, so it is not the right tool here). Store baseline outputs **outside** the worktree, or `reports/`'s ignore rule and the next run will eat them. Capture the baseline **first, before anything moves**.

## 15e. Two rules this run produced, and the evidence for them

A project with no test suite lives or dies on whether its checks are honest. Two rules emerged from actually building them, each from a failure rather than from principle. Both belong at the top of `COMMANDS.txt` (where they now are) and are direct input to the CONTRIBUTING guide.

**Rule 1 — a check must distinguish "I looked and found nothing" from "there was nothing to look at."** Such a check is worse than no check, because it converts absence of evidence into evidence of absence, and it is believed. Four instances in this run:

| what passed vacuously | what it would have let through | fix |
|---|---|---|
| viewer probe on a report with 0 recordings | recordings vanishing entirely from a report that should have them | pass the expected count; mismatch fails |
| comparison harness never exercised | a harness that reports clean because it cannot see | dry-run against unchanged code, then seed defects |
| viewer probe on the standalone page (no `[data-rec]`) | the JavaScript corruption on a whole artifact class | auto-detect the page shape |
| `--declared` printing "not present in either tree" | reads as "the string is gone" when it means "no file differed" — and on byte-identical trees *every* label lands there | reworded to "not seen in any differing file" |

**Rule 2 (corollary) — a check that has never been seen to FAIL proves nothing.** QA's first mutant renamed the JavaScript function *declarations* as well as the call sites; `node --check` caught that, and that version would have "proved" a probe that does not actually work. Only the faithful mutant — call sites alone, which is what a blind sweep really produces — demonstrated the gap. **Before trusting a green result, mutate something and watch the check go red.**

**Rule 1 applies to guards, not only to checks — and there the vacuous pass inverts.** A check that cannot fail is one that never looks; a **guard** that cannot fail is one that fires on *everything*, which looks like working code and breaks the product. So a guard needs both halves asked: *does it fire when it must?* and *does it stay quiet when it must?*

This is not theoretical. Every criterion-12 case the plan specified tested the first half — that `refuse_inside_toolkit()` blocks a write into a link-mounted toolkit. QA added a third case nobody asked for: **through a junction with output OUTSIDE the toolkit**, which is the actual install mode (cloned into `~/.claude/skills/fpv-review`, run from the user's own project). Had the guard over-fired there, the tool would have been broken for its primary installation, silently, for every user — and **no criterion in this plan would have caught it.** It passes: exit 0, output identical after timestamp normalisation. QA ran it against a *copy* of the tree so that a failed guard would write into its own directory rather than `TARGET_DIR`.

The two rules are siblings: one is about a check with no input, the other about a check with no proof. Both produce the same false confidence, and in a project that has chosen to have no test suite, false confidence in a check is the most expensive thing available.

## 16. Risks carried into implementation

1. **The invocation decision is the one that can break the product silently.** Verified empirically on Windows/PowerShell/junction on Python 3.14; QA's criterion-7 check from a fresh clone in two shells is the real gate. Fallback: `src\fpv.py` launcher.
2. `python "<clone>\src"` **reads as unusual.** It is documented CPython behaviour (directory-as-script, since 2.6), not a trick. The ADR must say what it does and why, and `SKILL.md` must print it with the path spelled out rather than assembled from a variable.
3. **Splitting `fpv_report.py`'s `main()` out of a 2,133-line module is the largest single content edit**, with no test behind it. The commit sequencing is the mitigation. The alternative — leaving `main()` in `common/report.py` with an injected source — was rejected because it strands Liftoff-shaped argparse defaults (`data/liftoff_history.json`, "the Liftoff Recordings folder") in `common/`, passing criterion 10's grep while failing its spirit.
4. **The dataclasses are designed against one sim.** Every field is traced to a reader that exists today; nothing is added speculatively. The ADR states plainly that the first real second sim will change this contract.
5. **`liftoff_pbs.py` splits across both trees**, as the use case predicted. Liftoff keeps `DEFAULT_ROOT`, `track_names`, `parse_times`, `snapshot`; `common/pbs.py` takes the history store, `fmt`, `diff_line`, and `pb_context` — which today lives in `fpv_report.py:840`, not in `liftoff_pbs.py`, so the mapping table must show a function arriving from a third file.
6. **On-disk cache formats must not change.** `trackdata/index.json`, the scene cache and `props.json` each carry `FORMAT = 1`. The dataclasses are in-memory only; cache readers and writers keep their current dict shapes and `FORMAT` stays 1.
7. **Criterion 16 is a do-not-touch check, not a regeneration check.** `examples/20260828-140705_BardwellsYard_Race_3lap/` came from a replay that may no longer exist on this machine, and `examples/` is outside the production scope by the brief's own statement. The developer simply must not write there.
8. **No test suite, linter or CI is added.** The brief forbids all three (settled 2026-08-30) and criterion 17 forbids any third-party runtime dependency.

---

**Hard ordering dependency:** the developer starts at §14 commit A **only after the §15 baseline has been captured** — the baseline must exist before anything moves.
