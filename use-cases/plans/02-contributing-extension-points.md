---
plan_for: use-cases/02-contributing-extension-points.md
work_branch: feat/uc-02-contributing
team: session-5db7517b
status: INTERRUPTED — baseline captured, proposal not yet approved
date: 2026-08-30
---

# UC-02 — interrupted run: what is established, and what is not

**The analyst/challenger loop did not finish.** The session hit its usage limit at
round 4 of 6, killing the analyst mid-v6, the challenger mid-verification of v5,
and QA mid noise-floor diff. **No implementation started; `src/` is byte-identical
to `main`.** This file records what was measured before the interruption, so a
resumed run inherits it instead of re-deriving it — the lesson UC-01 learned when
its verification tooling was deleted and only the committed § 15a survived.

## The baseline IS captured, and it is valid

Captured while `src/` still equalled `main`, which was the one window that could
not be reopened once implementation began.

**Location:** `C:\dev\liftoff-uc02-run\baseline\` (119 files), frozen with
`baseline-sha256.txt`. Verified identical to the `reports-p1` / `views-p1` /
`logs-p1` capture it came from. The `-p2` trees are the second pass, kept only as
the noise-floor control.

**Run directory** — the fixed `cwd` for every comparison in this engagement,
before and after: `C:\dev\liftoff-uc02-run`, holding `trackdata/` (187 entries
with `index.json`, `props.json`, `scenes/` for `HangarC03`, `LiftoffArena`,
`PineValley`, `Rustline`), `data/liftoff_history.json`, and `replays/` with the
four archived replays. **The archive filenames are byte-identical to UC-01's**,
because archiving stamps from the replay's own `creationTime` — so UC-01's § 15a
notes apply directly.

**Entry point used:** `python "C:/dev/liftoff-flight-analyzer-uc-02-contributing/src" <command>`,
always with `cwd` set to the run directory, always with archived paths passed
explicitly, **never `--latest`**, and `--no-auto-open` (canonical; `--no-open` is
a deprecated alias). `pbs --save` was never run and must not be.

### The measured noise floor

Two identical passes over unchanged code: **92 files byte-identical, 0 files
present in only one pass, 27 differing.** Every one of the 27 is a timestamp or a
path artifact of the `-o` name:

| what differs | where |
|---|---|
| `"generated"` | `analysis.json`, one line, all four replays |
| footer `generated … by` | `report.md` and `report.html`, one line each, all four |
| the `-o` value | the `logs/*.cmd` and `logs/*.out` records only |

**Everything else is signal.** In particular, across the two passes:

- all four `flight.csv` — **byte-identical**
- all SVG assets — **byte-identical**
- all three `view` pages — **byte-identical**

### Criterion 18a's instrument is calibrated

The `view` pages reproduce byte-for-byte across runs of unchanged code:

| page | bytes |
|---|---|
| `arena.html` (LiftoffArena) | 222,363 |
| `canary.html` (Rustline 122843) | 187,422 |
| `pinned.html` (Rustline 125608) | 288,951 |

`incident_view.page()` embeds **no timestamp** — the only two timestamp sites in
the tree are `report.py:1271` and `cli.py:446` — so `cmp` on these pages is a
true zero-tolerance instrument with **nothing to excuse**. It is the strictest
check in the run, and the only one that touches the code criterion 14 changes.
These numbers were measured independently by the challenger and reproduced here.

### The Woodpecker refusal contract, captured verbatim

`view` on `20260830-183818_TheRussianWoodpecker_Race_1lap` — whose scene is
deliberately **not** cached, and must not be built:

```
exit 1
no cached scene for TheRussianWoodpecker.
Build it: python "<clone>\src" scene --environment TheRussianWoodpecker
NO-FILE-WRITTEN
```

Criterion 18a asserts this rather than comparing a page, so that the run keeps its
only coverage of `view` refusing where `report` degrades. Note the printed command
embeds the **resolved** clone path — the link-install consequence ADR-0001 already
records, surfacing again.

## Established by measurement, not yet implemented

Everything below was proven during the analysis loop and should be inherited
rather than re-argued.

1. **The documented per-sim contract cannot be satisfied.** A package conforming to
   ADR-0001 decision 4's four modules raises `KeyError('replay')` during **parser
   construction** — `python src --sim <new> --help` fails before any command runs.
   Adding keys one at a time gives the required order `replay` → `pbs` → `tracks` →
   `scene` → `props` → `telemetry`; all ten are required, **none optional**. The
   contract is wrong about six of ten keys. Reproduced independently by both agents.
2. **`calibration.py` must expose exactly six names** — `THRESHOLDS`,
   `IMPACT_DROP_KMH`, `IMPACT_DEBOUNCE_SAMPLES`, `PROP_NOMINAL`, `REC_RADIUS_M`,
   `CAM_SPAN_M` — and omitting any breaks at first use. Absent from ADR-0001.
3. **Criterion 20's obvious fix is a trap, confirmed by running it.** Repairing
   `tracks.load_index` at source with a `sys.exit` refusal raises `SystemExit`,
   which derives from `BaseException` and is **not** caught by `geometry_for`'s
   `except Exception` — converting `report`'s clean exit-0 degrade into an exit-1
   abort, in the exact path criterion 18 protects, introduced by the fix meant to
   make failure cleaner. Measured three ways:

   | variant | `report` | `view` |
   |---|---|---|
   | unpatched (today) | exit 0, degrades | exit 1, **unhandled traceback** |
   | `load_index` → `sys.exit` | **exit 1, aborts** | exit 1, clean message |
   | `load_index` → `raise FileNotFoundError` | exit 0, degrades | exit 1, **still a traceback** |

   **Guard in `cmd_view` instead.** And worse than predicted: the aborted `report`
   left a **partial output directory** behind — `flight.csv` and five SVGs, written
   before geometry was fetched — so "no output written" is a real assertion, not a
   formality. `view` writes nothing in all three variants.
4. **A silent-degradation hazard in the registration fix.** Today a non-conformant
   package fails loudly with `KeyError`. Making registration tolerant would give it
   a clean CLI that quietly offers fewer commands — which `PROJECT_BRIEF.md` forbids
   twice ("Degradation is explicit, not silent"; "failing loudly rather than
   degrading silently"). **Required clause:** a `--help` epilog naming the omitted
   commands, which for Liftoff is empty and must render as **zero bytes**, or the
   help comparison fails on every subcommand.
5. **The surviving subcommand set is `{analyse, report}`, not `{analyse}`.**
   `add_report`'s only registration-time need for `sim["replay"]` is the `--root`
   default; every other use sits inside the `--latest` branch. So `report` on an
   explicit path runs entirely on the four contract modules, and gating it would
   leave a conformant sim unable to do the one thing the contract exists for.
   `--latest` refuses clearly instead.
6. **The precondition is command-specific.** From a directory holding only a replay
   XML: `report` **exits 0** with a full report and a "no track data" note; `view`
   **cannot run at all**, and neither can `tracks --check`. So a saved replay can be
   *analysed* without the game but not *viewed* — and since 18a makes `view` the
   strictest check, a guide claiming "a replay file suffices" would be wrong about
   the very command the verification depends on.
7. **Do not carry § 15a's temp-clone recipe into this run.** `PROG` embeds the
   resolved clone path, so a temp-clone "before" against a worktree "after" is pure
   noise across the whole help surface — the surface criterion 16 most needs
   checked. The in-place route is correct here and was used: `git diff main -- src/`
   in the worktree is empty. § 15a was right for UC-01, where the whole tree moved;
   inherited unexamined it is the trap here.
8. **`pyproject.toml` is load-bearing, demonstrated accidentally.** A scratch copy
   of the tree without `SKILL.md` and `pyproject.toml` above it made `toolkit_root()`
   refuse — ADR-0001 decision 6's two-marker search working exactly as designed, in
   a case nobody constructed for it.

## What is NOT established

- **No approved proposal exists.** v5 was with the challenger, which had two
  outstanding Majors (the epilog clause, and the temp-clone/help-comparison
  incompatibility) and expected to approve v6. The full approved text was never
  produced, so there is no plan to implement from — a resumed run restarts the
  analyst/challenger loop, but with items 1–8 above as inputs rather than
  discoveries.
- **No code has been written.** Criteria 14, 15, 16, 17, 19 and 20 are all
  outstanding, and `CONTRIBUTING.md` is still the one-line placeholder.
- **Criterion 16's resolution is ruled but not implemented.** The lead ruled for
  making registration accept a contract-conformant package, scoped to command
  registration, on the grounds that ADR-0001 already published the contract, so the
  only remaining question is whether it is true — and a contract that fails at
  parser construction cannot be satisfied at all rather than merely having gaps.
  The challenger tested the affordability claim structurally and did not overturn
  it: `--sim` choices come from `sorted(SIMS)`, which holds one entry, so every
  added guard is taken in the "present" direction and the absent branches are
  unreachable. The output-unchanged constraint therefore holds for a structural
  reason, with 18a confirming it empirically rather than carrying the whole weight.
