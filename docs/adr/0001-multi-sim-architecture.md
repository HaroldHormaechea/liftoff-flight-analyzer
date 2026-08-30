# 1. A multi-sim architecture

## Status

Accepted — 2026-08-30.

Amended — 2026-08-31, by use case 02, in four places: decision 4 twice (the
registration tolerance, and the function surface each contract module exposes),
decision 7 once (the six calibration module-level names), and Consequences once,
where § "Degradation stays explicit" became § "Degradation is declared and
published; the consuming half is provided and not yet called". No decision is
reversed. Each amendment records what the code does — which is what that use
case changed the code to make true.

## Context

The toolkit began as nine Python modules in a flat `scripts/` folder, every one
of them written against Liftoff: its replay XML, its Unity asset bundles, its
lap semantics, its coordinate conventions. That was the right shape while there
was one sim, and it stopped being the right shape the moment the author decided
there would eventually be more.

Nothing about *measuring a flight* is Liftoff-specific. Sideslip, tilt, turn
radius, the overrun/corner/hesitation decision table, the report and the 3D
incident view are all arithmetic over a time-indexed series of positions,
attitudes and stick positions. What is Liftoff-specific is *getting* that
series: decoding a base64 state blob, unwrapping a UnityFS bundle, reading a
ratcheting best-times file. The seam was already there in the code; it was not
expressed in the structure, and the flat layout let a Liftoff detail leak into
the analysis without anything noticing.

Two constraints shape everything below. `PROJECT_BRIEF.md` forbids speculative
generalisation ahead of a second real sim — no second sim's data has been
inspected, so this contract is designed against Liftoff plus what the analysis
actually consumes, and nothing else. And the analysis path takes no third-party
dependency: the project ships by being cloned into `~/.claude/skills/` and run
in place, with nothing to install.

## Decision

### 1. The tree is `src/fpv_review/{common,sources/<sim>}/`

`common/` holds the sim-agnostic half: the schema, the analysis, the report
templates, the incident view, the toolkit guard. `sources/<sim>/` holds
everything that knows what a particular game's bytes mean. `SKILL.md` stays at
the repository root, because Claude Code discovers it there.

**The three-layer import rule is the whole architecture in one sentence:**

- `common/` may import `common/` and the standard library, nothing else.
- `sources/<sim>/` may import `common/` and its own siblings, never another sim.
- `cli.py` is the only module allowed to import both trees, and it does the
  wiring.

Acceptance criterion 10 ("every module under `common/` is free of imports from
`sources/*`") is then satisfied by construction rather than by vigilance, and it
is checkable with one grep.

**Beat:** top-level `sources/` and `common/` packages, which squat two of the
most common import names on `sys.path` — any project that added this repo to its
path would find its own `common` shadowed. **Beat:** keeping the flat `scripts/`
folder, which works only while every module shares one directory; the flat
`import liftoff_replay` trick depends on exactly that and breaks the moment a
subfolder appears.

**Rejected, and worth naming so it is not re-proposed:** a string-based plugin
registry inside `common/` that looks sims up by name at runtime. It would pass
criterion 10's grep while violating its intent — `common/` would still be
reaching into `sources/`, just dynamically and unverifiably.

### 2. `pyproject.toml` carries metadata only

`[project]` with `name`, `version`, `requires-python = ">=3.9"` and
`dependencies = []`, plus `[project.optional-dependencies] unity = ["UnityPy"]`.
No `[build-system]`, no `[tool.setuptools]`, no `[project.scripts]`.

The file exists to **declare the zero-dependency promise** to tooling and to a
reader. This project is not an install target: it ships by being cloned and run
in place, and `pip install .` is out of scope and untested.

**Beat:** having no metadata file at all — nothing then states the
zero-dependency promise anywhere a tool can read it. **Beat:** a full installable
distribution — it breaks clone-and-go, and the claim could not have been backed
here anyway: the only interpreter on the development machine has no `setuptools`
installed, so a `[build-system]` block would have been an untested assertion
added to a project that has deliberately chosen to have no tests.

### 3. Python dataclasses are the schema

`common/schema.py` defines every artifact that crosses a stage boundary:
`FlightSample`, `FlightSeries`, `SessionMeta`, `LapSet`, `Gate`,
`TrackGeometry`, `Collider`, `PropPlacement`, `WorldGeometry`, `PbSnapshot`.
Every field carries its unit, and the coordinate frame — Unity world space,
left-handed, +Y up, metres, seconds — is stated once at module level.

**Beat:** JSON Schema with a hand-rolled standard-library validator — a validator
is code, and this project has no test suite to put behind it. **Beat:** JSON
Schema as unenforced documentation — it drifts, silently, and the first person to
notice is someone debugging a wrong number.

### 4. The per-sim contract is documented here, not stubbed in the tree

A sim is added by writing `sources/<sim>/` with `source.py` (emit the schema),
`map_geometry_generator.py` (answer what is near a set of points),
`calibration.py` (the constants measured on that sim) and `capabilities.py`
(what it cannot supply), then registering it in `cli.py`. The analysis is not
touched.

**Those four modules are the contract, and registration honours it.** `cli.py`
registers a sim as a dictionary of module keys. Four are required —
`calibration`, `capabilities`, `source` and `map` — and a package holding only
those registers successfully and offers `analyse` and `report`. The other six
keys — `replay`, `pbs`, `tracks`, `scene`, `props` and `telemetry` — are per-sim
extras. Each enables named commands, each is optional, and `--help` lists every
command left out beside the module file that would add it.

Every key names the module file of the same name — `replay` is `replay.py`,
`pbs` is `pbs.py` — with one exception. `map` is `map_geometry_generator.py`,
because the map is assembled from tracks, scene and props rather than being any
one of them.

Before this amendment (use case 02) that was not true. A package conforming to
the contract above raised `KeyError('replay')` while the parser was still being
built, because `add_report` read `sim["replay"].DEFAULT_ROOT` for the `--root`
default unconditionally. The documented contract could not be implemented.

**Beat, and it was the cheaper option:** amending this decision to describe the
ten-key registration the code actually required. Rejected. It would have
published a registration shape nobody designed — ten mandatory modules, six of
them irrelevant to a sim that only wants its flights analysed — and it would
have left the contract untrue rather than making it true. The gap was in the
code, so the code moved.

**The function surface, so a contributor does not have to read `cli.py` to find
it.** Signatures as defined, not as called:

| module | function | returns |
|---|---|---|
| `source.py` | `load_flight(path)` | `(SessionMeta, FlightSeries, LapSet, meta)` — four values. `meta` is the sim's raw metadata dict, published verbatim as `analysis.json`'s `meta` key |
| `map_geometry_generator.py` | `props_near(track_dir, track_meta, route, points, radius, shapes=None)` | a list of item dicts (`p`, `yaw`, `n`, `k`, `ap`, `sh`), one per track item within `radius` of the path |
| `map_geometry_generator.py` | `geometry_for(replay, track_dir, scenes_dir, props_path)` | `(track, race, scene, shapes, note)`. A missing cache is never fatal here: it degrades and reports through `note`, the sentence naming what could not be drawn, which is empty only when nothing is missing |
| `calibration.py` | — | six module-level names, no functions; see decision 7 |
| `capabilities.py` | `declare()` | a `common/capabilities.py` `Capabilities` |

Two more functions became contractual in the same use case, when `cmd_view` was
corrected to reach them through the selected sim rather than through Liftoff's
modules directly:

| module | function | returns |
|---|---|---|
| `tracks.py` | `for_replay(out_dir, replay)` | `(track, race, track_id, race_id)`. Either dict is `None` for a track the index does not hold |
| `scene.py` | `load_scene(out_dir, environment)` | the cached scene dict (`colliders`, `skipped`, …). It refuses with a runnable `scene` command when that environment is not cached |

Both serve `view`, so they are required only of a sim that supplies `tracks.py`
and `scene.py`. They are not part of the four-module contract.

These signatures are checked by first use, not at registration. Registration
validates the module **keys**; the functions behind them are the contract this
decision states, and duplicating them in a runtime check would put the same
contract in two places.

**Beat:** empty `velocidrone/` and `uncrashed/` stub folders. Git does not track
empty directories, and stubs for sims whose data nobody has inspected are
precisely the speculative generalisation the brief rules out.

### 5. Invocation is `python "<clone>/src" <command>`

CPython, given a **directory** as its script argument, prepends that directory to
`sys.path` and executes its `__main__.py`. So `src/` lands on `sys.path[0]`,
`import fpv_review…` resolves, and **the working directory is untouched**. One
string, identical in PowerShell, cmd and bash. Documented behaviour since Python
2.6, not a trick.

The working directory is the crux. Every output default in this tool is
bare-relative to it — `--archive-dir replays`, `-o reports`,
`--history data/liftoff_history.json`, `--track-dir trackdata` — and
`refuse_inside_toolkit()` only fires when the toolkit is mounted through a link,
so it does not protect an ordinary clone.

**Beat:** setting the working directory to `<clone>/src`, which would silently
accumulate the user's replays, reports and personal-best history *inside the
toolkit*. `liftoff_pbs.py` stated the rule in the codebase's own words long
before this ADR: paths are "relative to the working directory — never the
script's own folder, which may be shared or public." **Beat:** `PYTHONPATH=src`,
which is bash-only syntax and silently wrong in PowerShell, the primary
environment here. **Beat:** `pip install -e .`, which breaks clone-and-go.

### 6. The toolkit root is found by searching for two marker files

`common/toolkit.py`'s `toolkit_root()` walks upward from its own resolved path
and returns the first directory containing **both `SKILL.md` and
`pyproject.toml`**, raising if it reaches the filesystem root.

**Beat:** counting `.parent` levels, which is what the code did before
(`Path(realpath(__file__)).parent.parent`, correct only because the file sat one
level below the root). At the new depth a wrong count does not fail — it points
`TOOLKIT_ROOT` at some inner directory, no write ever lands underneath it, and
`refuse_inside_toolkit()` silently stops guarding anything. A search has no depth
to get wrong. **Beat:** an environment variable, which is one more thing to
forget; the guard has to work with zero configuration or it is not a guard.

Two markers rather than one because a user's own project may perfectly well
contain a `pyproject.toml`; only this toolkit has `SKILL.md` beside one. Note the
consequence: `pyproject.toml` is now load-bearing, and moving or deleting it
disables the guard.

### 7. Per-sim calibration lives in `sources/<sim>/calibration.py`

**Every physically-calibrated constant, wherever it previously sat.** For
Liftoff that is the 20 threshold defaults from the analysis parser (fixed
against the Rustline 2-lap race of 2026-08-26), `IMPACT_DROP_KMH`, the impact
debounce, `PROP_NOMINAL`, and the two track-scale distances `REC_RADIUS_M` and
`CAM_SPAN_M`. `common/analysis.build_parser(calibration)` receives them and
hardcodes none.

**The six module-level names, exactly as registration checks for them:**
`THRESHOLDS`, `IMPACT_DROP_KMH`, `IMPACT_DEBOUNCE_SAMPLES`, `PROP_NOMINAL`,
`REC_RADIUS_M` and `CAM_SPAN_M`. `cli.py` checks all six before it builds the
parser and refuses by name, naming the missing constant and the sim's own
`calibration.py`, rather than failing later inside a command.

The 20 `THRESHOLDS` keys are **not** listed a second time and are **not**
checked separately. `common/analysis.build_parser(calibration)` reads every one
of them to build the `analyse` parser, and `cli.py` calls it while registering
that subcommand — so a missing key is reached at registration by construction,
and is refused there by name. The keys stay encoded in the one module that has
always held them. A second list would be exactly the drift this decision exists
to prevent.

**The line, so a later reader can place a new constant: physical constants are
calibration; presentational ones are not.** A speed in km/h, a distance in
metres, a count of samples at this sim's rate — calibration. Seconds of
animation, frames of SVG, pixels — properties of the report, and they stay in
`common/`.

**Beat:** leaving them as `common/analysis.py` defaults. They were measured on
one sim's flights, and left in the shared layer they would apply to a sim they
were never calibrated against — silently, and with nothing to tell a reader it
had happened.

## Consequences

**Nine modules lose runnability by path.** `python scripts/fpv_report.py` and its
eight siblings are gone; there is one front door and nine subcommands. The
house convention that every module exposes `build_parser()` and is importable as
a library survives — what changed is that there is one `main()` instead of nine.

**`pyproject.toml` is load-bearing**, per decision 6.

**Under a link install, the printed commands name the resolved path rather than
the one the user typed.** `toolkit.invocation()` builds on `TOOLKIT_ROOT`, which
comes from `realpath`, and every message telling a user what to run next is built
from it — as is argparse's own usage line, which shares the same `PROG`. So a
toolkit reached through a symlink or a junction prints the real clone directory,
not the link.

Accepted rather than fixed. The command it prints **works**; it is consistent
with `refuse_inside_toolkit()`, which already names the real root in its refusal
for the same reason; and it is not a regression, because before the restructure
these messages printed a bare filename with no path at all, which ran from
nowhere.

The cost, stated plainly: the documented install is a clone, where the link path
and the real path coincide and none of this is visible. It surfaces only for
someone who has mounted the toolkit through a link — who is precisely the reader
least likely to recognise the directory they are handed — and a command pasted
out of such a message goes stale if the link is later re-pointed. Resolving it
would mean threading the invoked path through from `sys.argv[0]`, which is more
machinery than the problem currently justifies. Revisit if link installs become
the common case rather than the exception.

**The UnityFS reader was NOT hoisted to a shared engine layer.**
`sources/liftoff/unityfs.py` holds a general UnityFS/LZ4 bundle reader that
would serve any Unity-based sim, and `scene.py` reaches into it by private name
for `_cstr` and `lz4_block`. Promoting it is deferred until a second Unity sim
actually exists, because generalising against one example is how the wrong
abstraction gets frozen in. When that sim lands, this is the file to promote.

**`load_flight()` returns four values, not three:**
`(SessionMeta, FlightSeries, LapSet, meta)`. The fourth is the sim's raw metadata
dict, and it travels because `report.py` writes it verbatim into
`analysis.json`'s `meta` key — a published record read by later tooling, so
reshaping it would be a change to the output rather than to the architecture.
`SessionMeta` is the typed view of the same data.

**`FlightSeries.sample_dt` is declared but not populated by the Liftoff source.**
The measured median interval is computed downstream by `analysis.sample_dt()`,
which remains the authority. Moving where that number comes from would have been
a behaviour change inside a migration whose whole claim is that it has none.
Unifying them is a follow-up. There is exactly one implementation of the median.

**A precision-parity measure existed for the length of the migration, and was
removed within it.** Before the move, the analysis read `flight.csv` — written
with `round(x, 6)` — while the incident view and the crash table read the same
flight at full double precision from memory. The pipeline ran at two precisions
at once. Collapsing both onto one `FlightSeries` had to shift one of them, which
would have produced 7th-significant-digit differences across most of
`analysis.json` at exactly the moment the migration needed to prove it changed
nothing.

So for the duration of the migration `analysis.load()` quantised each field with
`round(v, 6)` as it read, exactly reproducing the CSV round-trip — an exact equivalence, not an approximation:
`csv.writer` emits `repr()` of the rounded float and `float()` of that string
returns the identical double. It was verified across 310,637 values including
adversarial 6-decimal ties, signed zero, denormals and random 64-bit patterns,
compared as packed doubles, with zero mismatches; and again on 107,253 values
from four real replays against the pre-migration code.

The measure sat in two places — `analysis.load()` and the nose bearing in
`report.py`'s `load_samples()` — and **only** there. Hoisting it into
`schema.py` or `source.load_flight()` would have changed the crash-table and
incident-view numbers instead: the same regression in the opposite direction,
and harder to spot.

**It has been removed, and the removal is part of this change rather than a wart
left behind it.** It existed for the five commits of the migration; a sixth
deleted both sites and nothing else, so that the numeric change is attributable
to one decision and to nothing in the restructure. The analysis now runs at one
precision — full double — and so does everything downstream of it.

What that removal actually moved, measured on the four verification replays:

- **85% of the analysis's in-memory float values changed** (78,279 of 91,681),
  which is the expected consequence of removing a quantisation and is the
  evidence that the measure had really been doing something.
- **Nothing in `analysis.json` changed at all.** Every value there is rounded on
  the way out — speeds to whole km/h, angles to a decimal — and the shift is far
  below that. The published record is insensitive to it.
- **45 of 99,385 numeric tokens across the generated SVGs moved**, every one by
  0.1 in the last printed decimal: coordinates that had been sitting on a
  rounding boundary. No figure changed structurally.
- **No verdict changed.** Not one stall reclassified, no crash appeared or
  disappeared, and the recording counts held at 1 / 0 / 2 / 11 — including the
  knife-edge case whose single impact measures 20.2 km/h against a 20.0 km/h
  threshold, which was the flip most likely to happen and did not.

The largest absolute movements were 0.09° of tilt, 0.002°/s of turn rate and
0.002 m of turn radius; every other field moved by less than 10⁻⁶ of its unit.
So the numbers are now marginally more faithful to the flight, and no
conclusion the tool draws rests on the difference.

**`flight.csv` keeps its six-decimal serialisation permanently** — it is the
readable, diffable interchange artifact, full precision there was explicitly
declined, and it was verified byte-identical across the removal. Only the
in-memory analysis path went to full precision.

**Degradation is declared and published; the consuming half is provided and not
yet called.** A sim declares what it cannot supply (`capabilities.py`), and
`cli.py` writes that declaration into `analysis.json` as one additive top-level
key on every report. That half runs on every run.

The other half does not. `common/capabilities.py` provides `gap()` and `has()`
so that a stage meeting a declared gap can name it rather than infer a value,
and nothing calls either function today. That is correct rather than
unfinished: Liftoff declares no gap that suppresses a finding the report makes,
so no stage has anything to consult, and `gaps_named_in_this_run` is `[]` in
every report this repository has produced. The rule — name a declared gap,
never infer past it — is the standard this project holds itself to, and the
machinery for it is in place, waiting for the first sim that needs it. Read it
as provided, not as running.

For Liftoff this changes nothing in `report.md` or `report.html`.

**`analyze_flight.py` was already standard-library-only with no Liftoff import at
any line**, so criterion 10 was achievable rather than aspirational. The analysis
was already sim-agnostic in its dependencies; this migration makes that
structural rather than accidental.

**The first real second sim will change this contract.** Every field in
`schema.py` is traced to a reader that exists today; nothing was added because a
hypothetical sim might have it. That is a deliberate trade: the contract is
minimal and honest now, and it will need revision when a second sim's actual
capabilities are known. That is expected, not a failure.

## Module mapping

Rename for rename, as it is on disk.

| from `scripts/` | to |
|---|---|
| `liftoff_replay.py` | `sources/liftoff/replay.py` — decode, archive, discovery, `DEFAULT_ROOT`. **Split:** `mounted_via_link` / toolkit root / `refuse_inside_toolkit` → `common/toolkit.py`; `add_velocity` → `common/kinematics.py`; `COLUMNS` → `common/schema.py` |
| `liftoff_tracks.py` | `sources/liftoff/tracks.py`. **Split:** the bundle reader (`lz4_block`, `_cstr`, `bundle_payload`, `text_assets`, `_serialized_text_assets`, `normalise_xml`, `_root_tag`, `locate`, `CLASS_TEXTASSET`, `MAX_BUNDLE_MB`) → `sources/liftoff/unityfs.py` |
| `liftoff_scene.py` | `sources/liftoff/scene.py`. **Split:** `qmul`, `qrot`, `bounds_of`, `contains_point`, `path_inside`, `cull` → `common/geometry.py` |
| `liftoff_props.py` | `sources/liftoff/props.py` (moves whole) |
| `liftoff_view.py` | `common/incident_view.py` (`impacts`, `window_indices`, `window_points`, `build`, `page`, `VIEWER_JS`, `PAGE`). **Split:** `props_near` → `sources/liftoff/map_geometry_generator.py`; `IMPACT_DROP_KMH`, the impact debounce and `PROP_NOMINAL` → `sources/liftoff/calibration.py`; `main()` → `cli.py` |
| `analyze_flight.py` | `common/analysis.py`. **Split:** the 20 threshold default *values* → `sources/liftoff/calibration.py`; `main()` → `cli.py` |
| `fpv_report.py` | `common/report.py`. **Split:** `main()` → `cli.py`; `pb_context` → `common/pbs.py`; **`geometry_for` → `sources/liftoff/map_geometry_generator.py`** (it reads Liftoff's track XML, so it could not stay in `common/`) |
| `liftoff_pbs.py` | `sources/liftoff/pbs.py` (`DEFAULT_ROOT`, `track_names`, `parse_times`, `snapshot`). **Split:** `fmt`, `diff_line` and the history store → `common/pbs.py`; `main()` → `cli.py` |
| `liftoff_telemetry.py` | `sources/liftoff/telemetry.py` (moves whole) |
| `scripts/README.md` | `docs/engineering.md` |

New with no predecessor: `common/schema.py`'s dataclasses, `common/capabilities.py`,
`sources/liftoff/{source,capabilities,calibration,map_geometry_generator}.py`,
`cli.py`, `src/__main__.py`, `pyproject.toml`, this ADR.

`map_geometry_generator.py` is a **façade**, not a rename of `tracks.py`. "The
map" is assembled from tracks (gates, route, blueprint placements), scene (world
colliders) and props (collider shapes); making it the single geometry surface
that delegates to all three is what makes the per-sim contract stateable.
Renaming `tracks.py` would have named a third of the job. It receives functions
from two origin files, as `common/pbs.py` receives from two.
