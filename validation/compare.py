#!/usr/bin/env python3
"""Compare palletcalc.py against stored onpallet.com results.

  python3 validation/compare.py validation/data/learn_raw.jsonl [more.jsonl ...] [-v]
"""
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from palletcalc import calc_layer  # noqa: E402
from check_layout import valid  # noqa: E402


def key(boxes):
    return sorted((b["a"], b["b"], b["c"], b["d"]) for b in boxes)


def symmetries(boxes, W, L):
    """All 4 mirror images of a layout on a W x L pallet."""
    out = []
    for fx in (False, True):
        for fy in (False, True):
            t = []
            for b in boxes:
                a, c = (W - b["c"], W - b["a"]) if fx else (b["a"], b["c"])
                bb, d = (L - b["d"], L - b["b"]) if fy else (b["b"], b["d"])
                t.append({"a": a, "b": bb, "c": c, "d": d})
            out.append(key(t))
    return out


def main():
    files = [f for f in sys.argv[1:] if not f.startswith("-")]
    verbose = "-v" in sys.argv
    stats = Counter()
    rows = []
    for fn in files:
        for line in open(fn):
            rec = json.loads(line)
            c = rec["case"]
            if "pal" not in rec:
                stats["site_error"] += 1
                rows.append((c["id"], "SITE ERROR", rec.get("error")))
                continue
            p = rec["pal"]
            W, L = p["palW"], p["palL"]
            a, b = c["w"], c["l"]
            site = p["boxes"]
            ok, msg = valid(site, W, L, a, b)
            if not ok:
                stats["site_layout_odd"] += 1
            mine = calc_layer(a, b, W, L, mode=os.environ.get("MODE", "onpallet"))
            sn, mn = len(site), mine["count"]
            stats["n"] += 1
            if sn == mn:
                stats["count_equal"] += 1
                if key(site) == key(mine["boxes"]):
                    stats["layout_identical"] += 1
                elif key(mine["boxes"]) in symmetries(site, W, L):
                    stats["layout_mirror"] += 1
                else:
                    stats["layout_different"] += 1
            elif mn > sn:
                stats["we_beat_site"] += 1
                rows.append((c["id"], f"OURS {mn} > SITE {sn}", f"{a}x{b} on {W}x{L} ub={mine['upper_bound']}"))
            else:
                stats["site_beats_us"] += 1
                rows.append((c["id"], f"SITE {sn} > OURS {mn}", f"{a}x{b} on {W}x{L} ub={mine['upper_bound']}"))
            if verbose and not ok:
                rows.append((c["id"], "site layout check", msg))
    for k in ("n", "count_equal", "layout_identical", "layout_mirror", "layout_different",
              "we_beat_site", "site_beats_us", "site_error", "site_layout_odd"):
        print(f"{k:18} {stats[k]}")
    for r in rows:
        print(*r)


if __name__ == "__main__":
    main()
