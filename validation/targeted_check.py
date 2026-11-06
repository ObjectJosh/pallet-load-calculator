#!/usr/bin/env python3
"""Offline check of palletcalc against the targeted onpallet.com sample.

  python3 validation/targeted_check.py [validation/data/targeted_raw.jsonl] [-v]

Per case: pallet size, layer count and layout (sorted box tuples must be identical).
Site status -6 (box does not fit) counts as OK when palletcalc also places 0 boxes.
Other site errors (-7: the site gave up) are not comparable and are listed separately.
Cases recorded with the results page ("summary") also compare its figures; the layer
count then comes from the page, otherwise from floor(loadh / height) of the layout data.
Exit code 1 if any case mismatches.
"""
import json
import math
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from palletcalc import calculate  # noqa: E402
from compare import key  # noqa: E402
from summary_check import num  # noqa: E402

RAW = os.path.join(HERE, "data", "targeted_raw.jsonl")


def summary_diffs(site, r, unit):
    f = 1 / 25.4 if unit == "in" else 1
    ours = {
        "n packages:": r["total_boxes"],
        "n layers:": r["layers"],
        "Loading height:": round(r["stack_height_mm"] * f, 1),
        "Loading height with pallet:": round(r["height_with_pallet_mm"] * f, 1),
        "Surface usage:": r["layer_area_used_pct"],
        "Volume usage:": r["volume_used_pct"],
        "Total weight:": r["total_weight"],
    }
    return [f"{k} site={site.get(k)!r} ours={v}" for k, v in ours.items()
            if num(site.get(k, "")) is None or abs(num(site[k]) - v) > 0.051]


def check(rec):
    """Returns (status, message). status in OK, MISMATCH, SITE_ERROR."""
    c = rec["case"]
    args = (c["width"], c["length"], c["height"], c["weight"], c["pallet"], c["load_height"], c["unit"])
    r = calculate(*args)
    if "pal" not in rec:
        err = rec.get("error", "")
        if "status -6" in err:
            return ("OK", "both: box does not fit") if r["boxes_per_layer"] == 0 else \
                ("MISMATCH", f"site -6 (does not fit), ours {r['boxes_per_layer']} per layer")
        return "SITE_ERROR", f"{err} (ours {r['boxes_per_layer']} per layer)"
    p = rec["pal"]
    bad = []
    expected = ""
    if abs(p["palW"] - r["pallet_w_mm"]) > 0.051 or abs(p["palL"] - r["pallet_l_mm"]) > 0.051:
        # R6a (SPEC): for custom pallets in inch mode the site labels palW/palL as
        # (second typed side, first typed side) without sorting. The layout is unaffected,
        # and the calculator keeps long-side-first labels so its output stays consistent.
        swapped = (abs(p["palW"] - r["pallet_l_mm"]) <= 0.051 and abs(p["palL"] - r["pallet_w_mm"]) <= 0.051)
        if c["unit"] == "in" and str(c["pallet"]).startswith("custom:") and swapped:
            expected = " (EXPECTED: site's inch custom pallet labels swapped, R6a)"
        else:
            bad.append(f"pallet site={p['palW']}x{p['palL']} ours={r['pallet_w_mm']}x{r['pallet_l_mm']}")
    raw_layers = math.floor(p["loadh"] / p["height"]) if p["height"] else 0
    summ = rec.get("summary")
    site_layers = int(num(summ["n layers:"])) if summ and num(summ.get("n layers:", "")) is not None \
        else raw_layers
    if site_layers != r["layers"]:
        bad.append(f"layers site={site_layers} ours={r['layers']}")
    sn, mn = len(p["boxes"]), r["boxes_per_layer"]
    if sn != mn:
        bad.append(f"count site={sn} ours={mn} (best={r['best_possible_per_layer']})")
    elif key(p["boxes"]) != key(r["layout"]):
        bad.append(f"layout differs ({sn} boxes)")
    if summ:
        bad += summary_diffs(summ, r, c["unit"])
    note = f"{sn} boxes x {site_layers} layers"
    if summ and raw_layers != site_layers:
        note += f" (floor(loadh/height) of layout data = {raw_layers})"
    if r["best_possible_per_layer"] > mn:
        note += f", best possible {r['best_possible_per_layer']}"
    return ("MISMATCH", "; ".join(bad)) if bad else ("OK", note + expected)


def main():
    files = [a for a in sys.argv[1:] if not a.startswith("-")] or [RAW]
    verbose = "-v" in sys.argv
    per_cat = defaultdict(Counter)
    bad = 0
    for fn in files:
        for line in open(fn):
            if not line.strip():
                continue
            rec = json.loads(line)
            c = rec["case"]
            st, msg = check(rec)
            cat = c.get("category", "?")
            per_cat[cat]["n"] += 1
            per_cat[cat][st] += 1
            bad += st == "MISMATCH"
            if verbose or st != "OK":
                print(f"{st:10} {c['id']} {c['width']}x{c['length']}x{c['height']} {c['unit']} "
                      f"{c['pallet']} lh={c['load_height']}: {msg}")
    print(f"\n{'category':16} {'n':>4} {'OK':>4} {'MISMATCH':>9} {'SITE_ERROR':>11}")
    tot = Counter()
    for cat, s in sorted(per_cat.items()):
        tot.update(s)
        print(f"{cat:16} {s['n']:4} {s['OK']:4} {s['MISMATCH']:9} {s['SITE_ERROR']:11}")
    print(f"{'total':16} {tot['n']:4} {tot['OK']:4} {tot['MISMATCH']:9} {tot['SITE_ERROR']:11}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
