# Liftoff flight analysis tools

Turn a Liftoff: FPV Drone Racing flight into coaching data.

**No dependencies.** Python 3.9+ and the standard library. Nothing to install,
nothing to pin, portable to any machine as a folder copy.

| script | what it does |
|---|---|
| `liftoff_replay.py` | archive + decode a saved in-game replay to CSV |
| `analyze_flight.py` | flight geometry: sideslip, tilt, turn radius, corners, yaw-only time, and stalls classified as overrun / corner / hesitation |
| `liftoff_pbs.py` | personal bests per track, with snapshot history |
| `liftoff_telemetry.py` | live UDP feed at 100 Hz — only source of gyro/RPM |

## The normal run

```bash
python liftoff_replay.py --latest --archive-dir ../replays -o flight.csv
python analyze_flight.py flight.csv --laps "73:1077,1077:1768"
python liftoff_pbs.py --save
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
  dead quad, not a stall. Median, not peak: the grid wait ends with the pilot
  spooling up to launch, so a peak test passes the one episode it most needs to reject.
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
are what tuning questions need, and it is enabled game-side via
`TelemetryConfiguration.json` (default `127.0.0.1:9001`), so the receiver and
that config belong together. Delete both or neither.

```bash
python liftoff_telemetry.py --probe          # confirm the feed
python liftoff_telemetry.py -o flight.csv    # record until Ctrl+C
```

## Not covered

Uncrashed, and any other sim. There is no HUD-scraping path here any more — it
existed for Liftoff before the replay format was cracked, and carried numpy,
Pillow, OpenCV and ffmpeg with it for a strictly worse signal. When Uncrashed
needs handling it should be designed for whatever Uncrashed actually exposes,
not by resurrecting that.
