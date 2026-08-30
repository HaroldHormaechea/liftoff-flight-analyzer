# Contributing

## 1. What this guide covers

This guide covers two extension points: **add a sim parser**, and **add a
measurement**. It also states the two constraints a change must not breach, and
how you verify a change in a project that has no test suite.

This guide does not cover installation, day-to-day use, pull request
conventions or code style. [`README.md`](README.md) covers installation and use.
[`SKILL.md`](SKILL.md) covers how Claude Code drives the tool.

## 2. Before you start

**You need Liftoff installed, and your own saved replay.** The repository ships
no flight data. `flight.csv` is gitignored, no fixture is committed, and the
report in [`examples/`](examples/) cannot be regenerated from what the
repository contains — that folder holds `report.md`, `report.html`,
`analysis.json` and `assets/`, and no replay. So you cannot verify a change
against anything in this repository. You verify it against a flight you flew.

The requirement is narrower than it first looks. A saved replay alone is enough
to run `report`: the tool analyses the flight and writes the full report, and it
prints one line saying it drew no environment. A saved replay is **not** enough
to run `view`. `view` needs the track index, and `tracks` extracts that from
your Liftoff install. `tracks --check` does run without it, but the only thing
it can tell you is that the data is missing.

So: a saved replay can be **analysed** without the game. It cannot be
**viewed** without the game.

Worked examples appear in section 9. Read to there before you decide the
material is missing.

## 3. Words this guide uses

This project uses several words with more than one meaning. This table fixes
the meaning **this guide** uses. It does not rename anything in the code.

| Term | Meaning in this guide |
|---|---|
| sim | A flight simulator the tool can read. Today there is one: Liftoff. |
| sim package | The folder `src/fpv_review/sources/<sim>/`, and the modules in it. |
| the analysis | The sim-agnostic stage in `src/fpv_review/common/analysis.py`. Never the report, and never one measurement. |
| sample | One instant of the flight: position, attitude, stick positions, time. |
| series | The whole ordered set of samples for one flight, as a `FlightSeries`. |
| measurement | One derived quantity computed from samples — tilt, sideslip, turn radius. Not a fault classification. |
| calibration constant | A physical constant measured on one sim. It lives in that sim's `calibration.py`. |
| presentational constant | A property of the report — seconds of animation, frames, pixels. It lives in `common/`. |
| capability declaration | What a sim states it can and cannot supply, built by its `capabilities.py`. |
| gap | One field a sim declares it cannot supply. |
| track geometry | Gates, the race route and blueprint placements, from the game's track files. |
| world geometry | Static environment colliders, from the game's scene bundles. A different thing from track geometry. |
| prop | One placed item on a track — a barrier, a ramp, a light. |
| the track index | The file `index.json` inside the track-data folder. `tracks` writes it. |
| the scene cache | The per-environment JSON files under `<track-dir>/scenes/`. `scene` writes them. |
| the prop table | The file `props.json` inside the track-data folder. `props` writes it. |
| `trackdata` | The default folder holding all three of the above. This guide never calls it "the cache", because that word would cover three separate things. |
| the toolkit | This repository, wherever you cloned it. |
| the working directory | The folder you stand in when you run a command. Every output path is relative to it. |

Four words in the code carry two meanings each. This guide separates them:

| Word | This guide writes |
|---|---|
| report | `report` for the subcommand; **the report folder** for what it writes. |
| scene | `scene` for the subcommand; **the scene cache** for the cached files; **the scene dict** for the loaded value. |
| props | `props` for the subcommand; **the prop table** for `props.json`; **prop placements** for the items on a track. |
| source | `source.py` for the module; **the source tree** for `src/`. |

## 4. How the code is laid out

[`docs/engineering.md`](docs/engineering.md) § "Where the code lives" lists the
tree. [`docs/adr/0001-multi-sim-architecture.md`](docs/adr/0001-multi-sim-architecture.md)
§ "1. The tree is `src/fpv_review/{common,sources/<sim>}/`" gives the reasoning.

**The three-layer import rule is the whole architecture:**

- `common/` may import `common/` and the standard library, and nothing else.
- `sources/<sim>/` may import `common/` and its own siblings, and never another sim.
- `cli.py` is the only module that may import both trees. It does the wiring.

Check your change against the first rule with one command. Set `$FPV` first —
section 9 shows how.

```bash
grep -rn --include=*.py -E "^[[:space:]]*(from|import)[[:space:]]+fpv_review\.sources" "$FPV/src/fpv_review/common/"
```

```powershell
Get-ChildItem -Recurse -Filter *.py "$FPV\src\fpv_review\common" |
  Select-String -Pattern '^\s*(from|import)\s+fpv_review\.sources'
```

**The check passes when it prints nothing.** Judge it by its output, not by its
exit code: `grep` exits 1 when it finds no match, and that is the passing case.

Use the scoped form above rather than searching for the bare text
`fpv_review.sources`. The bare search reports two matches on unmodified `main` —
a sentence of prose in `common/__init__.py`, and a compiled file under
`__pycache__` — so it tells you the architecture is broken when it is not.

The second rule cannot fail today, because one sim exists. One sim cannot import
another sim. That half of the rule becomes checkable when a second sim lands.

## 5. Extension point one — add a sim parser

A sim parser is a new `src/fpv_review/sources/<sim>/`. You do not touch the
analysis.

**Read the contract in the ADR.** ADR-0001 § "4. The per-sim contract is
documented here, not stubbed in the tree" names the four modules a sim package
must provide, gives every function's signature and return, and lists the
optional modules. This guide does not repeat that table. The contract changes,
and a copy here would go stale the first time it does.

**Write the four required modules.** They are `source.py`,
`map_geometry_generator.py`, `calibration.py` and `capabilities.py`.

**Register the package in `cli.py`.** Add one entry to `SIMS`. The key is your
sim's name. The value is a dictionary of module keys.

**Four modules are enough to start.** A package holding only the four required
modules registers, and it offers `analyse` and `report`. Registration refuses a
package that is missing one of the four, and it names both the missing key and
the file that supplies it. Add the optional modules when you want the commands
they enable; `--help` lists every command your package leaves out, beside the
file that would add it.

**Emit the schema.** Your `source.py` returns the dataclasses defined in
`src/fpv_review/common/schema.py`: `FlightSample`, `FlightSeries`,
`SessionMeta` and `LapSet`. Read that module's header for the units and the
coordinate frame. It states them once, for everything in the module. Do not copy
them into your own module — convert to that frame in your ingestion layer, and
nothing downstream asks which sim the numbers came from.

**Put your constants in your own `calibration.py`.** ADR-0001 § "7. Per-sim
calibration lives in `sources/<sim>/calibration.py`" gives the rule and the six
module-level names your module must define. The placement rule is stated at the
top of `sources/liftoff/calibration.py`, in that file's own words:

> The line, so a later reader knows where a new constant belongs: physical
> constants are calibration; presentational ones are not.

**Expect the contract to move.** ADR-0001 says plainly that the first real
second sim will change it. The contract was designed against one sim and against
what the analysis consumes, and nothing was added for a sim nobody has
inspected. If your sim needs a field the schema does not carry, that is the
contract being revised as intended. It is not you working around it.

## 6. The capabilities declaration

Your sim declares what it cannot supply. Write `capabilities.py` with a
`declare()` function that returns a `Capabilities`.

Read `src/fpv_review/sources/liftoff/capabilities.py` as the worked example.
Read its `velocity` entry first. Liftoff's replay stores no velocity, so the
entry is `DERIVED`, and its note says how the number is obtained and what it is
not good for. That is the shape to copy: a state, and the reason.

**The rule the declaration serves: a stage that meets a declared gap names it,
and never infers the value.**

**Be clear about what runs today.** The declaration is recorded and published.
`cli.py` writes it into `analysis.json` as one additive `capabilities` key on
every report. The consuming half — `gap()` and `has()` in
`src/fpv_review/common/capabilities.py` — is provided, and nothing calls it
today.

That is correct rather than unfinished. Liftoff declares no gap that suppresses
a finding the report makes, so no stage has anything to consult. You can see
this in any report: `gaps_named_in_this_run` is `[]` in the `capabilities` block
of every `analysis.json` this repository has produced. If your sim has a gap
that does suppress a finding, you are the first to need the consuming half.

## 7. Extension point two — add a measurement

A measurement is a new derived quantity, alongside tilt, sideslip and turn
radius. [`docs/engineering.md`](docs/engineering.md) § "What the analysis
measures" explains what the existing measurements mean. This section covers
where you add one.

**Choose the level you are measuring at.** There are three, all in
`src/fpv_review/common/analysis.py`:

- **Per sample** — in `load()`. It builds one dictionary per sample. `tilt` is
  computed in its first loop; `turn` and `radius` in its second, which needs the
  neighbouring samples.
- **Per segment** — in `segment_stats()`. A segment is a lap, or the whole
  flight when there are no laps.
- **Per corner** — in `corner_stats()`.

**Know how your value reaches the reader.** `analyse()` assembles the
per-segment entries. `cmd_report` in `cli.py` writes them into `analysis.json`
under the `segments` key. So a new key you add to a segment entry reaches
`analysis.json` on its own, and you do not have to do anything for that to
happen. It reaches `report.md` only if you render it: `build_report()` in
`src/fpv_review/common/report.py` builds the segment table from an explicit
column list, and a key that is not in that list is not printed.

That asymmetry is deliberate. `analysis.json` is a superset of the report. Add
your key to the table only when a reader needs it in the narrative.

**Handle the samples where your measurement is undefined.** This is the one real
decision the procedure asks of you, and the code already shows you the pattern.
In `load()`, `turn` and `radius` are set to `None` **together** when either
neighbouring sample has no heading. Neither is guessed, and neither is left at a
stale value. `segment_stats()` states the same principle for a whole segment:
sideslip is measured over moving samples only, because the angle between nose
and velocity is undefined when there is no velocity — and the other statistics
are *not* restricted that way, because restricting them would delete stalled
time from the medians.

So decide, before you write the arithmetic, what your measurement means when its
input is missing. Then make it `None`, and make anything derived from it `None`
in the same place.

**Decide where its constants belong.** A physical constant is calibration, and
it goes in the sim's `calibration.py`. A presentational constant is not, and it
stays in `common/`. `IMPACT_DROP_KMH` is a speed in km/h measured on Liftoff
flights, so it is calibration. Seconds of animation and frames of SVG are
properties of the report, so they stay in `common/`.

**A measurement may need no constant at all.** Tilt needs none. Do not invent a
threshold to have one.

**Nobody has walked this path yet.** Every existing measurement predates the
restructure. The locations above are read off the current code, not from
precedent.

## 8. The two hard constraints

**The analysis path takes no third-party dependency.** `pyproject.toml` declares
`dependencies = []`, and ADR-0001 § "2. `pyproject.toml` carries metadata only"
gives the reasoning. The tool ships by being cloned and run in place, with
nothing to install. `UnityPy` is an optional extra, and only the Liftoff scene
and prop readers use it. Do not add an import that puts a package on the path
from a replay to a report.

**Never commit a game asset, an extracted track XML, a replay, a report or a
pilot profile.** Two mechanisms exist, and neither replaces the rule.
`.gitignore` covers `*.csv`, `replays/`, `reports/`, `data/`, `trackdata/` and
`liftoff-pilot.md`. `refuse_inside_toolkit()` in
`src/fpv_review/common/toolkit.py` stops a write that would land inside the
toolkit — but it only fires when the toolkit is mounted through a link, so it
does not protect an ordinary clone. An ignore rule is one `git add -f` away from
being wrong. Check what you are staging.

## 9. How a change is verified here

**This project has no test suite, by decision.** [`PROJECT_BRIEF.md`](PROJECT_BRIEF.md)
records it as settled question 2: introducing a test framework would make this
project depend on something, which is the one thing it has chosen not to do. So
**"the tests pass" is not a claim available in this repository.** You verify a
change by running the real pipeline against a real replay, and comparing what it
produces.

### Set `$FPV`, and check it

Run this from inside your clone. The capture and the check are one unit — run
both lines together, and read the result before you go on.

```bash
FPV=$(git rev-parse --show-toplevel)
test -f "$FPV/src/fpv_review/cli.py" && echo OK || echo FAILED
```

```powershell
$FPV = git rev-parse --show-toplevel
Test-Path "$FPV\src\fpv_review\cli.py"
```

A correct `$FPV` is the folder your clone sits in. The check prints `OK` in bash
and `True` in PowerShell.

The check exists because `git rev-parse` answers about the directory you are
standing in, not about this project. Stand in a folder that is not a repository
and it fails loudly, leaving `$FPV` empty. Stand inside a **different**
repository and it succeeds quietly, and hands you that project's root. The
second case is the dangerous one, because Python then fails naming a path inside
a project of your own. **The invariant to remember: if a command fails naming a
path that is not your clone, `$FPV` is wrong.** Set it again from inside the
clone.

`$FPV` holds forward slashes in both shells. Windows accepts
`"$FPV\src\fpv_review\cli.py"` with the separators mixed, so the PowerShell line
above runs as printed.

This guide writes `python "$FPV/src"` with a forward slash. The tool's own usage
line echoes the same path back with backslashes, because it prints the resolved
folder rather than the string you typed. The two are the same path. Do not
correct one to match the other.

### Work in `~/fpv-work`

Do not verify inside your clone. Every output path is relative to the working
directory, and a run inside the clone leaves your replays and reports in shared
code.

```bash
mkdir -p ~/fpv-work
cd ~/fpv-work
```

```powershell
New-Item -ItemType Directory -Force "$HOME\fpv-work"
Set-Location "$HOME\fpv-work"
```

Both forms are safe to run again on a folder that already exists. `$FPV` carries
across the move; you do not set it again.

### Get a replay path — do not type one

```bash
python "$FPV/src" replay --latest
```

It copies the newest replay out of Liftoff's Recordings folder into `replays/`
and prints the path it wrote. **Use that printed path in every later command.**

Do not use `--latest` again for the rest of your verification. It re-archives
and re-picks, so two runs would not compare the same flight.

### Run the pipeline

Substitute the path `replay --latest` printed.

```bash
python "$FPV/src" tracks --check
python "$FPV/src" report replays/<the-file-it-printed>.xml -o reports --no-auto-open
python "$FPV/src" view --replay replays/<the-file-it-printed>.xml -o incident3d.html
```

`tracks --check` reports whether your track data is present and current, and
exits 1 when it is not. That exit code is the answer, not a failure of the
command.

If you have no track data yet, `report` still works. It exits 0, writes the
whole report, and prints one line:

```
recordings: no track data for this replay - the path, the attitude and the impacts are drawn, the environment is not
```

`view` in that state does not run, and says so:

```
no track index in trackdata.
Build it: python "<your clone>/src" tracks -o trackdata
```

Run the command it prints, then run `view` again. Expect to do this more than
once. `view` needs the track index **and** the scene cache for the environment
you flew, and it asks for one thing at a time. After you build the index it asks
for the scene next, in the same two-line shape. Keep running what it prints until
`view` writes a page.

Building a scene cache is the one step in this guide that needs something
installed: the optional `UnityPy` extra. The `scene` command says so itself, and
it also says that only *building* a cache needs it. Reading one is plain JSON and
needs nothing, which is why `report` never asks you for it.

### Compare the before and the after

Keep the output of a run against unmodified code. Make your change. Run the same
commands again into a different `-o` folder. Compare the two folders file by
file.

**Only these may differ:**

- `generated` in `analysis.json`.
- The generated-by footer in `report.md` and in `report.html`.

Anything else that differs is a change in behaviour. If you believed your change
was a no-op, it was not.

**The `view` page is the strictest instrument you have.** It embeds no
timestamp — nothing on its path calls the clock — so two runs over unchanged
code produce byte-identical pages, with nothing to excuse. When you change
anything that `view` reaches, compare the page as well as the report. A report
comparison can pass while executing none of your change.

Compare the pages byte for byte, not line by line:

```bash
cmp before/incident3d.html after/incident3d.html
```

```powershell
(Get-FileHash before\incident3d.html).Hash -eq (Get-FileHash after\incident3d.html).Hash
```

`cmp` prints nothing when the files match, and the PowerShell line prints
`True`. Do not use `Compare-Object` here. It compares lines, so it reports no
difference when only whitespace at the end of a line has moved.

This guide leaves out the two verification rules this project wrote down while
building it. They are recorded in
[`use-cases/plans/01-multi-sim-architecture-adr.md`](use-cases/plans/01-multi-sim-architecture-adr.md).

## 10. How this project is built and evolved

This project is built with the **project-builder** harness:
<https://github.com/HaroldHormaechea/project-builder>. It is a set of Claude
Code entry points that capture what a project should do, and then drive a small
agent team to build it.

Two folders in this repository come from that harness.
[`use-cases/`](use-cases/) holds one formalized file per use case: a summary,
acceptance criteria, and the pitfalls found while capturing it.
`use-cases/plans/` holds the agreed implementation plan for a use case.
[`USE_CASES.md`](USE_CASES.md) is the status ledger for both.

They are committed on purpose. A use case records what was asked for and what
"done" meant, and a plan records which alternatives were rejected and why —
neither of which survives in the diff. You do not need the harness to
contribute.

## 11. Where to look next

- [`README.md`](README.md) — what the tool is, how to install it, how to run it.
- [`SKILL.md`](SKILL.md) — how Claude Code drives the tool, step by step.
- [`docs/engineering.md`](docs/engineering.md) — what each command does, what the analysis measures, and how the report is built.
- [`docs/adr/0001-multi-sim-architecture.md`](docs/adr/0001-multi-sim-architecture.md) — the per-sim contract, the import rule, and the alternatives each decision beat.
