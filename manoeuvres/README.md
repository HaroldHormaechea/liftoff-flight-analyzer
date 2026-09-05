# Manoeuvre library

Pre-rendered freestyle manoeuvres, drawn with the same code the flight reports
use: `common/report.py` primitives for the flat figure, `common/incident_view.py`
for the 3D view. They are TEMPLATES - synthetic, parametric, not flown - so they
can be committed and reused, unlike anything under `reports/` or `replays/`.

Regenerate with `python manoeuvres/build_manoeuvres.py`. Nothing in this
folder is hand-edited - the next build overwrites it, this README included.
**The guidance lives in `docs/manoeuvres.md`;** this file is just the inventory.

| manoeuvre | slug | length | inverted | height |
|---|---|---|---|---|
| Orbit | `orbit` | 8.0 s | 0% | 2-2 m |
| Figure eight | `figure-eight` | 10.0 s | 0% | 2-2 m |
| Axial roll | `axial-roll` | 4.0 s | 24% | 3-3 m |
| Backflip | `backflip` | 2.6 s | 48% | 2-6 m |
| Split-S | `split-s` | 3.7 s | 50% | 4-12 m |
| Immelmann | `immelmann` | 3.7 s | 50% | 3-11 m |
| Power loop | `power-loop` | 6.8 s | 25% | 2-8 m |
| Dive and pull-out | `dive` | 3.2 s | 0% | 0-18 m |

## Embedding

**In a report** copy the SVG into that report's own `assets/` and reference it
from there, so the report folder stays portable:

    python manoeuvres/build_manoeuvres.py --install <report-dir> split-s
    ![Split-S](assets/split-s.svg)

**In an HTML page** (report.html, a plan) use the fragment, and put one copy of
`viewer.js` and `manoeuvres.css` where the page can reach them:

    <link rel="stylesheet" href="manoeuvres.css">
    <script>window.__fpvViewerSrc = 'manoeuvres/viewer.js';</script>
    ...paste split-s.fragment.html...

Fragments are self-registering: the first one on a page loads `viewer.js`, the
rest wait for it. Any number can sit on one page.

Use `<slug>.bare.html` instead of the fragment when the page would rather
initialise every viewer itself in one pass - it is the same markup and data with
no script of its own.

**On their own** open `<slug>.html`. That one inlines everything.

## What the figure shows

Path coloured by speed, on the same ramp as every lap map in a report. The bar
across the path is the airframe and the spike is the top of the quad; both go
red once the quad is inverted. Loops are drawn side-on because a loop seen from
above is a straight line.

Speed is derived from the path by finite difference, so the colour means what it
means on a real recording. Stick positions are NOT modelled and are left at
zero - a synthetic throttle trace sitting in the same schema as a measured one
is a trap.
