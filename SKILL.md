---
name: fpv-review
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

## Step 0 — the pilot profile

Everything below is generic. What makes a review useful is what it knows about
*this* pilot: where their files live, the faults already diagnosed, the fix they
are currently working on, and what they have already been told.

**Look for a pilot profile, in this order, and read it before anything else:**

1. the path in the `LIFTOFF_PILOT` environment variable
2. `liftoff-pilot.md` in the working directory

The profile overrides the generic paths below and carries the standing
diagnosis. If one exists, it wins — including on where replays, reports and the
PB history are kept.

If there is no profile, work generically, and at the end of the review offer to
start one. A single flight reviewed in isolation is worth much less than the
second flight measured against the first.

**A profile is personal data. It is gitignored here and must never be
committed.** If this toolkit is mounted into another project — as a Claude Code
skill, say — keep the profile in that project, not in this directory, and the
tools will enforce it: `refuse_inside_toolkit()` hard-stops any attempt to write
reports, replays or history under a linked toolkit root.

## Step 1 — check the track data before anything else

**Run this first, every review, before reading a replay.** It is one command and
it either prints READY or tells you what to do.

```powershell
# PowerShell. $FPV is the folder this skill was cloned into.
$FPV = "$HOME\.claude\skills\fpv-review"
python "$FPV\src" tracks --check -o trackdata   # exit 0 ready, 1 not
python "$FPV\src" tracks         -o trackdata   # rebuild; a no-op if current
```

```bash
# bash
FPV="$HOME/.claude/skills/fpv-review"
python "$FPV/src" tracks --check -o trackdata    # exit 0 ready, 1 not
python "$FPV/src" tracks         -o trackdata    # rebuild; a no-op if current
```

The `tracks` command finds the Liftoff install itself — every Steam library from
the registry and `libraryfolders.vdf` — and extracts all 92 tracks and 92 races
out of the game's Unity bundles as XML, plus an `index.json` that joins a
replay's `trackID` to the track it was flown on. It takes about five seconds
and needs nothing installed.

**The extracted XMLs are game assets and are gitignored. Only the script is
committed.** They are cheap to regenerate and must not be redistributed, so
never commit them, and never hand-edit them — the next rebuild overwrites them.

Why the check exists rather than just running the extractor: bundle filenames
are content hashes, so a game patch silently leaves the extracted XMLs
describing a layout the game no longer has. `--check` compares the recorded
bundle fingerprint and Steam build id against what is installed and fails the
moment they disagree. Analysing a flight against stale gates is worse than
having no gates — it produces confident, wrong numbers.

If it says NOT READY, rebuild it. That is the whole procedure; there is no case
where the right move is to continue on stale data.

What it is for, once ready:

```bash
python "$FPV/src" tracks --for-replay replays/<file>.xml -o trackdata
python "$FPV/src" tracks --gates "03 - Stuff That Works" -o trackdata
```

`--for-replay` names the track and the race, because a replay records only a
GUID and an environment name — and an environment holds five or six tracks that
all share it. `--gates` prints the route in the order it is flown, each
checkpoint with its world position, its yaw and its aperture in metres where it
has one. Both are in the same coordinate frame as the replay, so a gate and a
flight path compare with no transformation.

**Which items are gates is the race's decision, not the track's.** A checkpoint
is any blueprint the route names, of any type: on Bardwells Yard all of them are
plain inflatable arches, on HangarC03 the route mixes truss gates, a fixed 5×5
box and three resizable ones. Filtering a track's items by type to find "the
gates" finds three of the ten. Resolve the route.

**A checkpoint is a scoring volume, not a hole.** The environment can obstruct
any part of it — on HangarC03 the gate 31 checkpoint centre sits half a metre
inside a closed container door, so aiming at the middle of the gate flies into
solid geometry. Do not turn gate positions into a racing line without checking
what is around them.

## The deliverable is an illustrated report, not a terminal dump

The `report` command writes a folder holding the report, its figures, an animated
replay of every lap, and a playable 3D recording of every crash and every stall.
That is what the pilot gets. The terminal
output of the `analyse` command is for answering a quick question mid-conversation,
not for a review.

## Step 2 — build the report

```powershell
# PowerShell
$FPV = "$HOME\.claude\skills\fpv-review"
python "$FPV\src" report --latest                 # newest replay saved in-game
python "$FPV\src" report replays\<file>.xml       # a specific archived one
```

```bash
# bash
FPV="$HOME/.claude/skills/fpv-review"
python "$FPV/src" report --latest                  # newest replay saved in-game
python "$FPV/src" report replays/<file>.xml        # a specific archived one
```

`--latest` archives the replay before it reads anything, then writes
`reports/<replay-stem>/`:

    report.md          the debrief the pilot reads and you edit
    report.html        the same thing, double-clickable, animations playing,
                       crash and stall recordings inside it
    analysis.json      EVERYTHING, including what the report leaves out
    flight.csv         the decoded per-sample data
    assets/*.svg       figures and the animated lap replays

**`analysis.json` is the one you read, not `report.md`.** The report is an
argument made to a person: sections are collapsed, panels are dropped, numbers
are rounded. The JSON is a deliberate superset — every segment statistic, every
corner, every stall, the generated findings, the exact thresholds that produced
them, the measured sample rate, the lap index boundaries, and a `not_in_report`
list naming what was left out and where it lives instead. Never re-derive from
`flight.csv` what is already sitting in there.

Report structure, in reading order: a compact header, then **Debrief**, **Data
analysis**, **Lap times**, **Flight playback**, **Highlights and recordings**,
then everything else collapsed. The debrief leads because it is the answer, and
everything after it is the evidence — which only gets read when the answer
provokes a question.

In `report.html` those sections are **tabs**, in a row under the race header, and
the Debrief is the one open on arrival. `report.md` is unchanged — one linear
document, still correct on GitHub and in the VS Code preview. A tab click updates
the fragment, so `report.html#highlights-and-recordings` opens straight into that
section and is
worth linking directly when the answer lives in one place.

**Archiving matters.** Liftoff names a replay after its track and total time, so
every abandoned attempt on a track collides on one filename and each save
destroys the previous one.

Lap boundaries come out of the replay metadata, so `--laps` is only needed for an
abandoned attempt worth splitting by hand. Untimed flying either side of the
timed laps gets its own segment when it contains real flying — which is how a run
that ends in a crash keeps the crash, since `lapTimes` only ever describes laps
that finished.

`report.html` opens in the default browser as soon as it is written, so the
pilot sees the report rather than a path to it. Pass `--no-open` when that is a
nuisance — a batch run, or the regeneration in step 4 that only exists to pick
up a hand-written debrief.

Useful flags: `--no-anim` when only the numbers are wanted, `--no-open` to keep
the browser shut, `--cam-span` for the follow-cam width in metres, `--stall-pad`
for context around a stall recording, `--no-rec` to skip the recordings entirely,
`--reset-debrief` to clear a hand-written debrief instead of carrying it forward.

## Step 3 — read the figures before writing a word

- **Lap times** — lap bars with the stalls marked in red, against the pilot's
  best ever lap on that track. Says immediately whether the deficit is pace or
  stops.
- **Flight playback** — nose arrow versus dashed direction-of-travel ray. The
  angle between them is the sideslip, and the arrow turns red past 30 degrees.
  The overview map behind the quad is the lap coloured by speed, so this is also
  where the time is lost geographically. The stall clips are where a fault
  becomes visible rather than tabulated. The last entry, **Laps overlaid**, is
  the one still figure in the section: every lap on one map in its own colour,
  showing lap-to-lap line differences, which no change of stick technique can
  fix. It is there because it answers a question the playback cannot — the
  playback is always one lap.
  There is deliberately no combined "all laps" *animation*: a merged figure
  listed beside the laps it merges reads as one more lap. Seeing everything at
  once is the expand-all control the HTML puts on any section with two or more
  disclosures.
- **Traces** — speed, sideslip and throttle on one clock, stalls banded. Tilt and
  the stick traces are a second figure, collapsed; open it when the question is
  about inputs rather than results.
- **Corner scorecard** — tilt against sideslip, plus throttle added per corner.
  Down and to the right is a committed, coordinated corner.
- **The recordings**, under **Highlights and recordings**, which leads with the
  Crashes table, then Stalls, then the reference numbers behind them. A
  **Pit stops** table sits at the foot of **Flight playback**, not here, when the
  track has repair or recharge volumes the pilot used — beside the maps whose
  icons say where each stop happened. Every row
  of the Crashes and Stalls
  tables carries a play control, and it opens that moment in 3D inside the page
  — the environment, the track props, the path coloured by speed, the quad at
  its true attitude, the impact marked. Orbit it. This is the only view that
  shows what was actually AROUND the quad, which is the difference between "the
  speed collapsed" and "it clipped the ramp on the inside of the turn". When the
  environment has not been cached the recording says so in its footer and draws
  what it has; cache it with the `scene` and `props` commands once per
  environment (see `docs/engineering.md`).

What to read in the numbers:

- **`sideslip`** — the angle between where the nose points and where the quad is
  actually going. Under ~10 deg is coordinated, 30+ is a skid, near 90 means
  travelling sideways with no lift authority left. A crash usually shows as
  sideslip climbing through 90 in the two seconds before speed collapses.
- **`yaw-only`** — time with commanded yaw held while roll stays at zero. A turn
  flown on yaw alone is a pirouette: the airframe rotates, the path does not
  bend. Reported by speed band, because the fault typically appears as yaw
  authority rising while roll authority stays flat as speed drops.
- **`crashes`** — every impact in the flight, found in the trajectory: 20 km/h
  or more lost inside one 0.1 s sample. The replay's own `isCrashed` flag is not
  used, because it reads false on runs that ended pinned against the ground.
  Each carries the speed lost, the height, and the nearest solid track prop —
  usually what was hit.
- **`pit_stops` and `pit_landings`** — a track can carry repair and recharge
  volumes, and the way a pilot uses one is to fly in and sit there. That reads
  to the impact detector exactly like hitting the ground, because it is.
  **An impact inside a pit volume that the quad flew out of again is a landing,
  not a crash**, and it is in `pit_landings` rather than `crashes`; one the quad
  never flew out of stays a crash, because the drone was lost there and the pit
  is only where it happened. `pit_stops` is the stop itself — which service, how
  long the whole stop was (`seconds`), how much of it was actually inside the
  volume (`serviced_s`) and how much on the ground (`grounded_s`). The gap
  between the first two is time parked NEXT TO the pad rather than on it, which
  is coachable. It is drawn
  on every lap map and playback as a green bolt (recharge) or a purple propeller
  (repair), matching the game's own pad colours. A crash is a red disc with a
  white X, the same mark in the maps, the playbacks and the 3D recording. A stop is not a
  fault, it is a cost: read it off the clock, do not coach it. It is also taken
  out of `stalls`, so a six-second repair is not reported as a hesitation.
- **`stalls`** — every episode below 10 km/h, classified `overrun` (the path
  reversed and retraced itself), `corner` (another lap turns there too, so the
  track asked for it) or `hesitation` (another lap flies straight through). This
  is what turns "you were slow" into a cause. Pit stops are excluded.
- **`d_thr` per corner** — throttle added through the corner. Bank sets the
  direction of the turning force, throttle its magnitude, so a corner with no
  throttle increase goes wide and sinks.
- **`tilt` and `radius`** — a committed arc versus a flat yaw-around. Low tilt
  with a tiny radius and high sideslip is the failure pattern.
- **entry vs exit speed** — exit faster than entry is slow-in/fast-out working.

## Step 4 — write the Debrief section

The script fills in everything factual and leaves `## Debrief` empty on purpose.
It writes what happened; it does not write the coaching, because the diagnosis
depends on what the pilot has already been told and the script does not know
that. A generated sentence can say a number is large, but only a person knows
whether it is news.

It does scaffold the shape, in two halves:

- **The assessment**, above the heading. What happened, what it means, and what
  is still wrong. Report a result that went well in the same register as one that
  did not — name it, give the number, move on — and keep assessing afterwards,
  because a flight with a good headline still has faults in it. Cut any sentence
  that is not a measurement, a cause or an instruction; use a table wherever the
  data is tabular.
- **`### Recommendations`**, at the end. Numbered, terse, actionable: drills to
  fly, changes to make, things to stop doing. Putting every instruction here is
  what lets the body above stay assessment, and it is the part a pilot rereads
  before the next session.

**Pass `--no-auto-open` on every run, and open the report yourself at the end.**
The automatic open fires when the file is written, which is before this section
exists, so it shows the pilot a page whose headline reads "TO BE WRITTEN" — and
the regeneration that fills the Debrief in does not refresh that tab. The order
that works:

1. Generate with `--no-auto-open`. There is nothing to read yet.
2. Read `analysis.json` and write the Debrief into `report.md`.
3. Regenerate with `--no-auto-open` so `report.html` picks it up.
4. Open `report.html` yourself.

An existing debrief is carried forward on every regeneration, so nothing is lost.

Read the pilot profile and whatever notes it points to first. Repeating advice
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
- A stall tagged off-line is a track-knowledge error, not a stick error. No
  change of technique fixes it; slow exploratory laps do.
- Late-session runs carry almost no diagnostic value. Do not debug fatigue.

Tone: lead with the number and the cause. Name **one** thing to fix and give
**one** drill. Do not stack three — a pilot who is given three fixes does none of
them, and the next flight's data cannot attribute a change to any of them.

Then say the same thing in chat, short, and link the report. Do not paste the
tables into the conversation; they are in the file.

## Step 5 — the other sources, only when needed

- **`pbs --save`** — personal bests per track, diffed against the last
  snapshot. Liftoff overwrites these in place, so a beaten time is gone unless
  snapshotted. Run it every session. It also reveals flights that were never
  recorded, which is often where the real progress is, and it is what the
  report's "best ever" bar is drawn from.
- **`telemetry`** — live UDP feed, 100 Hz, and the only route to gyro,
  battery and motor RPM. It must be running during the flight. Reach for it for
  tuning-level questions (oscillation, propwash, PID feel), not for piloting
  technique, which 10 Hz covers. Enabled via `TelemetryConfiguration.json` in the
  Liftoff LocalLow folder, default endpoint `127.0.0.1:9001`.

## Step 6 — persist

Append a tight section to the notes the profile points at: date, what was flown,
the measured result, the diagnosis, the single fix given, and the path to the
report folder.
Compact prose, and cut superseded detail as you go — the file is read in full at
the start of every review, so it has to stay cheap to read.
