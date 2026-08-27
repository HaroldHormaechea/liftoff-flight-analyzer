# Liftoff flight analysis tools

Turn a Liftoff: FPV Drone Racing flight into coaching data.

**No dependencies.** Python 3.9+ and the standard library. Nothing to install,
nothing to pin, portable to any machine as a folder copy.

| script | what it does |
|---|---|
| `fpv_report.py` | **the normal entry point** — replay in, illustrated Markdown debrief out |
| `liftoff_replay.py` | archive + decode a saved in-game replay to CSV |
| `analyze_flight.py` | flight geometry: sideslip, tilt, turn radius, corners, yaw-only time, and stalls classified as overrun / corner / hesitation |
| `liftoff_pbs.py` | personal bests per track, with snapshot history |
| `liftoff_telemetry.py` | live UDP feed at 100 Hz — only source of gyro/RPM |

## The normal run

```bash
python fpv_report.py --latest        # archive, decode, analyse, draw, write
python liftoff_pbs.py --save
```

That writes `reports/<replay-stem>/`:

| file | for whom |
|---|---|
| `report.md` | the pilot reads it; the Debrief is written into it by hand |
| `report.html` | the same report, double-clickable, animations playing |
| `analysis.json` | **everything**, including what the report leaves out |
| `flight.csv` | the decoded per-sample data |
| `assets/*.svg` | figures and animated replays |

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

Header, **Debrief**, **Data analysis**, **Lap times**, **Circuit path**,
**Flight playback**, **Numbers**, then everything else collapsed. The debrief
leads because it is the answer, and everything after it is the evidence for the
answer — which only gets read when the answer provokes a question.

Disclosure uses plain `<details>`, so one construct works in the `.md`, in the
generated `.html`, in the VS Code preview and on GitHub, with no JavaScript.

For a quick number mid-conversation, the two lower-level steps still work on
their own:

```bash
python liftoff_replay.py --latest --archive-dir replays -o flight.csv
python analyze_flight.py flight.csv --laps "73:1077,1077:1768"
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
save destroys the previous one. `liftoff_replay.py` therefore copies to a
timestamped name *before* decoding, and decodes the copy. The archive is the
durable record; `Recordings/` is scratch space.

**Personal bests are a ratchet.** `raceTimes.xml` and `lapTimes.xml` are
overwritten in place, so a beaten time is gone. `liftoff_pbs.py --save` snapshots
them to `data/liftoff_history.json`. Run it every session — it is also the only
way to see flights that were never saved as replays.

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

## What analyze_flight.py measures

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

## Live telemetry — dormant, kept deliberately

`liftoff_telemetry.py` receives Liftoff's UDP stream: everything the replay has,
at 100 Hz, plus gyro, battery and motor RPM. It must be running during the
flight, which is why replays are the default source instead.

It is kept for two reasons: gyro and motor RPM are unreachable any other way and
are what tuning questions need, and the endpoint is already enabled on this
machine via `TelemetryConfiguration.json` (`127.0.0.1:9001`), so deleting the
receiver would orphan a live config. Delete both together or neither.

```bash
python liftoff_telemetry.py --probe          # confirm the feed
python liftoff_telemetry.py -o flight.csv    # record until Ctrl+C
```

## The report

`fpv_report.py` is the reason the other scripts exist. It embeds
`analyze_flight.py` rather than re-deriving anything — it calls `build_parser()`
for the thresholds and `analyse()` for the numbers — so a figure and a table can
never disagree, and a threshold added there reaches both.

It writes what happened and stops. `## Debrief` is left empty deliberately: a
generated sentence can say a number is large, but only a person knows whether
the pilot was already told about it last session, which is the whole difference
between coaching and nagging.

### Figures

| figure | what it answers |
|---|---|
| `timeline.svg` | where the time went — lap bars, stalls in red, against the best ever lap |
| `track.svg` | the line coloured by speed, one panel per lap, stalls pinned |
| `line.svg` | laps overlaid — a line difference, which no stick technique fixes |
| `traces.svg` | speed, sideslip, tilt, sticks, throttle on one clock, stalls banded |
| `corners.svg` | tilt against sideslip, plus throttle added per corner |
| `anim_lap*.svg` | the lap played back, with a follow cam |
| `anim_stall_*.svg` | each stall played back, ±4 s of context |

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
  column. `analyze_flight` leaves sideslip undefined below `--speed-floor`
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
