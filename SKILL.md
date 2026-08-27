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

## The deliverable is an illustrated report, not a terminal dump

`fpv_report.py` writes a folder holding the report, its figures and animated
replays of every lap and every stall. That is what the pilot gets. The terminal
output of `analyze_flight.py` is for answering a quick question mid-conversation,
not for a review.

## Step 1 — build the report

```bash
S=scripts
python $S/fpv_report.py --latest                  # newest replay saved in-game
python $S/fpv_report.py replays/<file>.xml        # a specific archived one
```

`--latest` archives the replay before it reads anything, then writes
`reports/<replay-stem>/`:

    report.md          the debrief the pilot reads and you edit
    report.html        the same thing, double-clickable, animations playing
    analysis.json      EVERYTHING, including what the report leaves out
    flight.csv         the decoded per-sample data
    assets/*.svg       figures and animated replays

**`analysis.json` is the one you read, not `report.md`.** The report is an
argument made to a person: sections are collapsed, panels are dropped, numbers
are rounded. The JSON is a deliberate superset — every segment statistic, every
corner, every stall, the generated findings, the exact thresholds that produced
them, the measured sample rate, the lap index boundaries, and a `not_in_report`
list naming what was left out and where it lives instead. Never re-derive from
`flight.csv` what is already sitting in there.

Report structure, in reading order: a compact header, then **Debrief**, **Data
analysis**, **Lap times**, **Circuit path**, **Flight playback**, **Numbers**,
then everything else collapsed. The debrief leads because it is the answer, and
everything after it is the evidence — which only gets read when the answer
provokes a question.

**Archiving matters.** Liftoff names a replay after its track and total time, so
every abandoned attempt on a track collides on one filename and each save
destroys the previous one.

Lap boundaries come out of the replay metadata, so `--laps` is only needed for an
abandoned attempt worth splitting by hand. Untimed flying either side of the
timed laps gets its own segment when it contains real flying — which is how a run
that ends in a crash keeps the crash, since `lapTimes` only ever describes laps
that finished.

Useful flags: `--no-anim` when only the numbers are wanted, `--cam-span` for the
follow-cam width in metres, `--stall-pad` for context around a stall clip,
`--reset-debrief` to clear a hand-written debrief instead of carrying it forward.

## Step 2 — read the figures before writing a word

- **Lap times** — lap bars with the stalls marked in red, against the pilot's
  best ever lap on that track. Says immediately whether the deficit is pace or
  stops.
- **Circuit path** — the track coloured by speed, one figure per lap, stalls
  pinned. Where the time is lost, geographically. The overlay shows lap-to-lap
  line differences, which no change of stick technique can fix.
- **Flight playback** — nose arrow versus dashed direction-of-travel ray. The
  angle between them is the sideslip, and the arrow turns red past 30 degrees.
  The stall clips are where a fault becomes visible rather than tabulated.
- **Traces** — speed, sideslip and throttle on one clock, stalls banded. Tilt and
  the stick traces are a second figure, collapsed; open it when the question is
  about inputs rather than results.
- **Corner scorecard** — tilt against sideslip, plus throttle added per corner.
  Down and to the right is a committed, coordinated corner.

What to read in the numbers:

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

## Step 3 — write the Debrief section

The script fills in everything factual and leaves `## Debrief` empty on purpose.
It writes what happened; it does not write the coaching, because the diagnosis
depends on what the pilot has already been told and the script does not know
that. A generated sentence can say a number is large, but only a person knows
whether it is news.

Edit `report.md`, write that section, then re-run the script so `report.html`
picks it up. An existing debrief is carried forward on every regeneration, so
nothing is lost.

Read the pilot's notes file first. Repeating advice they have already absorbed
reads as not having watched the flight, and the value of this tool is almost
entirely in tracking what changed since last time.

Coaching model that the measurements support:

- Bank sets the direction of the turning force, throttle sets its magnitude.
- Pitch is speed, throttle is height. Yaw follows the turn, it never leads it.
- A quad that stops to rotate has decomposed a corner into three manoeuvres —
  stop, pirouette, go. The turn and the travel must overlap.
- Pilots coming from fixed-wing sims have a rudder habit that reappears below
  roughly 25 km/h. Use the bridge — load factor, thrust vector, slow-in/fast-out
  — rather than teaching from zero.
- A stall tagged off-line is a track-knowledge error, not a stick error. No
  change of technique fixes it; slow exploratory laps do.
- Late-session runs carry almost no diagnostic value. Do not debug fatigue.

Tone: lead with the number and the cause. Name **one** thing to fix and give
**one** drill. Do not stack three — a pilot who is given three fixes does none of
them, and the next flight's data cannot attribute a change to any of them.

Then say the same thing in chat, short, and link the report. Do not paste the
tables into the conversation; they are in the file.

## Step 4 — the other sources, only when needed

- **`liftoff_pbs.py --save`** — personal bests per track, diffed against the last
  snapshot. Liftoff overwrites these in place, so a beaten time is gone unless
  snapshotted. Run it every session. It also reveals flights that were never
  recorded, which is often where the real progress is, and it is what the
  report's "best ever" bar is drawn from.
- **`liftoff_telemetry.py`** — live UDP feed, 100 Hz, and the only route to gyro,
  battery and motor RPM. It must be running during the flight. Reach for it for
  tuning-level questions (oscillation, propwash, PID feel), not for piloting
  technique, which 10 Hz covers. Enabled via `TelemetryConfiguration.json` in the
  Liftoff LocalLow folder, default endpoint `127.0.0.1:9001`.

## Step 5 — persist

Append a tight section to the notes file: date, what was flown, the measured
result, the diagnosis, the single fix given, and the path to the report folder.
Compact prose, and cut superseded detail as you go — the file is read in full at
the start of every review, so it has to stay cheap to read.
