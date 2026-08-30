---
plan_for: use-cases/02-contributing-extension-points.md
work_branch: feat/uc-02-contributing
team: session-949520aa
approved: 2026-08-30
status: APPROVED — challenger-approved after six rounds, nine Majors closed
---

# UC-02 — approved implementation plan

> **Provenance.** This is the analyst's v5, approved by the challenger after six
> rounds and nine Majors. A second consolidated plan was produced concurrently by a
> duplicate agent and was **rejected by the lead**: it hardcoded
> `$FPV = "$HOME\.claude\skills\fpv-review"`, the README's *install* path, when the
> whole `git rev-parse` two-step exists because a **contributor clones wherever
> they like** — and its own text conceded that on a machine without that path the
> recipe's "designed outcome" is printing `FAILED`. A setup recipe whose designed
> outcome is failure does not satisfy criterion 10, and it would have reintroduced
> the machine-varying-path defect five rounds of review removed. Two additive
> improvements from that document are adopted in the addendum at the foot of this
> file.

## Analysis

### Where the work is

Criteria 1–12 and 19 concern `CONTRIBUTING.md`; only 14–18 and 20 touch code. The interrupted run spent itself on the code, so the centre of gravity here is the document.

**Criterion 12 is the design problem.** `README.md`, `SKILL.md`, `docs\engineering.md` and ADR-0001 already answer most contributor questions. The guide's job is the two *procedures* nobody wrote down, plus links — procedure and citation, not exposition.

**Criterion 11 is harder than it looks.** The codebase uses several words two ways: `report` is a subcommand and an artifact folder; `scene` is a subcommand, a cached JSON file and a dict; `props` is a subcommand, a shape table and a placement list; `source` is a module, a tree, and English. The guide cannot rename the code, so its terms table fixes the *guide's* usage.

### What the code requires of a new sim

`SIMS` (cli.py:50-59) has ten keys; ADR-0001 decision 4 names four modules. Finding 1: a four-module package raises `KeyError('replay')` at parser construction. Registration-time needs, key by key: `add_view` (cli.py:64) reads `calibration`, and after criterion 14 `cmd_view` reads `tracks` and `scene` at run time; `add_analyse` (cli.py:138) reads `calibration`; `add_report` (cli.py:226) reads `calibration` plus `sim["replay"].DEFAULT_ROOT` at cli.py:235 — its only registration-time need of `replay`, the other two uses (cli.py:303, 307) sitting inside `if args.latest or path is None`; `add_pbs` (cli.py:518) reads `pbs`; `add_sim_commands` (cli.py:593) reads `build_parser()`/`__doc__` per sim command. So a conformant four-module package yields `{analyse, report}` — and `report` on an explicit path is what the contract exists for.

**The full required surface**, from every `sim["` in cli.py. Contract: `calibration` (six names); `source.load_flight(path)` → `(SessionMeta, FlightSeries, LapSet, meta)` (cli.py:89, 310); `map.props_near(track_dir, track, route, points, radius, shapes)` (cli.py:111, 297); `map.geometry_for(path, track_dir, scenes, prop_table)` → `(track, race, scene, shapes, note)` (cli.py:415); `capabilities.declare()` → `Capabilities` (cli.py:322). Optional: `replay` (`DEFAULT_ROOT`, `find_replays`, `archive`); `pbs` (`__doc__`, `DEFAULT_ROOT`, `snapshot`, `track_names`); `tracks`/`scene`/`props`/`telemetry` (`build_parser`, `run`, `__doc__`) — **and, once criterion 14 lands, `tracks.for_replay` (tracks.py:411) and `scene.load_scene` (scene.py:460)**, which our own change makes contractual. Three of the four contract functions are documented nowhere.

**Calibration's surface** (finding 2): `THRESHOLDS` plus `IMPACT_DROP_KMH`, `IMPACT_DEBOUNCE_SAMPLES`, `PROP_NOMINAL`, `REC_RADIUS_M`, `CAM_SPAN_M`. The twenty `THRESHOLDS` keys need no separate validation list: `build_parser` does `T = calibration.THRESHOLDS` (analysis.py:402) then exactly 20 distinct `T["…"]` lookups, `add_analyse` calls it at registration (cli.py:146), and `default_args` (analysis.py:486) routes through the same function. That measurement is what makes the guard in §C proportionate — only the six module-level names need explicit checking, and the twenty keys are covered where they already live.

### The capabilities mechanism

`gap()` and `has()` have **no call site**: the only four references outside the two modules are cli.py:34, 51, 322, 479. The overstatement sits in three places, two of them code — `common\capabilities.py`'s docstring, `sources\liftoff\capabilities.py`'s, and ADR-0001's Consequences § "Degradation stays explicit", in the present indicative. Correcting only the ADR leaves the falsehood in the module a contributor copies. **Output-safe**: the `__doc__` reads are `incident_view`, `analysis`, `report`, `sim["pbs"]` and `module` in `add_sim_commands` — neither capabilities module among them.

### Criterion 20, and why the obvious fix is the trap

Finding 3, measured three ways. `cmd_view` → `tracks.for_replay` → `load_index` (tracks.py:407-408) reads `index.json` unguarded; with no cache that is an unhandled `FileNotFoundError` and a raw traceback, and the `track is None` guard at cli.py:101 never runs. Repairing `load_index` with `sys.exit` raises `SystemExit`, which `BaseException`-derives and escapes `geometry_for`'s `except Exception` — turning `report`'s clean exit-0 degrade into an exit-1 abort **leaving a partial output directory** (`flight.csv` and five SVGs). Raising `FileNotFoundError` instead leaves `view` printing a traceback. The guard belongs in `cmd_view`; `scene.py:460-466` is the model, and tracks.py:449/551/558 already print `toolkit.command("tracks", "-o", …)`.

### What the guide may honestly promise

Finding 6: from a directory holding only a replay XML, `report` exits 0 with a "no track data" note; `view` cannot run, nor can `tracks --check`. Since 18a makes `view` the strictest instrument, a guide claiming "a replay suffices" would be wrong about the command its verification leans on. Liftoff requirement up front, the narrower fact after it as relief, worked examples promised later.

### The `$FPV` recipe needs a check, not a warning

Measured in both shells: cwd = clone → `C:/dev/liftoff-flight-analyzer-uc-02-contributing`, exit 0, byte-identical between shells; cwd = a non-repo → exit 128, variable empty; end to end from the run directory → `python "$FPV/src" --help` exit 0, output byte-identical to `baseline\logs\help-root.out`.

**That loudness is an accident of this machine.** Built and run: a work directory inside another repository returns *that* repository's toplevel at exit 0, silently, and `python "$FPV/src"` then fails naming a path inside the contributor's own project. The failure is not silent but **misdirected**, which for a newcomer is worse — it sends them looking in the wrong place. Two shapes exist, and the plan records both because a later run inherits this file: with no `src/` in their repo, `can't open file …: [Errno 2] No such file or directory`, exit 2; with a `src/` lacking `__main__.py`, `can't find '__main__' module in …`, exit 1. Neither string reaches the guide (Risks 9).

So capture and verification print as one unit, checking that `$FPV/src/fpv_review/cli.py` exists. Tested against all three outcomes:

| `$FPV` is | bash | PowerShell |
|---|---|---|
| the clone | `OK` | `True` |
| empty (run outside any repo) | `FAILED` | `False` |
| another repository | `FAILED` | `False` |

Also: the inline `"$(git rev-parse --show-toplevel)/src"` form is **not** bash-only — PowerShell's `$(…)` runs the command too. It is unusable for a better reason: it only resolves when cwd is the clone, which ADR-0001 decision 5 forbids. The two-step is the only viable shape in any shell.

## Proposed Solution

### A. `CONTRIBUTING.md` — replaced entirely

Eleven sections. The order is load-bearing: the prerequisite before anything that wastes effort (criterion 19), the terms before the prose using them (criterion 11), the extension points before the constraints and verification that apply to both.

**§1 What this guide covers.** Two or three sentences: the two extension points, the two hard constraints, how a change is verified. Not installation, usage, PR conventions or code style — links to `README.md` and `SKILL.md`.

**§2 Before you start.** Criterion 19, first substantive section. You need Liftoff and your own saved replay, because `flight.csv` is gitignored, no fixture is committed, and the committed `examples/` report cannot be regenerated from the repository (that folder holds `report.md`, `report.html`, `analysis.json`, `assets/` — no replay, no CSV). Then the relief, correctly narrowed: a replay alone lets you run `report`; `view` and `tracks --check` need the cache. Closes by promising worked examples later.

**§3 Words this guide uses.** ~18 rows: *sim*; *sim package*; *the analysis*; *sample*; *series*; *measurement*; *calibration constant*; *presentational constant*; *capability declaration*; *gap*; *track geometry* vs *world geometry*; *prop*; *the toolkit*; *the working directory*. Plus `trackdata` as the folder **and** the *track index*, *scene cache* and *prop table* one row each — §9 and criterion 20's message name all three separately, so "the cache" as a catch-all was itself a two-meaning term. Plus the four overloaded words disambiguated.

**§4 How the code is laid out.** Pointers to `docs\engineering.md` § "Where the code lives" (line 29) and ADR-0001 decision 1. Criterion 6's three-layer rule stated in full, since the criterion requires stating not just linking. Then the check, in the scoped form, both shells:

```
grep -rn --include=*.py -E "^[[:space:]]*(from|import)[[:space:]]+fpv_review\.sources" src/fpv_review/common/
```

Pass condition: no output. The naive form returns two hits on unmodified `main` — the prose line at `common/__init__.py:3` and a `__pycache__` binary match, exit 0 — so a reader running it would conclude the architecture is broken. Both forms get run before shipping. And it says plainly that the sibling half of the rule cannot fail today, because one sim exists: the ADR's "checkable with one grep" is currently half a check.

**§5 Extension point one — add a sim parser.** Cites `### 4. The per-sim contract is documented here, not stubbed in the tree` by its real heading text. Covers the module surface and what each returns (by citation, once §D lands); registration as one entry in `SIMS` (cli.py:50); what four modules gets you, with the rest named in `--help` — a sentence true only after §C lands, which is why the two travel together; the dataclasses `FlightSample`, `FlightSeries`, `SessionMeta`, `LapSet` in `common\schema.py`, with units and coordinate frame *referenced* at schema.py:5-9, not copied; calibration by reference to amended decision 7, with the placement rule quoted from calibration.py:9-13. Closes with the second pitfall's warning: the contract was designed against one sim and ADR-0001 says the first real second sim will change it.

**§6 The capabilities declaration.** Criteria 4 and 17 together. `declare()` returns a `Capabilities`; `sources\liftoff\capabilities.py` is the worked example, its `velocity` entry (derived, with the reason) the one to read first. The rule: a stage meeting a declared gap names it and never infers. Then the honest present tense — the declaration is recorded and published as one additive `capabilities` key in `analysis.json` (cli.py:479), and `gap()`/`has()` are provided for a sim that needs them and have no call site today. States that `gaps_named_in_this_run` is `[]` in every report — verified across all four baseline `analysis.json`, 13 declared fields each — because that key is the one place the overstatement is machine-readable.

**§7 Extension point two — add a measurement.** Per-sample in `analysis.load()` (analysis.py:92; tilt :123, radius :135); per-segment in `segment_stats()` (:361); per-corner in `corner_stats()` (:154). How it reaches the report: `analyse()` → `cmd_report`'s `full` dict → `analysis.json` `segments`; the human table in `report.py` (`build_report` :1120, segment row :1229). States that a new key reaches `analysis.json` automatically and `report.md` only if you render it, because `analysis.json` is a deliberate superset. Names the one real decision the procedure faces: analysis.py:129-130 sets `turn` and `radius` to `None` **together** when either neighbour lacks a heading — the per-sample analogue of the `segment_stats` docstring, and what turns §7 from a list of locations into a procedure. Constants rule worked both directions: `IMPACT_DROP_KMH` is calibration, animation seconds and SVG frames are presentation. And: a measurement may need no constant at all. Closes noting every existing measurement predates the restructure, so nobody has walked this path.

**§8 The two hard constraints.** No third-party dependency on the analysis path (`pyproject.toml` `dependencies = []`, ADR decision 2); never commit a game asset, extracted track XML, replay, report or pilot profile. Names both mechanisms: the `.gitignore` entries covering `*.csv`, `replays/`, `reports/`, `data/`, `trackdata/`, `liftoff-pilot.md`, and `refuse_inside_toolkit()` (toolkit.py:87).

**§9 How a change is verified here.** Opens: no test suite, by decision, and "the tests pass" is not a claim available here — pointing at `PROJECT_BRIEF.md`'s settled question 2 so it reads as a decision, not an omission. Then:

- **Setup: capture and check as one unit**, both shells, per the three-outcome table. States what a correct `$FPV` looks like, and that a wrong one means Python will fail naming a path inside whatever repository you were standing in. No CPython error string is quoted (Risks 9).
- **Work directory: `~/fpv-work`.** `~` expands in both shells, is the same printed string on every machine, and is outside both the clone and the skills folder. If the folder already exists, skip to `cd fpv-work` — `mkdir` errors on a second run in both shells and PowerShell's `mkdir` takes no `-p`, so there is no single idempotent form.
- **Replay path: obtained, not typed.** `python "$FPV/src" replay --latest` archives one into `replays/` and prints the path; every later example uses what it printed. (`replay --latest` at replay.py:176; `--archive-dir` defaults to `replays` at replay.py:179-180.) The guide explains why later runs pass the explicit path and never `--latest`: it re-archives and re-picks, so the two runs would not compare the same flight.
- **What legitimately differs:** `analysis.json`'s `generated`, and the generated-by footer in `report.md` and `report.html`. Nothing else, or the change was not a no-op.
- **The strictest instrument, named as one:** the `view` page embeds no timestamp, so two runs over unchanged code compare byte-for-byte with nothing to excuse.
- One sentence recording that UC-01's two verification rules are deliberately excluded, per the use case.

**§10 How this project is built and evolved.** The `project-builder` harness at https://github.com/HaroldHormaechea/project-builder; `use-cases/` holds one formalized file per use case, `use-cases/plans/` the agreed implementation plan; `USE_CASES.md` is the status ledger. Two sentences on why they are committed. No instruction to use the harness.

**§11 Where to look next.** `README.md`, `SKILL.md`, `docs\engineering.md`, ADR-0001, one line each.

Throughout: one instruction per sentence, active voice, present tense, the terms table's spellings held to. No claim of ASD-STE100 conformance or certification. A sentence noting the guide prints forward slashes while the tool's usage line echoes backslashes, so a reader who notices does not "correct" something that is not broken.

### B. `cli.py` — criterion 14

Route cli.py:100 through `sim["tracks"].for_replay` and cli.py:104 through `sim["scene"].load_scene`. These are the only two bare sim references in the file, and no other command has one, so the criterion's "unlike every other command" is literally true. Module-level imports at cli.py:39/42 stay — still needed for `SIMS` and `add_sim_commands`. With one sim registered this changes no behaviour, which is why 18a exists.

### C. `cli.py` — criterion 16, registration

**One declaration, three consumers.** A single module-level table beside `SIMS`, partitioned required/optional, mapping each registration key to its module filename and what it enables. Three things read from it: the contract-key validation, the per-command gating, and the epilog text. Two hand-maintained lists of the required surface would be a drift risk built into the fix for a drift.

**Validation before anything runs or is written.** `build_parser` validates the contract keys before any `add_*` call and refuses naming **both what is missing and which module supplies it** — a contributor reading `missing: capabilities` should not have to work out what file that means. Zero bytes for Liftoff.

**Scope of validation, stated so the developer does not merge two mechanisms.** Validation is at the level of registration **keys**, not callables: do not import and introspect modules to confirm `source` exposes `load_flight` or `map` exposes both functions. The **function** surface is documented in ADR decision 4 and enforced by first use; the **key** surface is validated at registration. The six calibration module-level names are checked, since they are attributes of an already-imported module rather than an introspection of behaviour.

**The `THRESHOLDS` gap is closed, not carried.** `add_analyse`'s call to `analysis.build_parser(sim["calibration"])` is wrapped so a `KeyError` becomes a stated refusal naming the missing key and the sim's `sources/<sim>/calibration.py`. Zero duplication — the twenty keys stay encoded only in `build_parser`, their existing single source of truth — so this satisfies the one-declaration rule rather than straining it. With it the change has no path left where a missing piece of the contract produces a stack trace: a sentence for a missing module, a sentence for a missing name, a sentence for a missing key.

**No partial output on a failure path — a stated rule the developer is held to**, not a property that falls out of where the check sits, so that a later edit moving the check has something to violate. Measured twice: finding 3's aborted `report` left `flight.csv` and five SVGs behind, and a `{calibration, source, map}` package would write the output directory *and* a complete `flight.csv` (cli.py:315, 320) before the `KeyError` at cli.py:322.

**Gating.** Registration order preserved exactly — `view`, `analyse`, `report`, `pbs`, then `SIM_COMMANDS` order — because that is the order `--help` prints them in.

**`report` survives without `replay`.** cli.py:235's `--root` default becomes `str(sim["replay"].DEFAULT_ROOT)` when present, `None` when absent. Byte-safe: `add_report` uses `RawDescriptionHelpFormatter` (cli.py:229) and the help is a bare `"Recordings folder"` with no `%(default)s`, so the default is never printed. At run time `cmd_report`'s `if args.latest or path is None` branch (cli.py:301) refuses with a stated reason rather than raising, naming both routes into it, since omitting the positional argument enters it too.

**The epilog.** Top-level parser only, last, nowhere else — naming each omitted command, the module it needs, and `report --latest`. When nothing is omitted the keyword is not passed. Measured: 162 bytes both ways on an isolated parser, 1568 both ways on the real `cli.build_parser()`. Mechanism: `add_text` admits `""`, `_format_text("")` returns `'\n\n'`, and `format_help`'s closing `help.strip('\n') + '\n'` erases it *because the epilog is last*. **The constraint is positional, not about the empty string** — recorded as a measured non-issue so the next reader does not re-litigate it.

**Accepted residual, into the ADR beat:** `--sim foo view` on a package lacking `tracks` gives argparse's "invalid choice" error, and argparse prints no epilog on error. Loud, and the answer is one `--help` away.

### D. `docs\adr\0001-multi-sim-architecture.md` — a named deliverable, four edits

Reviewed as one artifact, with each edit checked against the thing it documents.

1. **Decision 4 — registration tolerance.** The four modules are the contract; a conformant package registers and gets `analyse` and `report`; the six other keys are per-sim extras enabling named commands, absences reported in `--help`. Beat: correcting the ADR to describe the ten-key shape was cheaper and was rejected — it would have published a registration shape nobody designed and left the contract untrue rather than making it true. Records that before this change a conforming package raised `KeyError('replay')` at parser construction.
2. **Decision 4 — the function surface:** all four contract modules' signatures and returns, plus `tracks.for_replay` and `scene.load_scene`, which criterion 14 makes contractual in this same run.
3. **Decision 7 — the six calibration names**, plus the note that the twenty `THRESHOLDS` keys are reached at registration by construction and are refused there by name.
4. **Consequences § "Degradation stays explicit"** — rewritten for criterion 17.

Applied under the standing rule: where the guide cannot cite because the ADR is silent, the ADR gets the content and the guide cites it.

### E. The two capabilities docstrings — criterion 17

Amend both module docstrings to describe the mechanism as provided and not yet called. `gap()`'s own docstring stays: it correctly describes what the function does when called.

### F. `sources\__init__.py` — criterion 15

Add `capabilities.py` with the ADR's phrase ("what it cannot supply"), keeping the sentence shape and the closing ADR pointer. Docstring only.

### G. `cli.py` — criterion 20, the `view` guard

In `cmd_view`, before the `for_replay` call at cli.py:100, test whether `Path(args.track_dir) / "index.json"` exists. If it does not, `sys.exit` with a stated reason and a runnable command built by `toolkit.command("tracks", "-o", args.track_dir)` — `-o` because that is the flag `tracks.build_parser()` uses for the index location (tracks.py:520), and its default `trackdata` matches `--track-dir`'s. The message follows `scene.load_scene`'s two-line shape (scene.py:462-465): what is missing, then `Build it: <command>`.

**Three things this deliberately does not do**, each protecting something measured:

- It does **not** touch `tracks.load_index`. That is finding 3's trap: `sys.exit` there raises `SystemExit`, which escapes `geometry_for`'s `except Exception` and converts `report`'s clean degrade into an exit-1 abort with a partial output directory.
- It does **not** touch `cmd_report`, which already degrades cleanly at exit 0 in this situation and whose behaviour criterion 18 protects.
- It does **not** change the existing uncached-*scene* refusal, which is a different and already well-behaved case. **Verification 4 asserts that refusal verbatim**, so tidying its wording while implementing this would fail a check in this plan without touching the code that check exists to cover.

## Files Affected

- `C:\dev\liftoff-flight-analyzer-uc-02-contributing\CONTRIBUTING.md` — replaced (1–12, 19)
- `…\src\fpv_review\cli.py` — 14 (§B), 16 (§C), 20 (§G)
- `…\src\fpv_review\sources\__init__.py` — 15 (§F)
- `…\src\fpv_review\common\capabilities.py` — 17 (§E)
- `…\src\fpv_review\sources\liftoff\capabilities.py` — 17 (§E)
- `…\docs\adr\0001-multi-sim-architecture.md` — 16, 17 (§D)

Not touched: `README.md`, `SKILL.md`, `docs\engineering.md`, `PROJECT_BRIEF.md`, `examples/`, every other module under `src/`. `USE_CASES.md` and the plan file are the orchestrator's.

## Verification

**In place, never a temp clone.** `PROG` comes from `toolkit.invocation()` built on the resolved `TOOLKIT_ROOT`, and the resolved clone path sits in line 1 of all ten help outputs — the usage line reads `usage: python "C:\dev\liftoff-flight-analyzer-uc-02-contributing\src"`. A temp-clone before against a worktree after does not merely add noise, it **cannot pass criterion 16 at all**, on every one of the ten surfaces.

Every run: `cwd` = `C:\dev\liftoff-uc02-run`, explicit archived paths, never `--latest`, never `pbs --save`, fresh `-o` subdirectory, `--no-auto-open` where applicable.

1. **Baseline — frozen, do not re-capture.** `C:\dev\liftoff-uc02-run\baseline\` (119 files, `baseline-sha256.txt`), taken while `src/` equalled `main`.
2. **Criterion 18.** Re-run `report` on all four replays; diff against baseline. Only the 27 known noise files differ, each only on its known line: `"generated"` in `analysis.json`, the footer in `report.md`/`report.html`, the `-o` value in `logs/*.cmd` and `logs/*.out`. All four `flight.csv` and every SVG byte-identical.
3. **Criterion 18a, three replays.** `cmp` the `view` pages against baseline: byte-identical at 222,363 / 187,422 / 288,951 bytes. The only check that executes the code criterion 14 changes.
4. **Criterion 18a, fourth replay.** `view` on the Woodpecker replay still exits 1, writes no file, prints the captured refusal verbatim including a runnable `Build it:` line. **Do not build that scene cache.** §G's third constraint exists to protect this.
5. **Criterion 16 — the "before" is frozen and named:** `C:\dev\liftoff-uc02-run\baseline\logs\help-{root,view,analyse,report,pbs,replay,tracks,scene,props,telemetry}.{cmd,out,err,exit}`. Ten parsers, `help-root.out` 1602 bytes through `help-analyse.out` 8188, `help-root.out` still byte-identical to the worktree. Compared byte-for-byte including trailing whitespace. **Must not be re-captured** — once `cli.py` is edited that capture is unreproducible in place, and a developer told only to "compare before and after" is one step from the temp clone.
6. **Criterion 20.** With `--track-dir` at a directory holding no `index.json`: `view` exits 1 with a stated reason and a runnable command, writes no file, prints no traceback. **In the same run**, `report` still exits 0, degrades with its note, and writes a complete output directory — not optional, because the measured trap was a fix that passed the first half and broke the second.
7. **Criterion 16's refusal paths.** A sim dict missing a contract key refuses at registration, before any command runs and before any file is written, naming the key and its module. A `calibration.THRESHOLDS` missing a key refuses the same way, naming the key and the sim's `calibration.py`. No partial output directory in either case.
8. **Criterion 10.** Every command the guide prints, run as printed, in PowerShell and bash, from `~/fpv-work`. Not read — run. Including the `$FPV` check against all three outcomes.

## Risks & Considerations

1. **The `--root` conditional is the top byte risk.** Any edit touching its `help=` string, argument order or formatter class moves `--help`, and unlike the epilog nothing strips the difference.
2. **Registration order**, second: the table-driven `add_*` calls must preserve `view, analyse, report, pbs, SIM_COMMANDS`.
3. **The epilog**, third, positional constraint only — demoted from where I first had it, wrongly.
4. **Criterion 14 cannot be proven correct by any check available here.** One entry in `SIMS` means `sim["tracks"] is tracks`, so 18a proves the correction broke nothing and cannot prove the bug is gone. Verified by reading and by confirming the call routes through `sim[...]`.
5. **The guide asserts things the criterion-16 change makes true.** §5's "four modules are enough to register" is false against `main`. If the code change were dropped, §5 would need rewriting, not footnoting.
6. **`report --latest`'s help stays Liftoff-specific.** Wrong wording for another sim; correcting it would move `--help` and fail criterion 18. A candidate for the second-sim run.
7. **The ADR is amended in four places by a run whose theme is documentation drifting from code**, so it gets the same scrutiny as the code.
8. **`docs\engineering.md` overlaps §7.** §7 must describe the procedure and link there for what the existing measurements mean, or criterion 12 is breached in the most tempting section.
9. **Do not quote an error string this project does not own — a rule for the guide, not only a fix.** CPython has reworded both shapes across releases and prefixes each with the interpreter's full path, and `pyproject.toml` declares `requires-python = ">=3.9"`, so quoting a 3.14 message is a **version-varying claim — the same defect family as the machine-varying paths removed from §9, on a different axis.** The guide would be wrong on some supported interpreter with no way to notice, since nobody here has a 3.9 to check against. **The tool's own messages stay quotable**: this project controls them and this run is fixing four of them, so §9's expected outputs, 18a's captured refusal and criterion 20's new message are all fair to print — only somebody else's release is not. For a wrong `$FPV` the guide teaches the invariant instead: the path in the error is not your clone.
10. **Three defects in this plan's own preparation were caught by re-running or re-reading, never by reasoning**, and the developer and QA will meet the same temptations. An `epilog=""` byte cost asserted from argparse's source and disproved by running it; a CPython error string reported as observed when the case that produced it could not have printed it; and an agreed section silently lost when six messages were consolidated into one. The pattern: a claim about what a program *would* print, and an artifact that *was* agreed, both degrade quietly. Run the command; diff the document against the list of things it must contain.

---

# Addendum — three items adopted by the lead

All three come from the rejected duplicate plan. The challenger judged them additive, touching no settled ruling, and verified the one that is a printed command. All three are adopted:

1. **A falsification step for the import check (§A §4).** After running the scoped grep and seeing no output, add a temporary `from fpv_review.sources.liftoff import tracks` to a file under `common/`, re-run the check, watch it match, then revert. This is the project's own standing rule — *a check nobody has watched fail proves nothing* — applied to the one check the guide asks a contributor to trust. **It goes in the plan's Verification section, NOT in the guide** — both the challenger and the document's own author said so, and the lead's first draft of this addendum had it backwards. The guide stays procedural, per the use case. Use `from fpv_review.sources.liftoff import calibration` in a `common/` module, confirm each shell form prints exactly one line, revert.
2. **An idempotent work-directory step (§A §9).** `mkdir -p ~/fpv-work` in bash and `New-Item -ItemType Directory -Force "$HOME\fpv-work"` in PowerShell, rather than instructing the reader to skip a line on a second run. This **supersedes** §9's sentence claiming no single idempotent form exists — that sentence is true only of bare `mkdir`.
3. **The capture's ordering and its precondition, stated inside the block (§A §9).** Put the `$FPV` capture **before** the move to the work directory, and head each block with the prose line *"Run this from inside your clone."* That ordering is precisely what the three measured outcomes are about, and v5 only implies it. The prose line is not a printed path, so criterion 10 still holds. **Verified by the challenger**, since a contributor pastes this: in PowerShell `$FPV = git rev-parse --show-toplevel` yields a forward-slash path, and `Test-Path "$FPV\src\fpv_review\cli.py"` — mixed separators — returns `True` from inside the clone **and** from `C:\dev\liftoff-uc02-run` with `$FPV` still set. Windows accepts the mixed form, so the recipe runs as printed in both shells.

**Take nothing else from that document.** Its `validate_sim`, `omitted_epilog`, `GATED` and rewritten `build_parser` are unreviewed code; §C above specifies the same behaviour at the level the review actually covered.

**Rejected from the same document, recorded so it is not reintroduced:** hardcoding `$FPV = "$HOME\.claude\skills\fpv-review"`. That is the *install* path from the README; a **contributor clones wherever they like**, which is the distinction the entire `git rev-parse` two-step exists to serve. The rejected text conceded the consequence itself — on a machine without that path, the recipe printing `FAILED` "is the designed outcome" — which is not a setup recipe, and leaves the reader no way to obtain a correct `$FPV`. The author of that document conceded the defect on its own analysis before any ruling: the three measured outcomes — clone, empty, another repository — only make sense for a capture that reads the *current* repository, so a hardcoded install path cannot have been what they were measured against.

## How the duplicate arose — a lead error worth recording

The second plan was **not a competing proposal. It was a recovery attempt against a loss that had not happened.** When the account limit killed the first pair mid-round, the lead concluded the approved text was gone — the agents held it only in memory — and briefed a fresh analyst to reconstruct it from the record. The original pair then came back alive after the limit reset, still holding v5, and finished.

The cost was one wasted analyst run and a near-miss: an unreviewed reconstruction carrying a real criterion-10 defect nearly displaced a six-round-reviewed original, and was caught only because both arrived in the same batch. **The lesson for the next handoff: confirm an agent is actually dead before declaring its work lost.** `ListAgents` reports liveness; a failure notification reports only that a turn ended. The two are not the same, and the difference is what separates a recovery from a duplicate.

---

# Status after merge — QA outstanding

**Merged to `main` as `ed1bec3` (PR #2) on 2026-08-30, before independent QA ran.**
The author authorised the merge explicitly. All seven sections are implemented and
the developer's own verification is recorded above and in the PR body; what has
**not** happened is verification by anyone other than the agent that wrote the code.

The ledger row stays `in-progress` rather than `done` for that reason: the ledger's
`done` means implementation *and* verification, and only the first is true.

## What QA still has to do, and against what

The frozen baseline at `C:\dev\liftoff-uc02-run\baseline\` (119 files,
`baseline-sha256.txt`) is intact and was captured while `src/` was byte-identical
to `main`. It is still the correct reference — the merge did not touch it, and
comparing `main` against it is exactly as valid as comparing the branch was.

Run directory unchanged: `C:\dev\liftoff-uc02-run` with `trackdata/` (187 entries),
`data/liftoff_history.json`, `replays/` (four archived). Same rules — explicit
archived paths, never `--latest`, never `pbs --save`, fresh `-o`.

**Claims to check rather than accept**, all from the developer's own runs:

- ten `--help` surfaces byte-identical (root 1602 … telemetry 2858)
- three `view` pages byte-identical at 222,363 / 187,422 / 288,951
- Woodpecker `view` exits 1, writes no file, refusal byte-identical
- 27 of 39 report artifacts byte-identical; 12 differ on one timestamp line each
- a four-module package registers, yields exactly `['analyse', 'report']`, and
  produces a complete 12-file report on an explicit path
- all three refusal shapes name the missing item **and** its file, leaving no
  output directory
- criterion 20 both halves in the same state: `view` refuses cleanly, `report`
  still exits 0 and writes a complete directory
- all 17 commands the guide prints run as printed, in both shells

**Where to look hardest:** criterion 10 (every printed command runs as printed —
the developer found three of its own wrong by running them; find the fourth if
there is one), criterion 2 (citation not restatement), and the five ADR
amendments checked against the code they document.

**One trap already paid for:** the frozen help captures carry **CRLF**; a naive
comparison against LF-emitting output reports ten false differences on the last
line. Normalise before concluding. The lead lost time to this once.

## A process finding from this run, for the harness rather than the project

The developer read the approved plan **once** at the start and worked from that
copy through all seven sections. A correction committed after that read
(`5d4dc56`, moving the falsification step out of the guide) never reached it; the
right instruction was followed only because the lead happened to restate it in a
later brief. **A plan file is durable so it can be re-read; treating it as a
one-time load defeats that.** Re-reading at each section boundary costs almost
nothing and closes the gap.
