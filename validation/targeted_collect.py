#!/usr/bin/env python3
"""Record onpallet.com responses for the targeted cases (resumable, strictly sequential).

  python3 validation/targeted_collect.py [--delay 1.5] [--max 100]

Reads data/targeted_cases.json (inputs already rounded like the browser), appends one line
per case to data/targeted_raw.jsonl: {"case": {...}, "pal": {...}[, "summary": {...}]} or
{"case": {...}, "error": "..."}. Cases with "summary": true also record the results page.
This contacts the site: keep the delay, never run two copies at once.
"""
import argparse
import json
import os
import time

from onpallet_client import Session

HERE = os.path.dirname(os.path.abspath(__file__))
CASES = os.path.join(HERE, "data", "targeted_cases.json")
OUT = os.path.join(HERE, "data", "targeted_raw.jsonl")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--max", type=int, default=100, help="max calculations this run")
    a = ap.parse_args()
    cases = json.load(open(CASES))
    done = set()
    if os.path.exists(OUT):
        done = {json.loads(ln)["case"]["id"] for ln in open(OUT) if ln.strip()}
    sent = 0
    with open(OUT, "a") as f:
        for c in cases:
            if c["id"] in done:
                continue
            if sent >= a.max:
                print("calculation budget reached")
                break
            rec = {"case": c}
            for attempt in range(2):
                sent += 1
                try:
                    s = Session()
                    s.submit(c["width"], c["length"], c["height"], c["weight"], c["pallet"],
                             c["load_height"], c["unit"])
                    rec["pal"] = s.layout()
                    rec.pop("error", None)
                    if c.get("summary"):
                        try:
                            rec["summary"] = s.summary()
                        except Exception as e:
                            rec["summary_error"] = f"{type(e).__name__}: {e}"
                    break
                except Exception as e:  # site errors are recorded, network errors retried once
                    rec["error"] = f"{type(e).__name__}: {e}"
                    if "status" in str(e) or "rejected" in str(e):
                        break
                    time.sleep(a.delay * 3)
            f.write(json.dumps(rec) + "\n")
            f.flush()
            print(c["id"], len(rec["pal"]["boxes"]) if "pal" in rec else rec["error"], flush=True)
            time.sleep(a.delay)


if __name__ == "__main__":
    main()
