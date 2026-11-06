#!/usr/bin/env python3
"""Check palletcalc's summary figures against onpallet.com results pages.

  python3 validation/summary_check.py          # offline, against data/summary_pages.json
  python3 validation/summary_check.py fetch    # record missing cases from the site

Only the site's "Detail results" table is stored, with the inputs as typed and as the
browser sends them. Checked: n packages, n layers, both loading heights, surface and
volume usage, total weight, and the "Package size" / "Pallet size" text.

Weight: the page rounds weight to 0.1 and clamps it (1300 in mm/kg mode, 51.2 in inch
mode, a site bug, see SPEC R10). The calculator does not round or clamp weight, so when
the sent weight differs from the typed one, "Total weight" may differ. That is reported as
EXPECTED only if the site's figure equals n packages x the weight actually sent.
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

    # weight edge cases
    "S13": ("300", "400", "250", "5000", "euro", "1500", "mm"),          # weight clamped to 1300
    "S14": ("12", "16", "10", "60", "us", "60", "in"),                   # weight clamped to 51.2 (site bug)
    "S15": ("95", "114", "120", "1300", "euro", "1000", "mm"),           # max weight, big total (thousands format)
    "S16": ("250", "350", "200", "3.14", "half", "1200", "mm"),          # 2-decimal weight, page sends 3.1
    "S17": ("2.8", "2.8", "2.8", "0.7", "half", "100", "in"),            # tiny inch boxes, huge count, decimal weight
    # every standard pallet in inch mode (euro and us are S09 / S08)
    "S18": ("11", "14", "9", "18.5", "industrial", "55", "in"),
    "S19": ("8", "10", "6.5", "4.2", "half", "48", "in"),
    "S20": ("10.5", "15.2", "8", "9.9", "australian", "70", "in"),
    "S21": ("20", "24", "40", "35", "us", "40", "in"),                   # box height == load height
    # custom pallets
    "S22": ("7.8", "11.8", "5.9", "2.2", "custom:47.5x42.5", "51.3", "in"),  # inch, long side typed first
    "S23": ("333", "222", "150", "12", "custom:1300x1000", "2400", "mm"),    # mm, long first, box w > l
    "S24": ("210.5", "297.5", "148.5", "1.5", "custom:799.4x1012.6", "1350", "mm"),  # decimal mm everywhere
    # box counts and layer edge cases
    "S25": ("600", "800", "2400", "1250.5", "euro", "2600", "mm"),       # very small count: 2 boxes
    "S26": ("70", "70", "70", "0.1", "industrial", "2600", "mm"),        # very large count, minimum sizes
    "S27": ("200", "300", "200", "8", "australian", "2000", "mm"),       # load height exact multiple
    "S28": ("400", "500", "1000", "25", "industrial", "1000", "mm"),     # box height == load height
    "S29": ("500", "300", "400", "15", "us", "1250", "mm"),              # box typed w > l on US pallet
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


WEIGHT_MAX = {"mm": 1300.0, "in": 51.2}  # page clamp (in inch mode: 1300 / 25.4, a site bug)


def browser_inputs(args):
    """What the browser sends: summary_check's rounding, then the page's weight clamp."""
    w, l, h, kg, pal, lh, unit = browser_rounded(args)
    kg = f"{min(float(kg), WEIGHT_MAX[unit]):g}"
    return w, l, h, kg, pal, lh, unit


def fmt(x):
    """1 decimal, trailing .0 dropped (as the site displays numbers)."""
    return f"{half_up(x, 1):g}"


def package_text(sent):
    """Observed: typed order, values as the browser sent them, ' mm' or ' in'."""
    w, l, h, _, _, _, unit = sent
    return f"{fmt(float(w))} x {fmt(float(l))} x {fmt(float(h))} {unit}"


def pallet_text(sent, r):
    """Observed: standard pallets short side first; custom pallets in the typed order
    (as sent, not the solver's long-first order). mm as whole mm glued to 'mm' (no space);
    inches to 0.1, trailing .0 dropped, ' in' with a space."""
    unit, pal = sent[-1], sent[4]
    if pal.startswith("custom:"):
        a, b = (float(v) for v in pal.split(":")[1].split("x"))
    else:
        a, b = sorted((r["pallet_w_mm"], r["pallet_l_mm"]))
        if unit == "in":
            a, b = a / 25.4, b / 25.4
    return f"{fmt(a)} x {fmt(b)} in" if unit == "in" else f"{fmt(a)} x {fmt(b)}mm"


def load():
    return json.load(open(DATA)) if os.path.exists(DATA) else {}


def fetch(delay=2.0, limit=20):
    from onpallet_client import Session, SiteError
    data, done = load(), 0
    for cid, args in CASES.items():
        if cid in data:
            continue
        if done >= limit:
            print("limit reached")
            break
        sent = browser_inputs(args)
        done += 1
        try:
            s = Session()
            s.submit(*sent)
            s.layout()
            site = s.summary()
        except SiteError as e:
            site = {"error": str(e)}
        data[cid] = {"input": dict(zip(FIELDS, args)), "sent": dict(zip(FIELDS, sent)), "site": site}
        json.dump(data, open(DATA, "w"), indent=1, ensure_ascii=True)
        print(cid, "recorded", site)
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
        rec = data[cid]
        site, sent = rec["site"], browser_inputs(args)
        if "error" in site:
            fails += 1
            print(cid, "MISMATCH site error:", site["error"])
            continue
        r = calculate(*args)
        unit = args[-1]
        f = 1 / 25.4 if unit == "in" else 1
        ours = {
            "n packages:": r["total_boxes"],
            "n layers:": r["layers"],
            "Loading height:": round(r["stack_height_mm"] * f, 1),
            "Loading height with pallet:": round(r["height_with_pallet_mm"] * f, 1),
            "Surface usage:": r["layer_area_used_pct"],
            "Volume usage:": r["volume_used_pct"],
        }
        bad = [f"{k} site={site.get(k)!r} ours={v}" for k, v in ours.items()
               if num(site.get(k, "")) is None or abs(num(site[k]) - v) > 0.051]
        for k, v in (("Package size:", package_text(sent)), ("Pallet size:", pallet_text(sent, r))):
            if site.get(k) != v:
                bad.append(f"{k} site={site.get(k)!r} ours={v!r}")
        note = ""
        sw = num(site.get("Total weight:", ""))
        if sw is None or abs(sw - r["total_weight"]) > 0.051:
            expected = r["total_boxes"] * float(sent[3])
            if sw is not None and float(sent[3]) != float(args[3]) and abs(sw - expected) <= 0.051:
                note = (f"  EXPECTED weight diff: site={site['Total weight:']!r} = {r['total_boxes']} x "
                        f"{sent[3]} (sent), ours={r['total_weight']} = x {args[3]} (typed)")
            else:
                bad.append(f"Total weight: site={site.get('Total weight:')!r} ours={r['total_weight']}")
        fails += bool(bad)
        print(cid, ("OK" if not bad else "MISMATCH " + "; ".join(bad)) + note)
    print(f"mismatching cases: {fails}")
    return fails


if __name__ == "__main__":
    if sys.argv[1:] == ["fetch"]:
        fetch()
    else:
        sys.exit(1 if compare() else 0)
