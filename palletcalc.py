#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pallet Load Calculator.

Computes uniform pallet loads: how many identical boxes fit on a pallet layer (boxes may
turn 90 degrees on the pallet face) and how many layers fit under the load height.

Modes:
  onpallet  Reproduces onpallet.com exactly (default). Runs phase 1 (recursive five-block
            algorithm) of the Birgin, Lobato and Morabito solver.
  best      Also runs phase 2 (L-approach) and returns the best layout found.

The solver is bundled in third_party/RecursivePartitioningAlgorithm (GPLv3) and must be
built once with `make`. A pure-Python solver is available with --allow-fallback; it is not
guaranteed to match onpallet.com.

Usage:
  palletcalc input.csv -o results.csv
  palletcalc --one 300 400 250 10 euro 1500
  palletcalc input.csv --mode best

See README.md for the input format and docs/SPEC.md for the full specification.
"""
__version__ = "1.0.0"

import argparse
import bisect
import csv
import math
import os
import re
import shutil
import subprocess
import tempfile
import sys
from functools import lru_cache

PALLETS_MM = {  # (width, length) as onpallet uses them
    "euro": (1200, 800),
    "industrial": (1200, 1000),
    "us": (1219, 1016),
    "half": (800, 600),
    "australian": (1165, 1165),
}
# Pallet heights onpallet adds for "loading height with pallet" (read off its results page).
PALLET_HEIGHT_MM = {"euro": 145, "industrial": 145, "us": 142, "half": 158, "australian": 151, "custom": 145}


UNIT_ALIASES = {"mm": "mm", "": "mm", "in": "in", "inch": "in", "inches": "in", '"': "in"}

# Input limits enforced by onpallet's form (in mm / kg). The site silently clamps values
# outside these ranges; we report an error instead so bad data gets noticed.
LIMITS_MM = {"width": (70, 1300), "length": (70, 1300), "height": (70, 2400),
             "load_height": (300, 2600), "pallet side": (200, 1300)}


def norm_unit(unit):
    u = str(unit if unit is not None else "mm").strip().lower()
    if u not in UNIT_ALIASES:
        raise ValueError(f"unknown unit '{unit}' (use mm or in)")
    return UNIT_ALIASES[u]


def half_up(x, digits=0):
    """Round like JavaScript Math.round (half away from zero for positives)."""
    f = 10 ** digits
    return math.floor(x * f + 0.5) / f


def to_mm(v, unit, name="value"):
    """Convert one input to mm exactly the way onpallet does (may return a fraction for inches).

    The page rounds mm input to whole mm and inch input to 0.1 in when you leave the field.
    The server then multiplies inches by 25.4; box width/length are later rounded down to
    whole mm for the layout, while box height, load height and pallet size stay exact.
    """
    try:
        x = float(str(v).strip().replace(",", "."))
    except ValueError:
        raise ValueError(f"{name} '{v}' is not a number")
    if not x > 0:
        raise ValueError(f"{name} must be greater than 0 (got {v})")
    if unit == "in":
        return round(half_up(x, 1) * 25.4, 6)
    return float(half_up(x))


def floor_mm(x):
    return int(math.floor(x + 1e-9))


def tidy(x, digits=1):
    """Round for output; show whole numbers without a trailing .0."""
    r = round(x, digits)
    return int(r) if r == int(r) else r


def check_limit(name, mm):
    lo, hi = LIMITS_MM[name]
    if not lo <= mm <= hi:
        raise ValueError(f"{name} {tidy(mm)} mm is outside onpallet's allowed range {lo}-{hi} mm "
                         "(the site would silently change it)")


# ---------------------------------------------------------------- layer solver

class LayerSolver:
    """Max number of a x b rectangles (90 degree rotation allowed) in an L x W rectangle."""

    def __init__(self, a, b, L, W):
        self.a, self.b, self.L, self.W = a, b, L, W
        top = max(L, W)
        pts = set()
        for i in range(top // a + 1):
            for j in range((top - i * a) // b + 1):
                pts.add(i * a + j * b)
        self.R = sorted(pts)  # raster points: all reachable sums of box sides
        self._best = lru_cache(maxsize=None)(self._best_impl)
        self.recursive_five = False
        self.five_limit = 400  # skip nested pinwheel search in sub-rectangles holding more boxes than this

    def norm(self, v):
        if v < 0:
            return 0
        return self.R[bisect.bisect_right(self.R, v) - 1]

    def ub(self, x, y):
        return (self.norm(x) * self.norm(y)) // (self.a * self.b)

    # A plan is a tuple: ("grid", rot, nx, ny) | ("cut", axis, pos, plan1, plan2) | ("t", plan)
    # value of best(x, y) == (count, plan) for an x by y rectangle.
    def best(self, x, y):
        x, y = self.norm(x), self.norm(y)
        if x >= y:
            return self._best(x, y)
        n, plan = self._best(y, x)
        return n, ("t", plan)  # transposed

    def _best_impl(self, x, y):
        a, b = self.a, self.b
        g0 = ((x // a) * (y // b), ("grid", 0, x // a, y // b))
        g1 = ((x // b) * (y // a), ("grid", 1, x // b, y // a))
        best = max(g1, g0, key=lambda t: t[0])  # ties: onpallet prefers box length along pallet width
        bound = (x * y) // (a * b)
        if best[0] == bound or best[0] == 0 and min(a, b) > min(x, y):
            return best
        for axis, span, other in ((0, x, y), (1, y, x)):
            for r in self.R:
                if r == 0:
                    continue
                if r > span // 2:
                    break
                if axis == 0:
                    n1, p1 = self.best(r, y)
                    n2, p2 = self.best(x - r, y)
                else:
                    n1, p1 = self.best(x, r)
                    n2, p2 = self.best(x, y - r)
                if n1 + n2 > best[0]:
                    best = (n1 + n2, ("cut", axis, r, p1, p2))
                    if best[0] == bound:
                        return best
        # Recursive non-guillotine step (Morabito-Morales style): pinwheel split whose
        # blocks are themselves solved by this same recursion.
        if self.recursive_five and best[0] < bound and bound <= self.five_limit:
            best = self.five_block(x, y, best)
        return best

    def five_block(self, x, y, incumbent):
        """First-order non-guillotine (pinwheel) patterns; block cuts at multiples of a or b."""
        a, b = self.a, self.b
        cuts_x = sorted({i * s for s in (a, b) for i in range(1, x // s + 1)})
        cuts_y = sorted({i * s for s in (a, b) for i in range(1, y // s + 1)})
        best = incumbent
        bound = self.ub(x, y)
        for x1 in cuts_x:
            for x2c in cuts_x:           # x2 = x - x2c  (right block width = x2c)
                x2 = x - x2c
                if x2 <= x1:
                    continue
                for y1 in cuts_y:
                    n2, p2 = self.best(x - x1, y1)                      # bottom-right
                    for y2c in cuts_y:
                        y2 = y - y2c
                        if y2 <= y1:
                            continue
                        n1, p1 = self.best(x1, y2)                      # left-bottom
                        n3, p3 = self.best(x2c, y - y1)                 # right-top
                        n4, p4 = self.best(x2, y2c)                     # top-left
                        if n1 + n2 + n3 + n4 + self.ub(x2 - x1, y2 - y1) <= best[0]:
                            continue
                        n5, p5 = self.best(x2 - x1, y2 - y1)            # centre
                        tot = n1 + n2 + n3 + n4 + n5
                        if tot > best[0]:
                            best = (tot, ("five", (x1, x2, y1, y2), p1, p2, p3, p4, p5))
                            if tot >= bound:
                                return best
        return best

    def solve(self):
        n, plan = self.best(self.L, self.W)
        if n < self.ub(self.L, self.W):
            if self.L >= self.W:
                n, plan = self.five_block(self.L, self.W, (n, plan))
            else:
                n2, p2 = self.five_block(self.W, self.L, (n, plan))
                if n2 > n:
                    n, plan = n2, ("t", p2)
        return n, plan

    # ------------------------------------------------------- layout extraction
    def boxes(self, plan, x0=0, y0=0, w=None, h=None):
        """Return box rectangles (a,b,c,d) = (x1,y1,x2,y2) in mm."""
        w = self.L if w is None else w
        h = self.W if h is None else h
        out = []
        self._emit(plan, x0, y0, w, h, False, out)
        return out

    def _emit(self, plan, x0, y0, w, h, tr, out):
        # tr: plan was computed for (h, w) and must be transposed into (w, h) space
        kind = plan[0]
        if kind == "t":
            self._emit(plan[1], x0, y0, w, h, not tr, out)
            return
        # local frame: X along plan's first dim, Y along second
        def put(lx, ly, lw, lh):
            if tr:
                out.append({"a": x0 + ly, "b": y0 + lx, "c": x0 + ly + lh, "d": y0 + lx + lw})
            else:
                out.append({"a": x0 + lx, "b": y0 + ly, "c": x0 + lx + lw, "d": y0 + ly + lh})

        def sub(p, lx, ly, lw, lh):
            if tr:
                self._emit(p, x0 + ly, y0 + lx, lh, lw, True, out)
            else:
                self._emit(p, x0 + lx, y0 + ly, lw, lh, False, out)

        PW, PH = (h, w) if tr else (w, h)
        if kind == "grid":
            _, rot, nx, ny = plan
            bw, bh = (self.a, self.b) if rot == 0 else (self.b, self.a)
            for i in range(nx):
                for j in range(ny):
                    put(i * bw, j * bh, bw, bh)
        elif kind == "cut":
            _, axis, r, p1, p2 = plan
            if axis == 0:
                sub(p1, 0, 0, r, PH)
                sub(p2, r, 0, PW - r, PH)
            else:
                sub(p1, 0, 0, PW, r)
                sub(p2, 0, r, PW, PH - r)
        elif kind == "five":
            _, (x1, x2, y1, y2), p1, p2, p3, p4, p5 = plan
            sub(p1, 0, 0, x1, y2)
            sub(p2, x1, 0, PW - x1, y1)
            sub(p3, x2, y1, PW - x2, PH - y1)
            sub(p4, 0, y2, x2, PH - y2)
            sub(p5, x1, y1, x2 - x1, y2 - y1)


def _find_solver():
    """Solver location: $PALLETCALC_SOLVER, the bundled build, or RecPartAlgorithm on PATH."""
    env = os.environ.get("PALLETCALC_SOLVER")
    if env:
        return env
    bundled = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "third_party", "RecursivePartitioningAlgorithm", "RecPartAlgorithm")
    if os.path.exists(bundled):
        return bundled
    return shutil.which("RecPartAlgorithm") or bundled


RECPART_BIN = _find_solver()


def recpart_layer(box_w, box_l, pal_w, pal_l, phase1_only=False, timeout=120):
    """Run the Birgin-Lobato-Morabito Recursive Partitioning Algorithm (GPLv3, compiled C++).

    phase1_only=True runs only the five-block algorithm, which is what onpallet.com uses:
    with the box sides passed in the order typed (width, length) it reproduced the site's
    layouts box-for-box on 144/144 test cases.
    Returns {"count", "upper_bound", "boxes"} in pallet coordinates, or None if unavailable.
    """
    if not os.path.exists(RECPART_BIN):
        return None
    L, W = max(pal_w, pal_l), min(pal_w, pal_l)
    env = dict(os.environ)
    if phase1_only:
        env["RECPART_PHASE1_ONLY"] = "1"
    with tempfile.TemporaryDirectory() as d:  # program writes solution.* into its cwd
        try:
            out = subprocess.run([RECPART_BIN], input=f"{L} {W}\n{box_w} {box_l}\n", cwd=d, env=env,
                                 capture_output=True, text=True, timeout=timeout).stdout
            with open(os.path.join(d, "solution.txt")) as fh:
                lines = fh.read().split("\n")
        except (subprocess.TimeoutExpired, OSError):
            return None
    m = re.search(r"Solution found:\s*(\d+)", out)
    u = re.search(r"upper bound:\s*(\d+)", out)
    if not m:
        return None
    rects = [tuple(map(int, ln.split())) for ln in lines[2:] if ln.strip()]
    flip = pal_w < pal_l  # solver's x axis is the long pallet side
    boxes = [{"a": y1, "b": x1, "c": y2, "d": x2} if flip else {"a": x1, "b": y1, "c": x2, "d": y2}
             for x1, y1, x2, y2 in rects]
    n = int(m.group(1))
    return {"count": n, "upper_bound": int(u.group(1)) if u else None, "boxes": boxes if n else []}


def python_layer(box_w, box_l, pal_w, pal_l):
    """Pure-Python fallback (guillotine + pinwheel); used when the C++ solver isn't compiled."""
    s = LayerSolver(box_w, box_l, pal_w, pal_l)
    n, plan = s.solve()
    return {"count": n, "upper_bound": s.ub(pal_w, pal_l), "boxes": s.boxes(plan) if n else [],
            "solver": "python"}


class SolverUnavailable(RuntimeError):
    pass


def calc_layer(box_w, box_l, pal_w, pal_l, mode="onpallet", allow_fallback=False):
    """mode="onpallet": replicate onpallet.com exactly.  mode="best": most boxes we can find.

    Always also returns best_count (the best layer we can find) so the two can be compared.
    """
    if min(box_w, box_l) > min(pal_w, pal_l) or max(box_w, box_l) > max(pal_w, pal_l):
        return {"count": 0, "upper_bound": 0, "boxes": [], "best_count": 0, "solver": "none"}
    site = recpart_layer(box_w, box_l, pal_w, pal_l, phase1_only=True)
    if site is None:
        if not allow_fallback:
            why = ("not built: run `make` in third_party/RecursivePartitioningAlgorithm"
                   if not os.path.exists(RECPART_BIN) else "failed or timed out")
            raise SolverUnavailable(f"onpallet-exact solver {why} "
                                    "(or pass --allow-fallback for the ~97%-accurate Python solver)")
        res = python_layer(box_w, box_l, pal_w, pal_l)  # matches site counts on ~97% of cases
        res["best_count"] = res["count"]
        return res
    site["solver"] = "recpart-phase1"
    best = site
    if site["upper_bound"] is None or site["count"] < site["upper_bound"]:
        full = recpart_layer(box_w, box_l, pal_w, pal_l)
        if full and full["count"] > site["count"]:
            best = dict(full, solver="recpart-full")
    res = dict(best if mode == "best" else site)
    res["best_count"] = best["count"]
    return res


def calculate(width, length, height, weight, pallet, load_height, unit="mm", mode="onpallet",
              allow_fallback=False):
    unit = norm_unit(unit)
    w, l, h, lh = (to_mm(v, unit, n) for v, n in ((width, "width"), (length, "length"),
                                                  (height, "height"), (load_height, "load_height")))
    for n, v in (("width", w), ("length", l), ("height", h), ("load_height", lh)):
        check_limit(n, v)
    w, l = floor_mm(w), floor_mm(l)  # layout uses whole mm; h and lh stay exact
    p = str(pallet).strip().lower()
    if p.startswith("custom:"):
        cw, cl = p.split(":", 1)[1].replace("×", "x").replace("*", "x").split("x")
        pw, pl = to_mm(cw, unit, "pallet width"), to_mm(cl, unit, "pallet length")
        check_limit("pallet side", pw)
        check_limit("pallet side", pl)
        pw, pl = max(pw, pl), min(pw, pl)  # onpallet always puts the long side first
    elif p in PALLETS_MM:
        pw, pl = PALLETS_MM[p]
    else:
        raise ValueError(f"unknown pallet '{pallet}'")
    layer = calc_layer(w, l, floor_mm(pw), floor_mm(pl), mode, allow_fallback)
    layers = floor_mm(lh / h) if h else 0
    if unit == "in" and mode == "onpallet":
        # R8a: onpallet divides the two inch values converted to mm in plain floating point,
        # with no tolerance, so exact multiples can lose a layer (48 in / 8 in -> 5 layers).
        # Reproduced here; --mode best keeps the exact count.
        h_in, lh_in = (half_up(float(str(v).strip().replace(",", ".")), 1) for v in (height, load_height))
        layers = math.floor((lh_in * 25.4) / (h_in * 25.4))
    stack_h = layers * h
    pal_h = PALLET_HEIGHT_MM["custom" if p.startswith("custom:") else p]
    total = layer["count"] * layers
    try:
        wt = float(str(weight).strip().replace(",", "."))
    except ValueError:
        raise ValueError(f"weight '{weight}' is not a number")
    if wt < 0:
        raise ValueError("weight must not be negative")
    used = sum((bx["c"] - bx["a"]) * (bx["d"] - bx["b"]) for bx in layer["boxes"])
    surface = used / (pw * pl)
    inch = unit == "in"
    return {
        "boxes_per_layer": layer["count"],
        "layers": layers,
        "total_boxes": total,
        "total_weight": tidy(total * wt, 2),
        "pallet_w_mm": tidy(pw),
        "pallet_l_mm": tidy(pl),
        "layer_area_used_pct": tidy(100 * surface),
        "volume_used_pct": tidy(100 * surface * stack_h / lh) if lh else 0,
        "stack_height_mm": tidy(stack_h),
        "height_with_pallet_mm": tidy(stack_h + pal_h),
        "stack_height_in": tidy(stack_h / 25.4) if inch else "",
        "height_with_pallet_in": tidy((stack_h + pal_h) / 25.4) if inch else "",
        "best_possible_per_layer": layer["best_count"],
        "provably_optimal": layer["count"] == layer["upper_bound"],
        "solver": layer["solver"],
        "layout": layer["boxes"],
    }


OUT_FIELDS = ["id", "width", "length", "height", "weight", "pallet", "load_height", "unit",
              "boxes_per_layer", "layers", "total_boxes", "total_weight", "pallet_w_mm",
              "pallet_l_mm", "layer_area_used_pct", "volume_used_pct", "stack_height_mm",
              "height_with_pallet_mm", "stack_height_in", "height_with_pallet_in", "best_possible_per_layer", "provably_optimal", "solver",
              "status", "error"]


def main():
    ap = argparse.ArgumentParser(prog="palletcalc", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?", help="input CSV file")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument("-o", "--output", default="results.csv")
    ap.add_argument("--one", nargs=6, metavar=("W", "L", "H", "KG", "PALLET", "LOADH"))
    ap.add_argument("--unit", default="mm", help="unit for --one (mm or in)")
    ap.add_argument("--allow-fallback", action="store_true",
                    help="use the pure-Python solver if the C++ solver is unavailable (not site-exact)")
    ap.add_argument("--force", action="store_true", help="overwrite the output file if it exists")
    ap.add_argument("--mode", choices=["onpallet", "best"], default="onpallet",
                    help="onpallet: replicate onpallet.com exactly (default); best: most boxes found")
    a = ap.parse_args()
    if a.one:
        try:
            r = calculate(*a.one, unit=a.unit, mode=a.mode, allow_fallback=a.allow_fallback)
        except (ValueError, SolverUnavailable) as e:
            sys.exit(f"error: {e}")
        lay = r.pop("layout")
        for k, v in r.items():
            print(f"{k:22} {v}")
        print(f"{'layout (x1,y1,x2,y2)':22} " + " ".join(f"({b['a']},{b['b']},{b['c']},{b['d']})" for b in lay))
        return
    if not a.input:
        ap.error("input CSV or --one required")
    with open(a.input, newline="", encoding="utf-8-sig") as f:
        rows = [{k.strip().lower(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]
    if os.path.exists(a.output) and not a.force:
        sys.exit(f"error: {a.output} already exists (use -o another.csv or --force)")
    if not os.path.exists(RECPART_BIN) and not a.allow_fallback:
        sys.exit("error: solver not found. Build it with `make -C third_party/RecursivePartitioningAlgorithm`, "
                 "set PALLETCALC_SOLVER, or pass --allow-fallback.")
    warned = 0
    with open(a.output, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=OUT_FIELDS, extrasaction="ignore")
        wr.writeheader()
        for row in rows:
            try:
                res = calculate(row["width"], row["length"], row["height"], row["weight"],
                                row["pallet"], row["load_height"], row.get("unit") or "mm", a.mode,
                                a.allow_fallback)
                if res["boxes_per_layer"] == 0:
                    res.update(status="does_not_fit", error="box does not fit on the pallet")
                elif res["layers"] == 0:
                    res.update(status="does_not_fit", error="box is taller than the loading height")
                else:
                    res.update(status="ok", error="")
                if res["solver"] not in ("recpart-phase1", "recpart-full", "none"):
                    warned += 1
                    print(f"warning: row {row.get('id', '')}: used fallback solver ({res['solver']}), "
                          "may differ from onpallet", file=sys.stderr)
            except Exception as e:
                res = {"status": "error", "error": str(e)}
            wr.writerow({**row, **res})
    print(f"wrote {a.output} ({len(rows)} rows)", file=sys.stderr)


if __name__ == "__main__":
    main()
