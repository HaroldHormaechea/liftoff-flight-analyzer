#!/usr/bin/env python3
"""
liftoff_view.py - a 3D view of an incident: geometry, flight path, orbit, scrub.

ROUGH FIRST VERSION. This writes a standalone self-contained HTML page so the
look can be judged before any of it is folded into `fpv_report.py`. Nothing here
is wired into the report yet.

    python liftoff_view.py --replay replays/<file>.xml --at 6.0 -o crash.html

What it draws:

  * the environment's collision geometry, culled to a radius around the path
    (from `liftoff_scene.py`'s cache)
  * the TRACK PROPS near the incident, drawn as placeholders - see below
  * the flown path, coloured by speed
  * the quad at its true attitude, with a nose arrow, on a time scrubber
  * every impact found in the window, marked

Drag to orbit, wheel to zoom, drag the scrubber or press play.

WHY THE PROPS ARE PLACEHOLDERS
------------------------------
A track's props - ramps, barriers, arches - are placed by the Track XML and
instantiated from prefabs at runtime. They are NOT baked into the scene bundle,
so the scene cache does not contain them. Their POSITION and ROTATION are known
exactly; only their SHAPE is missing, because that lives in a prefab bundle that
is not extracted yet.

This matters more than it sounds: the crash this was built against hit a ramp
and a crowd-control barrier 2.3 m away, and nothing in the scene geometry is
within 8 m of the impact. Drawn from the scene alone, that crash looks like the
quad stopping in clear air. So props are drawn at their true position and yaw
with a NOMINAL size, in a different colour, and clearly labelled - a marker
saying "something is here", not a claim about what it looks like.

IMPACTS ARE DETECTED, NOT READ
------------------------------
The replay's `isCrashed` flag is unreliable - it reads false on a flight that
ends with the quad pinned against the ground at full throttle. So an impact is
found from the trajectory instead: a large speed drop inside one or two samples.
That signature caught both impacts in the reference crash, 0.7 s apart, where
the flag caught neither.
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import liftoff_replay as LR
import liftoff_scene as LS
import liftoff_tracks as LT

IMPACT_DROP_KMH = 20.0          # speed lost inside one 0.1 s sample
PROP_NOMINAL = (0.6, 1.0, 0.6)  # half-extents for a prop whose shape is unknown


def impacts(rows):
    """Sample indices where speed collapses - an impact, not braking.

    Braking bleeds a few km/h per sample; hitting something takes 20+ out in one.
    Reported once per event, not once per sample, so a two-sample collapse is one
    impact."""
    found, last = [], -99
    for i in range(1, len(rows)):
        drop = rows[i - 1][16] - rows[i][16]
        if drop >= IMPACT_DROP_KMH and i - last > 3:
            found.append(i)
            last = i
    return found


def props_near(track_dir, track_meta, route, points, radius, shapes=None):
    """Track items within `radius` of the path, classified by what they ARE.

    Three different things live in a track's blueprint list and drawing them
    alike is actively misleading - it was the first thing the pilot questioned
    about this view. Around one crash on Mexican Wave: 79 solid props, 31
    pass-through trigger volumes, and 3 route checkpoints.

      gate     a checkpoint the race routes through - the path, not an obstacle
      trigger  a pit volume (charge battery, repair props) or a spawn point.
               NOT SOLID. You fly through these; drawing them as obstacles
               invents collisions that cannot happen.
      prop     everything else: barriers, ramps, lights, boards. Solid.

    Position and yaw are exact. Shape is not known yet - see the module note."""
    root = LT.parse_xml(Path(track_dir) / track_meta["file"])
    on_route = set(route or ())
    out = []
    for item in LT.blueprints(root).values():
        if item["type"] in ("Action", "Spawnpoint"):
            kind = "trigger"
        elif item["id"] in on_route:
            kind = "gate"
        else:
            kind = "prop"
        for _t, q in points:
            if math.dist(item["pos"], q) <= radius:
                shape = (shapes or {}).get(item["item"], {}).get("colliders", [])
                out.append({"p": [round(v, 3) for v in item["pos"]],
                            "yaw": round(item["yaw"], 2),
                            "n": item["item"] or "?",
                            "k": kind,
                            "ap": item["aperture"],
                            # solid parts only: a trigger volume is not an obstacle
                            "sh": [c for c in shape if not c.get("trig")]})
                break
    return out


PAGE = """<title>__TITLE__</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; background:#0e1116; color:#c9d1d9;
         font:13px/1.5 ui-sans-serif,system-ui,"Segoe UI",Roboto,sans-serif; }
  #wrap { position:relative; width:100vw; height:100vh; overflow:hidden; }
  canvas { display:block; cursor:grab; }
  canvas.drag { cursor:grabbing; }
  #hud { position:absolute; top:12px; left:14px; pointer-events:none;
         text-shadow:0 1px 3px #000; }
  #hud b { color:#e6edf3; font-size:15px; }
  #hud .k { color:#8b949e; }
  #legend { position:absolute; top:12px; right:14px; text-align:right;
            pointer-events:none; text-shadow:0 1px 3px #000; }
  #legend i { display:inline-block; width:10px; height:10px; margin-right:6px;
              vertical-align:middle; border-radius:2px; }
  #bar { position:absolute; left:0; right:0; bottom:0; padding:10px 14px 14px;
         background:linear-gradient(transparent,#0e1116cc 40%); display:flex;
         gap:12px; align-items:center; }
  #bar input[type=range] { flex:1; accent-color:#4dd0c7; }
  button { background:#21262d; color:#c9d1d9; border:1px solid #30363d;
           border-radius:6px; padding:5px 12px; font:inherit; cursor:pointer; }
  button:hover { background:#30363d; }
  #t { font-variant-numeric:tabular-nums; min-width:112px; }
  .warn { color:#e3b341; }
  .k2 { color:#8b949e; }
</style>
<div id=wrap>
  <canvas id=c></canvas>
  <div id=hud>
    <b>__HEADING__</b><br>
    <span class=k>drag to orbit &middot; wheel to zoom</span><br>
    <span id=readout class=k></span>
  </div>
  <div id=legend>
    <span><i style="background:#5b6b7f"></i>scene collider</span><br>
    <span><i style="background:#e3b341"></i>solid track prop <span class=warn>(placeholder shape)</span></span><br>
    <span><i style="background:#4dd0c7"></i>route checkpoint</span><br>
    <span><i style="background:#3a4a5c"></i>pit trigger <span class=k2>(not solid, hidden)</span></span><br>
    <span><i style="background:#f0524d"></i>impact</span>
  </div>
  <div id=bar>
    <button id=play>Play</button>
    <input id=scrub type=range min=0 max=0 step=1 value=0>
    <span id=t></span>
    <button id=gates>Show route</button>
    <button id=trig>Show triggers</button>
  </div>
</div>
<script>
const D = __DATA__;
const cv = document.getElementById('c'), cx = cv.getContext('2d');
let yaw = 2.3, pitch = 0.45, dist = D.dist0, frame = 0, playing = false;
/* Route checkpoints and pit volumes are both OFF by default: neither is an
   obstacle, and the question this view answers is what the quad hit. They
   are one button away when the route itself is what you want to see. */
let showTriggers = D.showTriggers, showGates = D.showGates;
const tgt = D.target.slice();

function resize(){ cv.width = innerWidth * devicePixelRatio; cv.height = innerHeight * devicePixelRatio;
  cv.style.width = innerWidth+'px'; cv.style.height = innerHeight+'px'; draw(); }
addEventListener('resize', resize);

/* Unity is LEFT-handed (+Y up), so the camera basis uses right = up x forward.
   Using the right-handed cross product here mirrors the whole scene, which is
   subtly wrong in a way that is hard to spot and impossible to unsee. */
function basis(){
  const cp = Math.cos(pitch), sp = Math.sin(pitch);
  const cam = [tgt[0] - dist*cp*Math.cos(yaw), tgt[1] + dist*sp, tgt[2] - dist*cp*Math.sin(yaw)];
  let f = [tgt[0]-cam[0], tgt[1]-cam[1], tgt[2]-cam[2]];
  const fl = Math.hypot(f[0],f[1],f[2]); f = f.map(v=>v/fl);
  let r = [ 1*f[2] - 0*f[1], 0*f[0] - 0*f[2], 0*f[1] - 1*f[0] ];   // up(0,1,0) x f
  const rl = Math.hypot(r[0],r[1],r[2]) || 1; r = r.map(v=>v/rl);
  const u = [ f[1]*r[2]-f[2]*r[1], f[2]*r[0]-f[0]*r[2], f[0]*r[1]-f[1]*r[0] ];
  return {cam, f, r, u};
}
function project(p, B, W, H, focal){
  const v = [p[0]-B.cam[0], p[1]-B.cam[1], p[2]-B.cam[2]];
  const z = v[0]*B.f[0]+v[1]*B.f[1]+v[2]*B.f[2];
  if (z <= 0.05) return null;
  const x = v[0]*B.r[0]+v[1]*B.r[1]+v[2]*B.r[2];
  const y = v[0]*B.u[0]+v[1]*B.u[1]+v[2]*B.u[2];
  return [W/2 + focal*x/z, H/2 - focal*y/z, z];
}
function qrot(q, v){
  const [x,y,z,w] = q;
  const cx1 = y*v[2]-z*v[1], cy1 = z*v[0]-x*v[2], cz1 = x*v[1]-y*v[0];
  return [ v[0] + 2*(w*cx1 + y*cz1 - z*cy1),
           v[1] + 2*(w*cy1 + z*cx1 - x*cz1),
           v[2] + 2*(w*cz1 + x*cy1 - y*cx1) ];
}
function qmul(a, b){
  return [ a[3]*b[0] + a[0]*b[3] + a[1]*b[2] - a[2]*b[1],
           a[3]*b[1] - a[0]*b[2] + a[1]*b[3] + a[2]*b[0],
           a[3]*b[2] + a[0]*b[1] - a[1]*b[0] + a[2]*b[3],
           a[3]*b[3] - a[0]*b[0] - a[1]*b[1] - a[2]*b[2] ];
}
const CUBE = [[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]];
const FACES = [[0,1,2,3],[5,4,7,6],[4,0,3,7],[1,5,6,2],[3,2,6,7],[4,5,1,0]];

function boxFaces(centre, half, q, colour){
  const pts = CUBE.map(c => {
    let l = [c[0]*half[0], c[1]*half[1], c[2]*half[2]];
    if (q) l = qrot(q, l);
    return [centre[0]+l[0], centre[1]+l[1], centre[2]+l[2]];
  });
  return FACES.map(f => ({pts: f.map(i=>pts[i]), colour}));
}
function shade(hex, k){
  const n = parseInt(hex.slice(1),16);
  const r = Math.min(255,(n>>16&255)*k)|0, g = Math.min(255,(n>>8&255)*k)|0, b = Math.min(255,(n&255)*k)|0;
  return 'rgb('+r+','+g+','+b+')';
}
const LIGHT = (()=>{ const v=[0.4,0.85,0.3]; const l=Math.hypot(...v); return v.map(x=>x/l); })();

function draw(){
  const W = cv.width, H = cv.height, focal = H * 0.9;
  const B = basis();
  cx.fillStyle = '#0e1116'; cx.fillRect(0,0,W,H);

  const polys = [];
  for (const c of D.colliders){
    if (c.t === 'box') polys.push(...boxFaces(c.p, c.s, c.q, '#5b6b7f'));
    else if (c.t === 'cap'){
      const h = [c.r, c.r, c.r]; h[c.a] = Math.max(c.h/2, c.r);
      polys.push(...boxFaces(c.p, h, c.q, '#556077'));
    } else polys.push(...boxFaces(c.p, [c.r,c.r,c.r], null, '#556077'));
  }
  for (const p of D.props){
    if (p.k === 'trigger' && !showTriggers) continue;
    if (p.k === 'gate' && !showGates) continue;
    const a = p.yaw * Math.PI/180, s = Math.sin(a/2), cc = Math.cos(a/2);
    const q = [0,s,0,cc];
    const colour = p.k === 'gate' ? '#4dd0c7' : p.k === 'trigger' ? '#3a4a5c' : '#e3b341';
    if (p.sh && p.sh.length){
      /* Real prefab colliders, in the item's own frame: an instance is only ever
         the Track XML's position and yaw applied to that shape. */
      for (const c of p.sh){
        const l = c.p ? qrot(q, c.p) : [0,0,0];
        const w = [p.p[0]+l[0], p.p[1]+l[1], p.p[2]+l[2]];
        if (c.t === 'mesh'){
          /* Real triangles. A ramp's hull is two of them; its bounding box would
             be a slab with two vertical walls the game does not have. */
          for (const f of c.f){
            polys.push({pts: f.map(i => {
              const lv = qrot(q, c.v[i]);
              return [p.p[0]+lv[0], p.p[1]+lv[1], p.p[2]+lv[2]];
            }), colour, twoSided: true});
          }
          continue;
        }
        if (c.t === 'box')      polys.push(...boxFaces(w, c.s, qmul(q, c.q), colour));
        else if (c.t === 'sph') polys.push(...boxFaces(w, [c.r,c.r,c.r], q, colour));
        else { const h = [c.r,c.r,c.r]; h[c.a] = Math.max(c.h/2, c.r);
               polys.push(...boxFaces(w, h, qmul(q, c.q), colour)); }
      }
    } else {
      /* Shape unknown - a mesh-only prefab. Drawn dimmer: a marker saying
         something is here, not a claim about what it looks like. */
      polys.push(...boxFaces(p.p, D.propSize, q, p.k === 'prop' ? '#8a6d2f' : colour));
    }
  }

  const drawable = [];
  for (const poly of polys){
    const sp = poly.pts.map(p => project(p, B, W, H, focal));
    if (sp.some(p => !p)) continue;
    const ax = sp[1][0]-sp[0][0], ay = sp[1][1]-sp[0][1];
    const bx = sp[2][0]-sp[0][0], by = sp[2][1]-sp[0][1];
    const facing = ax*by - ay*bx;
    if (facing <= 0 && !poly.twoSided) continue;           // back face
    if (facing === 0) continue;                            // edge-on, no area
    const n = normal(poly.pts);
    const lit = 0.45 + 0.55*Math.abs(n[0]*LIGHT[0]+n[1]*LIGHT[1]+n[2]*LIGHT[2]);
    drawable.push({sp, z: sp.reduce((a,p)=>a+p[2],0)/sp.length, fill: shade(poly.colour, lit)});
  }
  drawable.sort((a,b)=>b.z-a.z);
  cx.lineWidth = devicePixelRatio;
  for (const d of drawable){
    cx.beginPath(); cx.moveTo(d.sp[0][0], d.sp[0][1]);
    for (let i=1;i<d.sp.length;i++) cx.lineTo(d.sp[i][0], d.sp[i][1]);
    cx.closePath(); cx.fillStyle = d.fill; cx.fill();
    cx.strokeStyle = 'rgba(0,0,0,.45)'; cx.stroke();
  }

  // flight path, coloured by speed
  cx.lineWidth = 3*devicePixelRatio; cx.lineCap = 'round';
  for (let i=1;i<D.path.length;i++){
    const a = project(D.path[i-1].p, B, W, H, focal), b = project(D.path[i].p, B, W, H, focal);
    if (!a || !b) continue;
    cx.beginPath(); cx.moveTo(a[0],a[1]); cx.lineTo(b[0],b[1]);
    cx.strokeStyle = ramp(D.path[i].v); cx.globalAlpha = i <= frame ? 1 : 0.28; cx.stroke();
  }
  cx.globalAlpha = 1;

  for (const i of D.impacts){
    const p = project(D.path[i].p, B, W, H, focal);
    if (!p) continue;
    const rr = Math.max(6, 260/p[2]) * devicePixelRatio;
    cx.beginPath(); cx.arc(p[0],p[1],rr,0,7); cx.strokeStyle='#f0524d';
    cx.lineWidth=2.5*devicePixelRatio; cx.stroke();
    cx.beginPath(); cx.arc(p[0],p[1],rr*0.34,0,7); cx.fillStyle='#f0524d'; cx.fill();
  }

  // the quad: a small body at its true attitude, plus a nose arrow
  const s = D.path[frame];
  const body = boxFaces(s.p, [0.16,0.06,0.16], s.q, '#e6edf3');
  for (const poly of body){
    const sp = poly.pts.map(p=>project(p,B,W,H,focal));
    if (sp.some(p=>!p)) continue;
    cx.beginPath(); cx.moveTo(sp[0][0],sp[0][1]);
    for (let i=1;i<sp.length;i++) cx.lineTo(sp[i][0],sp[i][1]);
    cx.closePath(); cx.fillStyle='#e6edf3'; cx.fill();
  }
  const nose = qrot(s.q, [0,0,1.4]);
  const a = project(s.p, B, W, H, focal);
  const b = project([s.p[0]+nose[0], s.p[1]+nose[1], s.p[2]+nose[2]], B, W, H, focal);
  if (a && b){
    cx.beginPath(); cx.moveTo(a[0],a[1]); cx.lineTo(b[0],b[1]);
    cx.strokeStyle='#4dd0c7'; cx.lineWidth=3*devicePixelRatio; cx.stroke();
  }
  document.getElementById('readout').textContent =
    s.v.toFixed(0)+' km/h   height '+s.p[1].toFixed(2)+' m';
  document.getElementById('t').textContent = 't = '+s.t.toFixed(1)+' s';
}
function normal(p){
  const a=[p[1][0]-p[0][0],p[1][1]-p[0][1],p[1][2]-p[0][2]];
  const b=[p[2][0]-p[0][0],p[2][1]-p[0][1],p[2][2]-p[0][2]];
  const n=[a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
  const l=Math.hypot(...n)||1; return n.map(v=>v/l);
}
function ramp(v){
  const k = Math.max(0, Math.min(1, v / D.vref));
  return k < 0.5 ? 'rgb('+(240)+','+(82+120*k*2)+','+(77+20*k*2)+')'
                 : 'rgb('+(240-163*(k-0.5)*2)+','+(202+6*(k-0.5)*2)+','+(97+102*(k-0.5)*2)+')';
}

const scrub = document.getElementById('scrub');
scrub.max = D.path.length-1; scrub.value = D.startFrame; frame = D.startFrame;
scrub.addEventListener('input', ()=>{ frame = +scrub.value; draw(); });
document.getElementById('gates').textContent = showGates ? 'Hide route' : 'Show route';
document.getElementById('trig').textContent = showTriggers ? 'Hide triggers' : 'Show triggers';
document.getElementById('gates').addEventListener('click', function(){
  showGates = !showGates;
  this.textContent = showGates ? 'Hide route' : 'Show route'; draw();
});
document.getElementById('trig').addEventListener('click', function(){
  showTriggers = !showTriggers;
  this.textContent = showTriggers ? 'Hide triggers' : 'Show triggers'; draw();
});
document.getElementById('play').addEventListener('click', function(){
  playing = !playing; this.textContent = playing ? 'Pause' : 'Play';
  if (playing) tick();
});
function tick(){
  if (!playing) return;
  frame = (frame+1) % D.path.length; scrub.value = frame; draw();
  setTimeout(()=>requestAnimationFrame(tick), 90);
}
let drag = null;
cv.addEventListener('pointerdown', e => { drag = [e.clientX, e.clientY]; cv.classList.add('drag');
  cv.setPointerCapture(e.pointerId); });
cv.addEventListener('pointerup',  e => { drag = null; cv.classList.remove('drag'); });
cv.addEventListener('pointermove', e => {
  if (!drag) return;
  yaw += (e.clientX - drag[0]) * 0.008;
  pitch = Math.max(-1.4, Math.min(1.4, pitch + (e.clientY - drag[1]) * 0.006));
  drag = [e.clientX, e.clientY]; draw();
});
cv.addEventListener('wheel', e => {
  e.preventDefault();
  dist = Math.max(2, Math.min(400, dist * (e.deltaY > 0 ? 1.12 : 0.89))); draw();
}, {passive:false});
resize();
</script>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--replay", required=True, help="archived replay xml")
    ap.add_argument("--at", type=float, help="incident time; default is the first impact")
    ap.add_argument("--pad", type=float, default=3.0, help="seconds either side (default 3)")
    ap.add_argument("--radius", type=float, default=25.0, help="metres of geometry (default 25)")
    ap.add_argument("--track-dir", default="trackdata")
    ap.add_argument("--scenes", default=None, help="default: <track-dir>/scenes")
    ap.add_argument("--props", help="prop shape table (default: <track-dir>/props.json)")
    ap.add_argument("--hide-route", action="store_true",
                    help="start with the route checkpoints hidden")
    ap.add_argument("--show-triggers", action="store_true",
                    help="draw pit trigger volumes from the start "
                         "(off by default; they are not solid)")
    ap.add_argument("-o", "--out", default="incident3d.html")
    args = ap.parse_args()

    meta, rows = LR.parse(args.replay)
    rows = LR.add_velocity(rows)
    hits = impacts(rows)
    t0 = rows[0][0]
    at = args.at if args.at is not None else (rows[hits[0]][0] - t0 if hits else 0.0)

    window = [r for r in rows if at - args.pad <= r[0] - t0 <= at + args.pad]
    if not window:
        sys.exit("no samples in that window; the flight is %.1f s long" % (rows[-1][0] - t0))
    points = [(r[0] - t0, (r[1], r[2], r[3])) for r in window]

    track, race, _tid, _rid = LT.for_replay(args.track_dir, args.replay)
    if track is None:
        sys.exit("this replay has no track, so there is no environment to draw")
    scenes = Path(args.scenes) if args.scenes else Path(args.track_dir) / "scenes"
    scene = LS.load_scene(scenes, track["environment"])
    kept = LS.cull(scene, points, args.radius)
    shapes = {}
    props_path = Path(args.props) if args.props else Path(args.track_dir) / "props.json"
    if props_path.exists():
        shapes = json.loads(props_path.read_text(encoding="utf-8"))["items"]
    props = props_near(args.track_dir, track, race["route"] if race else [],
                       points, args.radius, shapes)

    centre = list(window[len(window) // 2][1:4])
    if hits:
        near = min(hits, key=lambda i: abs(rows[i][0] - t0 - at))
        centre = list(rows[near][1:4])
    speeds = [r[16] for r in rows]
    data = {
        "colliders": kept,
        "props": props,
        "propSize": list(PROP_NOMINAL),
        "path": [{"t": round(r[0] - t0, 2),
                  "p": [round(r[1], 3), round(r[2], 3), round(r[3], 3)],
                  "q": [round(r[4], 4), round(r[5], 4), round(r[6], 4), round(r[7], 4)],
                  "v": round(r[16], 1)} for r in window],
        "impacts": [i for i, r in enumerate(window)
                    if any(abs(r[0] - rows[h][0]) < 1e-6 for h in hits)],
        "target": [round(v, 2) for v in centre],
        # Fit the camera to the PATH, not to the cull radius. At racing speed a
        # three-second window is ninety metres long, so a camera placed at the
        # radius sits inside the flight and half of it swings off screen.
        "dist0": round(min(140.0, max(15.0, 1.7 * max(
            math.dist(centre, (r[1], r[2], r[3])) for r in window))), 1),
        "vref": max(30.0, sorted(speeds)[int(len(speeds) * 0.9)]),
        "startFrame": 0,
        "showGates": not args.hide_route,
        "showTriggers": bool(args.show_triggers),
    }
    if data["impacts"]:
        data["startFrame"] = max(0, data["impacts"][0] - 3)

    heading = "%s &mdash; %s, impact at t=%.1f s" % (track["environment"], track["name"], at)
    page = (PAGE.replace("__TITLE__", "%s crash %.1fs" % (track["environment"], at))
                .replace("__HEADING__", heading)
                .replace("__DATA__", json.dumps(data, separators=(",", ":"))))
    Path(args.out).write_text(page, encoding="utf-8")
    print("%s  (%d colliders, %d props, %d samples, %d impacts)"
          % (args.out, len(kept), len(props), len(window), len(data["impacts"])))
    if scene.get("skipped"):
        print("  note: scene has no %s geometry; props are placeholder boxes"
              % ", ".join(scene["skipped"]))
    print("  impacts in the whole flight at t = %s"
          % ", ".join("%.1f s" % (rows[i][0] - t0) for i in hits))


if __name__ == "__main__":
    main()
