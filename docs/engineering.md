# Liftoff flight analysis tools

Turn a Liftoff: FPV Drone Racing flight into coaching data.

**The analysis path has no dependencies.** Python 3.9+ and the standard library:
decoding a replay, measuring a flight, writing a report, extracting the track
XMLs. Nothing to install, nothing to pin, portable as a folder copy.

**Two commands need `UnityPy`, and only when building a cache.** `scene`
and `props` read the game's compiled scene and prefab bundles, which
means generic Unity object parsing and, for collision meshes, vertex buffer
decoding. That is disproportionate to hand-roll for a step that runs once per
environment per game patch. What they produce is plain JSON, so everything that
*reads* a cache still needs nothing.

| command — module | what it does | needs |
|---|---|---|
| `report` — `common/report.py` | **the normal entry point** — replay in, illustrated Markdown debrief out | — |
| `replay` — `sources/liftoff/replay.py` | archive + decode a saved in-game replay to CSV | — |
| `analyse` — `common/analysis.py` | flight geometry: sideslip, tilt, turn radius, corners, yaw-only time, and stalls classified as overrun / corner / hesitation | — |
| `pbs` — `sources/liftoff/pbs.py` + `common/pbs.py` | personal bests per track, with snapshot history | — |
| `tracks` — `sources/liftoff/tracks.py` | extract the game's track and race geometry: where the gates are | — |
| `scene` — `sources/liftoff/scene.py` | an environment's collision geometry, and the cull to one incident | UnityPy |
| `props` — `sources/liftoff/props.py` | collider shapes for the items a track is built from | UnityPy |
| `view` — `common/incident_view.py` | the 3D incident view: geometry, path, orbit, scrub — as its own page, and as the recordings inside a report | — |
| `telemetry` — `sources/liftoff/telemetry.py` | live UDP feed at 100 Hz — only source of gyro/RPM | — |


### Where the code lives

```
SKILL.md                    the orchestration layer Claude Code loads
pyproject.toml              metadata only; also a marker for the toolkit-root search
src/__main__.py             the front door: python "<clone>/src" <command>
src/fpv_review/cli.py       the wiring layer, and the only module importing both trees
src/fpv_review/common/      sim-agnostic: schema, analysis, report, incident view
src/fpv_review/sources/     one package per sim; today only liftoff/
docs/adr/                   the decisions, with the alternatives they beat
```

The import rule is the architecture: `common/` may import `common/` and the
standard library; `sources/<sim>/` may import `common/` and its own siblings,
never another sim; `cli.py` is the only module allowed to import both. See
[`adr/0001-multi-sim-architecture.md`](adr/0001-multi-sim-architecture.md).

## The normal run

```bash
# $FPV is wherever this repository was cloned. Every command below uses it;
# in PowerShell the same lines work with backslashes and $FPV set the same way.
FPV="$HOME/.claude/skills/fpv-review"

python "$FPV/src" tracks --check     # first: is the track geometry present and current?
python "$FPV/src" report --latest        # archive, decode, analyse, draw, write, show
python "$FPV/src" pbs --save
```

`report.html` opens in the default browser when it is written. The report is the
deliverable, and a path printed to a terminal is not one. `--no-open` suppresses
it, for a batch run or for the regeneration that only exists to pick up a
hand-written Debrief.

That writes `reports/<replay-stem>/`:

| file | for whom |
|---|---|
| `report.md` | the pilot reads it; the Debrief is written into it by hand |
| `report.html` | the same report, double-clickable, animations playing, crash and stall recordings inside it |
| `analysis.json` | **everything**, including what the report leaves out |
| `flight.csv` | the decoded per-sample data |
| `assets/*.svg` | figures and the animated lap replays |

Lap boundaries come from the replay metadata, so nothing has to be worked out by
hand. Untimed flying either side of the laps that finished gets its own segment
when it contains real flying — which is how a run that ends in a crash keeps the
crash, since `lapTimes` only describes laps that completed.

### report.md is a summary; analysis.json is the record

The report is an argument made to a person, and it edits itself down to make
that argument: sections are collapsed, two trace panels are moved out of the
way, numbers are rounded to what a reader can hold. `analysis.json` is a
deliberate superset — every segment statistic, every corner, every stall, the
generated findings, the exact thresholds that produced them, the measured sample
rate, the lap index boundaries, and a `not_in_report` list naming what was left
out and where it lives instead.

So a later reader — usually a language model picking the work back up — reads
the JSON, never re-derives from the CSV what has already been computed, and
never has to guess which threshold produced a number.

### Section order

Header, **Debrief**, **Data analysis**, **Lap times**, **Flight playback**,
**Highlights and recordings**, then everything else collapsed. The debrief
leads because it is the answer, and everything after it is the evidence for the
answer — which only gets read when the answer provokes a question.

Flight playback holds one collapsed entry per lap, plus `line.svg` as a last
entry. Disclosure uses plain `<details>`, so one construct works in the `.md`, in
the generated `.html`, in the VS Code preview and on GitHub, with no JavaScript.

There is no per-lap track figure. It drew the same path in the same speed colours
as the overview map inside that lap's own animation, and a report that shows one
flight twice teaches the reader to skim. `line.svg` survives the same cull
because it answers a different question — where the *line* moved between laps —
and it is the one thing the playback cannot show, the playback being always one
lap.

### Recordings of the crashes and the stalls

A crash and a stall are the two moments a pilot wants to look at again, and a
table row describing one is not a look at it. So the **Highlights and
recordings** section leads with the Crashes table, then Stalls — both open on
arrival — and only then the numbers behind them. Every row in those two tables
carries a play control on the row itself — an icon captioned
*view recording* — and it opens the 3D incident view for that moment in a window
inside the page: the environment, the track props, the flown path coloured by
speed, the quad at its true attitude, every impact marked. Orbit, zoom, scrub,
play, close.

- **The renderer is `common/incident_view.py`, imported.** `build()` cuts the window and
  `VIEWER_JS` draws it, for the standalone page and for the report alike. There
  is one projection, one playback loop, and one place to fix either.
- **Crashes are found in the trajectory.** Twenty km/h or more lost inside one
  0.1 s sample is not something braking does. The replay's `isCrashed` flag is
  not used at all: it reads *false* on a run that ended pinned against the
  ground at full throttle. The table also names the nearest **solid** track prop
  to the impact, which is usually the answer to what was hit.
- **Geometry is best-effort, and says so.** An environment's colliders exist only
  once its scene bundle has been cached, and prop shapes only once the prefabs
  have been. A recording without them still draws the path, the attitude and the
  impacts — all from the replay — and prints what is missing in its own footer
  rather than quietly showing a crash into clear air.
- **It is a window in the page, not a browser pop-up**, in the report's own
  palette. A real pop-up loses the palette, the scroll position and, in most
  browsers, the click that asked for it.
- **One window, and pooled geometry.** Only one recording is ever being watched,
  so there is one canvas, built on click. Colliders and props are shared across
  recordings and referenced by index, because incidents cluster — two impacts
  0.7 s apart cull almost the same geometry twice.

`--no-rec` skips the recordings; `--track-dir`, `--scenes`, `--props` say where
the caches are, and `--rec-radius` how many metres of environment to include.

### Tabs, in the HTML only

`add_tabs()` wraps each `<h2>` section in a `<section class="panel">` and emits a
`role="tablist"` row directly under the race header. The Debrief is open on
arrival, because it is still the first section — the tab row changes how much of
the report is on screen, not what the report argues.

Three things are deliberate:

- **It runs after `add_expand_all()`.** Both split on `<h2>`, so they agree about
  what a section is by construction, and taking the tab label from the text
  before the expand-all button leaves that button inside the panel holding the
  disclosures it opens.
- **The trailing rule and provenance line are lifted out of the last section**
  and left below the panels. They describe the whole report, and nobody should
  have to guess which tab names the replay it came from.
- **Everything is gated on a `.js` class** set by an inline script in `<head>`.
  Without JavaScript the nav never appears and the page is the single scroll it
  always was, so nothing is reachable only through a control that is not running;
  gating in CSS rather than hiding panels on load also avoids a flash of the
  whole report before it collapses to one tab. `@media print` restores every
  panel, because paper has no tabs.

The active tab is written to the fragment with `history.replaceState`, so
`report.html#highlights-and-recordings` deep-links and the back button still
leaves the report
rather than walking back through tab clicks. Arrow keys, Home and End move
between tabs.

As with expand-all, this is done by the converter and not by `build_report()`:
`report.md` stays one linear Markdown document.

The generated HTML adds an **expand all / collapse all** control to any section
holding two or more disclosures. That is done by the converter and not by
`build_report()`, on purpose: `report.md` stays clean Markdown, because the
affordance belongs to the rendered page and the source should not carry a button
only one of its two renderings can use.

For a quick number mid-conversation, the two lower-level steps still work on
their own:

```bash
python "$FPV/src" replay --latest --archive-dir replays -o flight.csv
python "$FPV/src" analyse flight.csv --laps "73:1077,1077:1768"
```

Lap ranges are sample indices, from the replay metadata: `lapStartIndices[i]` to
that plus `lapTimes[i] * 10` (the replay samples at 10 Hz).

## Where Liftoff keeps things

    <LocalLow>/LuGus Studios/Liftoff/
      Recordings/<GameMode>/<name>.xml   saved replays  -- VOLATILE, see below
      RaceTimes/raceTimes.xml            best + average race time per track
      LapTimes/lapTimes.xml              five best laps + average per track
      Player.log                         content catalogue, GUID -> name

On Windows `<LocalLow>` is `%USERPROFILE%/AppData/LocalLow`.

**Replays are volatile.** Liftoff names a replay after its track and its total
time, so every abandoned attempt on one track lands on the same filename and each
save destroys the previous one. The `replay` decoder therefore copies to a
timestamped name *before* decoding, and decodes the copy. The archive is the
durable record; `Recordings/` is scratch space.

**Personal bests are a ratchet.** `raceTimes.xml` and `lapTimes.xml` are
overwritten in place, so a beaten time is gone. `pbs --save` snapshots
them to `data/liftoff_history.json`. Run it every session — it is also the only
way to see flights that were never saved as replays.

## Track geometry

A replay says where the quad went. It does not say where the track was. Without
the gates, "he went wide" is an opinion; with them it is a lateral offset
through a 2.45 m aperture.

The `tracks` command finds the Liftoff install — every Steam library named by the
registry and `libraryfolders.vdf`, or `--game-dir` / `$LIFTOFF_DIR` — and writes
the game's own track and race XMLs out of its Unity bundles into `trackdata/`,
about five seconds for all 184.

```bash
python "$FPV/src" tracks --check                          # ready? exit 1 if not
python "$FPV/src" tracks                                  # rebuild; no-op if current
python "$FPV/src" tracks --for-replay replays/<file>.xml  # which track was flown
python "$FPV/src" tracks --gates "03 - Stuff That Works"  # the route, with geometry
python "$FPV/src" tracks --list                           # every track, by environment
```

**The extracted XMLs are game assets: gitignored, never committed, never
hand-edited.** Only the script is versioned. They are cheap to regenerate and
the next rebuild overwrites them.

**Always `--check` first.** Bundle filenames are content hashes, so a game patch
leaves the extracted XMLs silently describing a layout the game no longer has.
The check compares the recorded bundle fingerprint and Steam build id against
what is installed. Stale gates are worse than no gates: they produce confident,
wrong numbers.

`index.json` is the join table, keyed by the `localID` GUIDs a replay records —
which is what makes `--for-replay` a lookup rather than a guess. Matching on the
environment name cannot work: an environment holds five or six tracks that all
share it.

Positions are Unity world space, left-handed, +Y up, metres — **the same frame
the replay records**, so a gate and a flight path compare with no
transformation. For an item at yaw `r` the normal is `(sin r, 0, cos r)` and the
width axis is `(cos r, 0, -sin r)`.

Two things that will bite a naive reader:

* **Which items are gates is the race's decision, not the track's.** A
  checkpoint is any blueprint the route names by `instanceID`, of any subtype.
  On Bardwells Yard every one is a plain inflatable arch; on HangarC03 the route
  mixes truss gates, a fixed 5×5 box and three resizable checkpoints. Filtering a
  track's blueprints by `xsi:type` to enumerate "the gates" finds three of the
  ten. Resolve the route. It is a lap, so it ends back on the checkpoint it
  started from.
* **A checkpoint is a scoring volume, not a hole.** The two are independent and
  the environment can obstruct any part of one. On HangarC03 the gate 31
  checkpoint centre sits 0.51 m inside a closed container door: aim at the middle
  of the gate and you fly into solid geometry. Anything that emits a racing line
  has to intersect apertures against scene colliders first — and this script does
  not extract colliders, only the track layout.

`aperture` is present only on the resizable subtypes, whose prefabs are
unit-sized so their `scale` *is* the opening in metres. Everything else is a
fixed prefab whose opening is baked into the model, and sizing one means
measuring its collider in the scene bundle.

## Collision geometry, and the 3D incident view

`tracks` says where the gates are. `scene` and
`props` say where the *world* is — what a crash actually hit.

```bash
python "$FPV/src" scene --environment LiftoffArena --witness replays/<a flight there>.xml
python "$FPV/src" props
python "$FPV/src" view --replay replays/<crash>.xml -o crash.html
```

Cache an environment once and every later report of a flight there gets its
geometry for free, in the recordings behind the crash and stall tables. Without
the caches those recordings still work; they just draw fewer things and say so.

Three sources, because a track is assembled from three:

| | holds | from |
|---|---|---|
| scene cache | the static environment: walls, floors, structures | the environment's scene bundle |
| prop table | the shape of every item a track places, in the item's own frame | the prefab bundles |
| Track XML | where each item sits, and its yaw | `tracks` |

**The scene alone is not enough, and this is the trap.** Track props are placed
by the Track XML and instantiated at runtime, so they are *not* in the scene
bundle. The reference crash hit a ramp 2.30 m away and a crowd barrier 2.46 m
away, while the nearest scene collider was 8 m off — drawn from the scene alone
that crash looks like the quad stopping in clear air.

**Identifying an environment's scene bundle needs a flight.** Bundle names are
content hashes, and every environment is authored around the world origin at
similar scale, so gate positions match almost any scene — ranking by them picks
the *wrong* bundle for HangarC03, whose answer is known independently. What
works is a flight as a witness to free space: reject any scene the path flies
through, then rank the survivors by gate proximity. Validated on both
environments where the truth is known. `--bundle` skips it when you already know.

Three things that are easy to get wrong, all of which were:

* **Trigger volumes are not solid.** An inflatable arch contains a 6.18 × 3.69 m
  box — the scoring volume, not the arch. Drawn as geometry it is a wall across
  the gate, and left in the scene cache it corrupts the free-space test above.
  Both extractors now flag `m_IsTrigger` and drop them from solids.
* **A prefab name appears on several GameObjects** — variants, nested copies, LOD
  holders — and only one owns the colliders. Taking the first silently produced
  an empty shape for the commonest prop on the track.
* **A mesh collider's bounding box is not its shape.** A ramp's hull is two
  triangles (`TriangleCollider02`, and the game's own typo `TraingleCollider01`);
  its AABB is a slab with two vertical walls that do not exist. Real triangles
  are decoded; the AABB is a marked last resort.

Still not extracted: scene MeshColliders and TerrainColliders. Outdoor grounds
live in those, so an outdoor scene renders its obstacles over no floor. A scene
reports what it skipped, and the incident view says so on the page.

### Why this parses Unity bundles by hand

UnityPy does it in ten lines, and pulls in a heavy dependency with an unstable
API that also needs `FALLBACK_UNITY_VERSION` set by hand, because these bundles
carry no usable version string. Everything else here is standard library and
portable as a folder copy, and the one moment this script is needed — the game
just updated and the gates are stale — is the worst possible moment to discover
a dependency is missing. The UnityFS reader inside it covers exactly what
Liftoff ships: UnityFS v6–8, LZ4/LZ4HC or uncompressed blocks, SerializedFile
v17–22. Its output was verified byte-identical to UnityPy's across all 184
assets.

## Replay format

Reverse-engineered on 2026-08-26 from game version 1.7.5, and verified against
the live telemetry feed.

The XML carries `environment`, `gamemode`, `trackID`, `raceID`, `isCrashed`, the
full `droneConfiguration` (rates, expo, PIDs), and — for runs that completed a
lap — `lapTimes` and `lapStartIndices`. The flight itself is `statesByte`, a
base64 block of fixed-size records described by `stateLayout`.

For `stateLayout = POSITION_STICKS`, each record is 48 bytes, 12 little-endian
floats, sampled at 10 Hz:

    [0:3]   position x, y, z      world metres, y up
    [3:7]   attitude quaternion   x, y, z, w
    [7:11]  throttle, yaw, pitch, roll
    [11]    timestamp             seconds, session clock

Throttle is 0..1; the other three axes are -1..+1. The axis order was confirmed,
not guessed: one flight was captured simultaneously as a replay and as a live UDP
telemetry stream, and across 1575 moving samples with exact position matches the
yaw/pitch/roll channels agreed to within 0.04 — the 10 Hz versus 100 Hz sampling
offset. Throttle is the same signal on a different scale, `telemetry = 2 *
replay - 1`.

A run with empty `lapTimes` and a `00_00_000` name is an abandoned attempt. Still
analysable as one segment, just not lap by lap.

## What the analysis measures

* **Sideslip** — the signed angle between where the nose points and where the
  quad is travelling. The key diagnostic: yawing faster than bank-plus-throttle
  bends the path means pointing into the turn while still moving outward. Under
  ~10° is coordinated, 30+ is a skid, near 90 is travelling sideways with no lift
  authority left.
* **Tilt** — the thrust axis off vertical. On a quad this *is* the turning force,
  so it is the honest measure of commitment in a corner.
* **Turn radius** — speed over turn rate. Separates a committed arc from a flat
  yaw-around.
* **Throttle delta through the corner** — bank sets the direction of the turning
  force, throttle sets its magnitude. A corner flown without adding throttle goes
  wide and sinks.

* **Yaw-only time** — time with commanded yaw held while roll stays at zero. A
  turn flown on yaw alone is a pirouette: the airframe rotates, the path does
  not bend. Reported whole-segment and by speed band, because the fault appears
  as yaw authority rising while roll authority stays flat as speed drops.

Corners are runs of sustained turn rate above `--turn-threshold` (default 25°/s),
measured only above `--speed-floor` (default 15 km/h), because sideslip is
meaningless when nearly stationary.

## Stalls, and why each one happened

Anything below `--stall-speed` (default 10 km/h) is a stall. Finding them is
trivial; the value is saying WHY, which is a decision table, not a judgement:

| verdict | test |
|---|---|
| `overrun` | the path reverses and retraces itself — heading swings at least `--reversal-deg` **and** the recovery passes within `--retrace-m` of ground already covered |
| `corner` | another lap turns at least `--corner-deg` at the same coordinates — the track asked for the direction change |
| `hesitation` | another lap passes the same coordinates going essentially straight — nothing there needed a stop |

The cross-lap probe is the decisive test and needs no gate data: **if a different
lap flies the same coordinates straight through at speed, the event belongs to
the pilot, not the track.** It requires `--laps` with two or more laps. With one
lap, verdicts fall back to the reversal test and are printed with a `?`.

A stall more than `--offline-m` from the other lap's line is tagged `[OFF LINE]`
— a line error, not a stick error, and no change of technique fixes it.

Rules that keep the numbers honest, all deterministic:

* Sub-runs less than `--stall-gap` apart merge — one bounce back over the
  threshold is still one event.
* A run whose **median** throttle is under `--idle-throttle` is grid time or a
  dead quad, not a stall. Median, not peak: the grid wait ends with the pilot spooling
  up to launch, so a peak test passes the one episode it most needs to reject.
* An episode starting at the first sample is pre-launch, not a stall.
* Measurement windows are clamped to the neighbouring stalls. Two stalls four
  seconds apart would otherwise each measure heading across the other, and the
  answer would depend on how far apart they happened to fall. Where clamping
  leaves too few samples the field prints `-` and the verdict falls back to
  whatever evidence survives, rather than inventing a number.
* Every threshold is a CLI flag. Defaults were fixed against the Rustline 2-lap
  race of 2026-08-26, where the overruns measured retrace 0.3–0.4 m with 172–178°
  of reversal and everything else measured 7.4 m or more with 104° or less. Each
  default sits in the gap between those groups.
* `--trace` prints the sample-by-sample stick trace around each stall.

Sample rate is the **median** interval, never the first difference — Liftoff's
replay timestamps are irregular (0.003–0.197 s in one 2026-08-26 file), so a
first-difference estimate was silently scaling every duration by up to 1.9×.

Works on either input: replay CSV (10 Hz, velocity differentiated from position)
or telemetry CSV (100 Hz, velocity measured).

## Pit stops, and why they are not crashes

A track's blueprint list can hold `TriggerBoxRepairPropellers` and
`TriggerBoxChargeBattery` volumes — `TrackBlueprintAction` items whose `<action>`
child names the service. `ShowText` is the only other action shipped and is not a
pit. `tracks.pit_volumes()` resolves them to `{shape, pos, yaw, size}`: the
prefabs are unit-sized, so `scale` **is** the full extent in metres, and the
`TriggerBox_` / `TriggerSphere_` prefix is what says which containment test to
run. `geometry.inside_volume()` runs it — deliberately not `contains_point()`,
which takes the scene cache's already-halved, quaternion-rotated collider dict.

The way a pilot uses one is to fly in and **sit there**, which the impact
detector reads as hitting the ground, because it is hitting the ground. Two
false positives followed and both are now handled:

* **the crash.** An impact inside a pit volume that the quad flew out of again
  is a landing and goes to `pit_landings`. One it never flew out of stays in
  `crashes`: the drone was lost there, and a pit volume is not an exemption from
  that — it is only where it happened. The recovery test is the same speed the
  stall detector uses. Containment is tested over the second FOLLOWING the
  impact, not on the impact sample alone: a quad arriving fast touches down short
  of the volume and slides into it.
* **the stall.** A six-second repair tripped the stall detector and came back
  classified `hesitation` — a stop nothing on the track asked for. `drop_pit_stalls()`
  takes them out. The seconds are relabelled, not deleted: `slow_seconds` still
  counts them, because it measures the flight, and `pit_seconds` says how much of
  it the pilot chose. The findings line names the split rather than subtracting
  it.

A stop is reported as a **cost**, not a fault: an icon on every lap map and
playback where it happened, and one row at the foot of **Flight playback**
saying how long the visit was and how much of it was on the ground. It sat at the
foot of Highlights first and then beside the lap bars, and both were wrong for
the same reason: in the HTML those are different TABS from the maps that carry
the icons, so the table and the thing it annotates were never on screen together.
The seconds can move; the icons cannot. The icons are drawn paths, not characters — these
SVGs load through `<img>` and an emoji font is not a safe assumption.

Colour carries as much of it as shape does, because at 18 px across the shape
alone is doing a lot of work. `--charge` is green and `--repair` purple, matching
the pads in the game: a pilot who has just flown the track already knows that
mapping, and inventing a second one here would make them learn it twice. An
impact is `--crash`, a red disc with a white X, and it is the **same mark in
every view** — the lap maps, the playbacks and the canvas in the 3D recording —
so someone scanning a report for what went wrong is looking for one shape rather
than learning a different one per figure.

A stop is not the same thing as time inside the volume, and three durations are
reported rather than one: `seconds` (arrival to departure), `serviced_s` (the
part actually inside, which is the part that repaired or charged anything) and
`grounded_s`. Two runs inside the **same** volume join when the quad never got
airborne between them — it never left, it was fumbling the approach. On the
2026-09-03 Hall26 recording the pilot arrived at the charge pad, overshot it by a
few centimetres, sat motionless just outside for three seconds and then nudged
back in; split on containment alone that reads as a 0.8 s stop and a 4.6 s stop
with three seconds of nothing between them — three seconds that were the most
expensive part of the stop and vanished from the pit accounting entirely. Joined,
it is one 8.4 s stop, 5.4 s of it servicing, and the 3.0 s difference is a
placement error with a number on it. Same volume deliberately: repair and
recharge pads sit side by side and flying from one to the other IS two stops.

`PIT_MIN_S` (0.5 s) separates a stop from a fly-through: a race line clips the
corner of a 3.7 m volume at 50 km/h for two samples, and marking that as a pit
stop puts an icon on the map for something that did not happen. It lives in
`calibration.py` because it is a duration of real flight tuned against Liftoff's
volume sizes, not a property of the report.

With no extracted track data there are no pit volumes, and every impact is
reported as an impact — which is what the tool did before any of this existed.

## Live telemetry — dormant, kept deliberately

The `telemetry` command receives Liftoff's UDP stream: everything the replay has,
at 100 Hz, plus gyro, battery and motor RPM. It must be running during the
flight, which is why replays are the default source instead.

It is kept for two reasons: gyro and motor RPM are unreachable any other way and
are what tuning questions need, and the endpoint is already enabled on this
machine via `TelemetryConfiguration.json` (`127.0.0.1:9001`), so deleting the
receiver would orphan a live config. Delete both together or neither.

```bash
python "$FPV/src" telemetry --probe          # confirm the feed
python "$FPV/src" telemetry -o flight.csv    # record until Ctrl+C
```

## The report

`common/report.py` is the reason the other modules exist. It embeds
`common/analysis.py` rather than re-deriving anything — it calls `build_parser()`
for the thresholds and `analyse()` for the numbers — so a figure and a table can
never disagree, and a threshold added there reaches both.

It writes what happened and stops. `## Debrief` is left empty deliberately: a
generated sentence can say a number is large, but only a person knows whether
the pilot was already told about it last session, which is the whole difference
between coaching and nagging.

`report.html` opens in the browser when it is written, unless `--no-auto-open`
is passed. Anything that writes the Debrief afterwards should pass it and open
the report itself: the automatic open fires at write time, so on a fresh report
it shows a page whose headline reads "TO BE WRITTEN", and the regeneration that
fills the Debrief in does not refresh that tab. `--no-open` is the older
spelling of the same flag.

The stub does scaffold the shape — an assessment, then a `### Recommendations`
subsection holding every instruction — because a debrief that mixes the two ends
up praising instead of instructing. `existing_debrief()` carries a hand-written
Debrief forward across regenerations and stops at the next `## ` heading, so the
`###` subsection travels with it.

### Figures

| figure | what it answers |
|---|---|
| `timeline.svg` | lap bars, stalls in red, against the best ever lap on that track |
| `line.svg` | laps overlaid — a line difference, which no stick technique fixes |
| `traces.svg` | speed, sideslip and throttle on one clock, stalls banded |
| `traces_extra.svg` | tilt and the stick inputs — collapsed in the report |
| `corners.svg` | tilt against sideslip, plus throttle added per corner |
| `anim_<segment>.svg` | one per lap: the lap played back, with a follow cam |
| `anim_stall_*.svg` | each stall played back, ±4 s of context |

There is deliberately **no per-lap track figure, no combined multi-panel track
figure and no whole-flight animation**. A figure that merges the laps, sitting in
a list beside the laps it merges, reads as one more lap; the way to see
everything at once is the expand-all control, not another entry. `line.svg` is
not an exception to that — it merges nothing, it compares. Do not add the others
back.

### Everything is standard library

Figures are hand-written SVG and the animations are SMIL. No matplotlib, no
Pillow, no ffmpeg, nothing to install, and the output is diffable text that
scales to any size. One file works on a light and a dark background, via CSS
custom properties inside a `prefers-color-scheme` media query.

Animated SVG plays in a browser and in the VS Code Markdown preview. Where it
does not play, every animation still reads as a static picture, because the
whole line and all the annotations are drawn underneath the animation.

### What the animations show, and why it is built this way

The moving marker carries a **nose arrow** and a dashed **direction-of-travel
ray** from one origin. The angle between them *is* the sideslip, so the fault is
visible instead of tabulated, and the arrow turns red past 30°.

Four decisions that are not arbitrary:

* **Position is `animateTransform translate`, not `animateMotion`.**
  `animateMotion` distributes frames along path *length*, which plays the slow
  parts fast — the exact opposite of what a debrief has to show.
* **The travel ray is hidden while the quad is stationary**, not frozen at its
  last bearing. A stopped quad has no direction of travel, and drawing one would
  be a lie at the moment the figure matters most.
* **The red flag is recomputed from raw geometry**, not read from the `slip`
  column. The analysis leaves sideslip undefined below `--speed-floor`
  because the *statistic* is meaningless down there — correct for a median, but
  the pirouette lives below that floor, and reusing the field would grey the
  arrow out exactly when it should be shouting.
* **The red arrow is a second arrow cross-faded on opacity**, not an animated
  `fill`. SMIL does not resolve a CSS `var()` inside an animation value, so
  animating `fill` would mean hard-coding hex and giving up the theme.

A **follow cam** repeats the flight magnified and centred on the quad, because
at whole-lap scale the nose-versus-travel gap is a few pixels wide.

Long segments are played back faster than real time — capped by `--anim-max`,
default 40 s — and the speed-up factor is printed on the figure.

### Colour

The speed ramp is red → amber → teal, deliberately not red → green: it stays
separable for the common colour-vision deficiencies and both ends hold contrast
on either background. It is scaled to the **p90** speed, not the maximum,
because against the maximum one fast straight pushes the whole working range of
the flight into two shades and the slow sections — the ones the debrief is
about — stop being visible.

## Not covered

Uncrashed, and any other sim. There is no HUD-scraping path here any more — it
existed for Liftoff before the replay format was cracked, and carried numpy,
Pillow, OpenCV and ffmpeg with it for a strictly worse signal. When Uncrashed
needs handling it should be designed for whatever Uncrashed actually exposes,
not by resurrecting that.
