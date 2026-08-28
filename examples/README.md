# An example report

One real, unedited report, exactly as `fpv_report.py` wrote it — a three-lap race
on Stuff That Works, flown on a Borrum 180 X.

| | |
|---|---|
| [`report.html`](20260828-140705_BardwellsYard_Race_3lap/report.html) | the deliverable: tabbed, with the lap animations playing |
| [`report.md`](20260828-140705_BardwellsYard_Race_3lap/report.md) | the same report as Markdown, which GitHub renders inline |
| [`analysis.json`](20260828-140705_BardwellsYard_Race_3lap/analysis.json) | everything, including what the report leaves out |
| `assets/` | the figures and the animated replays, hand-written SVG |

**[Open the live HTML](https://raw.githack.com/HaroldHormaechea/liftoff-flight-analyzer/main/examples/20260828-140705_BardwellsYard_Race_3lap/report.html)** — GitHub shows HTML as source, so that link goes
through raw.githack, a third-party viewer for raw repository files. Or clone the
repo and double-click the file, which is what the tool does for you anyway.

The tab row is deep-linkable, so you can point at one section:
**[the lap times](https://raw.githack.com/HaroldHormaechea/liftoff-flight-analyzer/main/examples/20260828-140705_BardwellsYard_Race_3lap/report.html#lap-times)**.

`flight.csv` — the decoded per-sample data — is the one part of the folder not
committed here. It is 140 KB of numbers already summarised by `analysis.json`,
and the repository ignores `*.csv`.

## What to look at

The **Debrief** is the point, and it is the one section written by hand: the
script fills in everything factual and deliberately leaves that heading empty,
because the diagnosis depends on what the pilot has already been told and the
script does not know that.

Then read it against the evidence. **Lap times** shows three laps within 1.75 s
of each other. **Circuit path** shows where the speed was carried. **Numbers**
shows the 0–20 km/h band missing entirely from all three laps, which is the
measurement the debrief is built on.
