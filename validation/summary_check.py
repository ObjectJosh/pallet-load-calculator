#!/usr/bin/env python3
"""Check palletcalc's summary figures against onpallet.com results pages.

  python3 validation/summary_check.py          # offline, against data/summary_pages.json
  python3 validation/summary_check.py fetch    # record missing cases from the site

Only the figures from the site's "Detail results" table are stored.
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from palletcalc import calculate, half_up  # noqa: E402

DATA = os.path.join(HERE, "data", "summary_pages.json")

# id: (width, length, height, weight, pallet, load_height, unit)
CASES = {
    "S01": ("230", "370", "180", "4.5", "euro", "1600", "mm"),
    "S02": ("300", "400", "250", "10", "industrial", "1500", "mm"),
    "S03": ("305", "406", "254", "12.3", "us", "1524", "mm"),
    "S04": ("180", "250", "333", "2.75", "half", "1800", "mm"),
    "S05": ("275", "390", "210", "7", "australian", "2000", "mm"),
    "S06": ("250", "300", "220", "3", "custom:700x1100", "1450", "mm"),   # custom, short side first
    "S07": ("95", "114", "120", "0.8", "euro", "1000", "mm"),             # hard instance
    "S08": ("12", "16", "10", "22", "us", "60", "in"),
    "S09": ("12", "16", "10", "22", "euro", "61", "in"),
    "S10": ("9.25", "13.6", "7.35", "5.5", "custom:30x44", "50", "in"),  # decimal inches
    "S11": ("300.4", "399.6", "250", "10", "euro", "1500.5", "mm"),       # decimal mm
    "S12": ("700", "500", "1200", "40", "euro", "1100", "mm"),            # box taller than load height
}
FIELDS = ("width", "length", "height", "weight", "pallet", "load_height", "unit")


def browser_rounded(args):
    """Round inputs the way the page does when a field loses focus (onpallet.js)."""
    w, l, h, kg, pal, lh, unit = args
    r = (lambda v: f"{half_up(float(v), 1):g}") if unit == "in" else (lambda v: f"{half_up(float(v)):g}")
    if pal.startswith("custom:"):
        cw, cl = pal.split(":")[1].split("x")
        pal = f"custom:{r(cw)}x{r(cl)}"
    return r(w), r(l), r(h), f"{half_up(float(kg), 1):g}", pal, r(lh), unit


def load():
    return json.load(open(DATA)) if os.path.exists(DATA) else {}


def fetch(delay=1.5):
    from onpallet_client import Session
    data = load()
    for cid, args in CASES.items():
        if cid in data:
            continue
        s = Session()
        s.submit(*browser_rounded(args))
        s.layout()
        data[cid] = {"input": dict(zip(FIELDS, args)), "site": s.summary()}
        json.dump(data, open(DATA, "w"), indent=1, ensure_ascii=True)
        print(cid, "recorded")
        time.sleep(delay)


def num(text):
    m = re.search(r"-?[\d.]+", text.replace(",", ""))
    return float(m.group()) if m else None


def compare():
    data, fails = load(), 0
    for cid, args in CASES.items():
        if cid not in data:
            print(cid, "not recorded")
            continue
        site = data[cid]["site"]
        r = calculate(*args)
        f = 1 / 25.4 if args[-1] == "in" else 1
        ours = {
            "n packages:": r["total_boxes"],
            "n layers:": r["layers"],
            "Loading height:": round(r["stack_height_mm"] * f, 1),
            "Loading height with pallet:": round(r["height_with_pallet_mm"] * f, 1),
            "Surface usage:": r["layer_area_used_pct"],
            "Volume usage:": r["volume_used_pct"],
            "Total weight:": r["total_weight"],
        }
        bad = [f"{k} site={site.get(k)!r} ours={v}" for k, v in ours.items()
               if num(site.get(k, "")) is None or abs(num(site[k]) - v) > 0.051]
        fails += bool(bad)
        print(cid, "OK" if not bad else "MISMATCH " + "; ".join(bad))
    print(f"mismatching cases: {fails}")
    return fails


if __name__ == "__main__":
    if sys.argv[1:] == ["fetch"]:
        fetch()
    else:
        sys.exit(1 if compare() else 0)
