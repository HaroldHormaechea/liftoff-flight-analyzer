---
name: liftoff-flight-analyzer
description: Analyse a Liftoff FPV drone sim flight and coach the pilot on it. Use when they ask to evaluate, review or debrief a flight, lap or race, save an in-game recording, or ask how a session went.
---

# Liftoff flight review

**Ask for a saved in-game replay. That is the whole data pipeline.**

Liftoff's "save recording" writes a parseable XML holding position, attitude and
stick positions at 10 Hz, plus the track, race, drone setup and lap times. It is
saved *after* the flight, so nothing has to be running beforehand, and it names
its own track. Everything below flows from it.

If there is no replay for a flight, the flight is not analysable — say so and ask
for the next one to be saved. Do not fall back to reading a screen recording. A
HUD-scraping path existed here before the replay format was decoded and it was
strictly worse: 71-79% OCR read rate and stick positions estimated from a 170px
overlay, versus exact values at 10 Hz.

Only Liftoff is handled. Other sims (Uncrashed, Velocidrone, DCL) expose
different data or none at all; design for what they actually expose rather than
assuming this pipeline transfers.

## Step 1 — decode the replay

```bash
S=scripts
python $S/liftoff_replay.py --list
python $S/liftoff_replay.py --latest --archive-dir replays -o flight.csv
```

Replays live in `<LocalLow>/LuGus Studios/Liftoff/Recordings/<GameMode>/`.

**Always pass `--archive-dir`.** Liftoff names a replay after its track and total
time, so every abandoned attempt on a track collides on one filename and each
save destroys the previous one. The script copies the replay to
`<timestamp>_<environment>_<mode>_<Nlap>.xml` BEFORE decoding, then decodes the
copy, so an analysis always refers to a file that still exists. It is idempotent,
so re-running is safe.

Read the metadata it prints. `lapTimes` and `lapStartIndices` are populated only
for runs that completed a lap; they give exact per-lap sample boundaries. A run
with neither and a `00_00_000` name is an abandoned attempt — still analysable as
one segment, just not lap-by-lap.

Archived replays are the durable record. `Recordings/` is scratch space that
Liftoff overwrites.

## Step 2 — analyse the geometry

```bash
python $S/analyze_flight.py flight.csv --laps "73:1077,1077:1768"
```

Lap ranges are sample indices: `lapStartIndices[0]` to that plus
`lapTimes[0] * 10`, and so on. Without `--laps` it treats the flight as one
segment, and the cross-lap stall probe degrades to the reversal test only.

What to read:

- **`sideslip`** — the angle between where the nose points and where the quad is
  actually going. Under ~10 deg is coordinated, 30+ is a skid, near 90 means
  travelling sideways with no lift authority left. A crash usually shows as
  sideslip climbing through 90 in the two seconds before speed collapses.
- **`yaw-only`** — time with commanded yaw held while roll stays at zero. A turn
  flown on yaw alone is a pirouette: the airframe rotates, the path does not
  bend. Reported by speed band, because the fault typically appears as yaw
  authority rising while roll authority stays flat as speed drops.
- **`stalls`** — every episode below 10 km/h, classified `overrun` (the path
  reversed and retraced itself), `corner` (another lap turns there too, so the
  track asked for it) or `hesitation` (another lap flies straight through). This
  is what turns "you were slow" into a cause.
- **`d_thr` per corner** — throttle added through the corner. Bank sets the
  direction of the turning force, throttle its magnitude, so a corner with no
  throttle increase goes wide and sinks.
- **`tilt` and `radius`** — a committed arc versus a flat yaw-around. Low tilt
  with a tiny radius and high sideslip is the failure pattern.
- **entry vs exit speed** — exit faster than entry is slow-in/fast-out working.

`--trace` prints the stick trace around each stall when a specific event needs
reconstructing frame by frame.

## Step 3 — the other sources, only when needed

- **`liftoff_pbs.py --save`** — personal bests per track, diffed against the last
  snapshot. Liftoff overwrites these in place, so a beaten time is gone unless
  snapshotted. Run it every session. It also reveals flights that were never
  recorded, which is often where the real progress is.
- **`liftoff_telemetry.py`** — live UDP feed, 100 Hz, and the only route to gyro,
  battery and motor RPM. It must be running during the flight. Reach for it for
  tuning-level questions (oscillation, propwash, PID feel), not for piloting
  technique, which 10 Hz covers. Enabled via `TelemetryConfiguration.json` in the
  Liftoff LocalLow folder, default endpoint `127.0.0.1:9001`.

## Step 4 — coach

Keep a notes file per pilot and read it before writing anything. Repeating advice
they have already absorbed reads as not having watched the flight, and the value
of this tool is almost entirely in tracking what changed since last time.

Coaching model that the measurements support:

- Bank sets the direction of the turning force, throttle sets its magnitude.
- Pitch is speed, throttle is height. Yaw follows the turn, it never leads it.
- A quad that stops to rotate has decomposed a corner into three manoeuvres —
  stop, pirouette, go. The turn and the travel must overlap.
- Pilots coming from fixed-wing sims have a rudder habit that reappears below
  roughly 25 km/h. Use the bridge — load factor, thrust vector, slow-in/fast-out
  — rather than teaching from zero.
- A stall tagged `[OFF LINE]` is a track-knowledge error, not a stick error. No
  change of technique fixes it; slow exploratory laps do.
- Late-session runs carry almost no diagnostic value. Do not debug fatigue.

Tone: lead with the number and the cause. Name **one** thing to fix and give
**one** drill. Do not stack three — a pilot who is given three fixes does none of
them, and the next flight's data cannot attribute a change to any of them.

## Step 5 — persist

Append a tight section to the notes file: date, what was flown, the measured
result, the diagnosis, and the single fix given. Compact prose, and cut
superseded detail as you go — the file is read in full at the start of every
review, so it has to stay cheap to read.
