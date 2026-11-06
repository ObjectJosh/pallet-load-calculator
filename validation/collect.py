#!/usr/bin/env python3
"""Record onpallet.com layouts for a list of cases (resumable).

  python3 validation/collect.py CASES.json OUT.jsonl [--delay 1.5]

CASES.json is a list of {"id", "w", "l", "h", "pallet", "load_h"[, "cw", "cl"]} in mm,
where pallet is a standard name or "custom" with cw/cl. Each output line is
{"case": {...}, "pal": {...}} or {"case": {...}, "error": "..."}.
"""
import argparse
import json
import os
import time

from onpallet_client import Session


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cases")
    ap.add_argument("out")
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between cases (default 1.5)")
    a = ap.parse_args()

    cases = json.load(open(a.cases))
    done = set()
    if os.path.exists(a.out):
        with open(a.out) as f:
            done = {json.loads(line)["case"]["id"] for line in f if line.strip()}

    with open(a.out, "a") as f:
        for i, c in enumerate(cases, 1):
            if c["id"] in done:
                continue
            pallet = c["pallet"] if c["pallet"] != "custom" else f"custom:{c['cw']}x{c['cl']}"
            rec = {"case": c}
            for attempt in range(3):
                try:
                    s = Session()
                    s.submit(c["w"], c["l"], c["h"], 1, pallet, c["load_h"])
                    rec["pal"] = s.layout()
                    rec.pop("error", None)
                    break
                except Exception as e:  # network errors are retried; site errors are recorded
                    rec["error"] = f"{type(e).__name__}: {e}"
                    if "status" in str(e) or "rejected" in str(e):
                        break
                    time.sleep(a.delay * (attempt + 2))
            f.write(json.dumps(rec) + "\n")
            f.flush()
            result = len(rec["pal"]["boxes"]) if "pal" in rec else rec["error"]
            print(f"[{i}/{len(cases)}] {c['id']}: {result}", flush=True)
            time.sleep(a.delay)


if __name__ == "__main__":
    main()
