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

## Second attempt, 2026-08-30 evening: five more rounds, nine Majors, all resolved

The loop was restarted with the eight findings above as inputs. It ran five more
rounds and closed nine Majors, then **died one message short of approval** when the
account hit its monthly spend limit. The full proposal text was exchanged between
the two agents but **never reached the lead**, so there is still no `PLAN_FILE` to
implement from — what follows is the complete set of decisions, which is enough to
reconstruct one.

### Settled by ruling (the lead)

1. **The six `calibration.py` names go into ADR-0001 decision 7**, and the
   decision-4 amendment is extended to cover the function surfaces of the contract
   modules (`props_near`, `geometry_for`, `declare()`), which the ADR documents
   nowhere. **Standing rule, now applied three times: where the guide cannot cite
   because the ADR is silent, the ADR gets the missing content and the guide cites
   it.** Criterion 2 makes restatement illegal, so an ADR gap leaves one legal move.
2. **The epilog names `report --latest`**, not only whole commands — `report`
   survives a partial contract *except* for that flag, so the flag is where the
   remaining gap lives.
3. **Registration validates before anything executes or is written**, refusing with
   a named reason that gives **both** the missing item **and the module that
   supplies it**. Half of that ("`capabilities` is missing") tells a contributor
   *what*; the whole of it ("…from `sources/<sim>/capabilities.py`") tells them
   *what to do*.
4. **The validation boundary is enumerated-versus-introspected, not
   keys-versus-attributes.** Validate the registration keys plus the six named
   module-level constants in `calibration.py`. Six names written down is a list, not
   a mechanism, and cannot drift into walking a namespace. **Importing contract
   modules to discover their function surface stays forbidden** — those live in the
   ADR and are enforced by first use, because that check would cost more than it
   protects.
5. **Do not quote an error string the project does not own.** The tool's own
   messages are quotable — we control them, and this run fixes four. CPython's are a
   claim about someone else's release, and quoting a 3.14 message against a
   `requires-python = ">=3.9"` floor is a **version-varying claim, the same defect
   family as the machine-varying paths removed from the guide, on a different
   axis** — unnoticeable here because nobody has a 3.9 to check against.

### Measured this round

| finding | measurement |
|---|---|
| The `THRESHOLDS` residual closes in three lines | `try/except KeyError` around the `analysis.build_parser(sim["calibration"])` call in `add_analyse`. **Duplicates nothing**: the twenty keys stay encoded only in `build_parser` (20 direct `T["…"]` lookups at `analysis.py:402`, reached at registration via `cli.py:146`; `default_args` routes through the same function at `analysis.py:486`). Satisfies the one-declaration rule rather than straining it. |
| The `KeyError` lands after a **complete** `flight.csv` | `outdir.mkdir` at `cli.py:315`, `schema.write_csv` at `:320`, `declare()` at `:322`. Not partial debris — a finished-looking artifact from a failed run, which is worse. |
| The nested-repo failure has **two** shapes | no `src/` → `can't open file '…\src': [Errno 2] No such file or directory`, exit 2. `src/` without `__main__.py` → `can't find '__main__' module in '…\src'`, exit 1. |
| …and a third reason not to quote either | CPython prefixes both with the **interpreter's full path**, which would have smuggled a machine-varying path back into the guide through the one door criterion 10 was not watching. |
| `epilog=""` is a non-issue | Byte-identical to omitting the keyword: **1568 bytes both ways** on the real `cli.build_parser()`, 162 both ways on an isolated parser. `HelpFormatter.format_help`'s closing `strip('\n')` erases it. Recorded so the next person who notices it does not re-litigate. |
| The naive import grep is wrong | `grep -rn "fpv_review.sources" common/` returns **2 hits on clean `main`** — a prose line in `__init__.py` plus a `__pycache__` binary match. The scoped form returns nothing. |

### Two design corrections worth keeping

- **`~/fpv-work`, never `cd "$FPV/.." && mkdir fpv-work`.** With the README's
  documented install path the latter resolves to `~/.claude/skills/fpv-work` —
  inside the folder Claude Code scans for skills. That is ADR-0001 decision 5's own
  reasoning reappearing one directory up, **inside the guide written to teach that
  rule**, in a spot `refuse_inside_toolkit()` does not cover because an ordinary
  clone is exactly what that guard is designed not to block.
- **The `$FPV` capture prints with its verification as one unit.** The recipe was
  accepted partly because it fails loudly from the wrong directory — but that
  loudness is an accident of this machine (`C:\dev` is not a repo). A contributor
  whose work directory sits inside any repository of their own gets **that**
  repository's path back, exit 0, no warning. The failure is then **misdirected
  rather than silent**: Python names a path inside the contributor's own project,
  which reads as a broken clone rather than a mis-set variable. The check built and
  tested for this is the existence of `$FPV/src/fpv_review/cli.py` — a file only
  this repository has — verified across all three outcomes in both shells (clone
  `OK`/`True`; empty `FAILED`/`False`; other repo `FAILED`/`False`).

### The one gap when the run died

**Criterion 20's fix was dropped from the Proposed Solution during consolidation.**
The final draft ran §A guide, §B criterion 14, §C criterion 16, §D ADR, §E
docstrings, §F `sources/__init__.py` — **with no section for criterion 20.** Files
Affected listed `cli.py — 14, 16, 20` and the verification section tested it, but a
developer implementing §A–§F would have built five of six changes. The Analysis
diagnosed the trap and said the guard belongs in `cmd_view`, which is diagnosis,
not instruction.

**Three constraints also fell out in the same consolidation**, and one of them
protects a verification step inside the plan itself:

1. **Do not repair `tracks.load_index`** — the `SystemExit` trap, measured.
2. **Do not touch `cmd_report`** — it degrades correctly today.
3. **Do not tidy `scene.load_scene`'s wording** while implementing criterion 20.
   The verification asserts the Woodpecker refusal **verbatim**, so a developer who
   rewords it fails a check in this plan without ever touching the code that check
   exists to cover.

A resumed run restores those four items; everything else was approved.

### A process finding worth carrying into implementation

**Twice in this run, an inferred result was recorded as a measurement**, and both
times it was caught only because someone re-ran it: the `epilog=""` claim, and an
error string reported for a case the scratch repository could not have produced (it
had no `src/`, so that message could not have been printed). Neither survived, but
neither was caught by review of the reasoning — only by execution. **The temptation
is strongest exactly where a check "obviously" would have printed something.**

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
