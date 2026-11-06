#!/usr/bin/env python3
"""From typed inputs, check palletcalc against stored site results: pallet size, layers, layout.

  python3 validation/end_to_end.py validation/data/learn_raw.jsonl validation/data/holdout_raw.jsonl
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from palletcalc import calculate  # noqa: E402
from compare import key  # noqa: E402

total_bad = 0
for fn in sys.argv[1:]:
    n = ok = 0
    for line in open(fn):
        r = json.loads(line)
        if "pal" not in r:
            continue
        c, p = r["case"], r["pal"]
        n += 1
        pal = c["pallet"] if c["pallet"] != "custom" else f"custom:{c['cw']}x{c['cl']}"
        res = calculate(c["w"], c["l"], c["h"], 1, pal, c["load_h"])
        if (res["layers"] == p["loadh"] // p["height"]
                and (res["pallet_w_mm"], res["pallet_l_mm"]) == (p["palW"], p["palL"])
                and key(res["layout"]) == key(p["boxes"])):
            ok += 1
        else:
            print("MISMATCH", c["id"])
    total_bad += n - ok
    print(f"{fn}: end-to-end match {ok}/{n}")
sys.exit(1 if total_bad else 0)
