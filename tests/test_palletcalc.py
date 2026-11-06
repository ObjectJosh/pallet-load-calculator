"""Tests for palletcalc. Run: python3 -m unittest discover -s tests -v

Rule numbers (R1-R9) and formulas refer to docs/SPEC.md. Everything runs offline; tests that
need the compiled solver are skipped (with a reason) if it has not been built.
"""
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "validation"))

import palletcalc as pc  # noqa: E402
from check_layout import valid  # noqa: E402

HAVE_SOLVER = os.path.exists(pc.RECPART_BIN)
needs_solver = unittest.skipUnless(HAVE_SOLVER, "solver not built: make -C third_party/RecursivePartitioningAlgorithm")
DATA = os.path.join(ROOT, "validation", "data")


def key(boxes):
    return sorted((b["a"], b["b"], b["c"], b["d"]) for b in boxes)


class InputRules(unittest.TestCase):
    def test_r1_mm_rounds_half_up(self):
        self.assertEqual(pc.to_mm("300.5", "mm"), 301)
        self.assertEqual(pc.to_mm("300.4", "mm"), 300)
        self.assertEqual(pc.to_mm("301.5", "mm"), 302)  # not banker's rounding

    def test_r1_comma_decimal(self):
        self.assertEqual(pc.to_mm("300,6", "mm"), 301)

    def test_r2_r3_inches_rounded_to_tenth_then_exact_mm(self):
        self.assertAlmostEqual(pc.to_mm("9.25", "in"), 9.3 * 25.4)
        self.assertAlmostEqual(pc.to_mm("7.35", "in"), 7.4 * 25.4)

    def test_r3_inch_box_face_floored_height_exact(self):
        r = pc.calculate(12, 16, 10, 22, "us", 60, "in")
        xs = {b["c"] - b["a"] for b in r["layout"]} | {b["d"] - b["b"] for b in r["layout"]}
        self.assertEqual(xs, {304, 406})            # 304.8 -> 304, 406.4 -> 406
        self.assertEqual(r["stack_height_mm"], 1524)  # 6 x 254.0 exact

    def test_units_aliases_and_rejection(self):
        for u in ("mm", "MM", "", "in", "inch", "Inches"):
            pc.norm_unit(u)
        for u in ("cm", "feet", "inchs"):
            with self.assertRaises(ValueError):
                pc.norm_unit(u)

    def test_non_positive_and_non_numeric_rejected(self):
        for bad in ("0", "-5", "abc", ""):
            with self.assertRaises(ValueError):
                pc.calculate(bad, 400, 250, 1, "euro", 1500)

    def test_r4_limits_reported_not_clamped(self):
        with self.assertRaises(ValueError):
            pc.calculate(50, 400, 250, 1, "euro", 1500)       # box side < 70
        with self.assertRaises(ValueError):
            pc.calculate(300, 400, 250, 1, "euro", 100)       # load height < 300
        with self.assertRaises(ValueError):
            pc.calculate(300, 400, 250, 1, "custom:150x900", 1500)  # pallet side < 200

    def test_mm_values_given_as_inches_are_caught(self):
        with self.assertRaises(ValueError):
            pc.calculate(300, 400, 250, 10, "euro", 1500, "in")

    def test_unknown_pallet(self):
        with self.assertRaises(ValueError):
            pc.calculate(300, 400, 250, 1, "chep", 1500)

    def test_r5_standard_pallets(self):
        self.assertEqual(pc.PALLETS_MM["euro"], (1200, 800))
        self.assertEqual(pc.PALLETS_MM["us"], (1219, 1016))

    @needs_solver
    def test_r6_custom_pallet_long_side_first(self):
        a = pc.calculate(250, 300, 220, 3, "custom:700x1100", 1450)
        b = pc.calculate(250, 300, 220, 3, "custom:1100x700", 1450)
        self.assertEqual((a["pallet_w_mm"], a["pallet_l_mm"]), (1100, 700))
        self.assertEqual(key(a["layout"]), key(b["layout"]))

    def test_custom_pallet_separators(self):
        for spec in ("custom:1140x1140", "custom:1140×1140", "custom: 1140 * 1140"):
            r = pc.calculate(250, 250, 200, 6, spec, 1400, allow_fallback=True)
            self.assertEqual(r["boxes_per_layer"], 16)

    def test_r8_layers(self):
        r = pc.calculate(300, 400, 251, 1, "euro", 1500, allow_fallback=True)
        self.assertEqual(r["layers"], 5)
        r = pc.calculate(300, 400, 1600, 1, "euro", 1500, allow_fallback=True)
        self.assertEqual(r["layers"], 0)

    def test_r9_pallet_heights(self):
        for pal, ph in (("euro", 145), ("industrial", 145), ("us", 142), ("half", 158), ("australian", 151)):
            r = pc.calculate(200, 200, 200, 1, pal, 1000, allow_fallback=True)
            self.assertEqual(r["height_with_pallet_mm"] - r["stack_height_mm"], ph, pal)


@needs_solver
class SiteGoldenCases(unittest.TestCase):
    """Figures read from onpallet.com results pages (validation/data/summary_pages.json)."""

    def check(self, args, unit, expect):
        r = pc.calculate(*args, unit=unit)
        for k, v in expect.items():
            self.assertAlmostEqual(r[k], v, places=1, msg=k)

    def test_euro_230x370(self):
        self.check((230, 370, 180, 4.5, "euro", 1600), "mm",
                   dict(total_boxes=80, layers=8, stack_height_mm=1440, height_with_pallet_mm=1585,
                        layer_area_used_pct=88.6, volume_used_pct=79.8, total_weight=360))

    def test_us_inches(self):
        self.check((12, 16, 10, 22, "us", 60), "in",
                   dict(total_boxes=60, layers=6, stack_height_in=60, height_with_pallet_in=65.6,
                        layer_area_used_pct=99.7, volume_used_pct=99.7, total_weight=1320))

    def test_decimal_inches_custom_short_side_first(self):
        self.check((9.25, 13.6, 7.35, 5.5, "custom:30x44", 50), "in",
                   dict(total_boxes=54, layers=6, stack_height_in=44.4, height_with_pallet_in=50.1,
                        layer_area_used_pct=86, volume_used_pct=76.4, total_weight=297))

    def test_r7_tie_break_orientation(self):
        # Both orientations fit 2; the site puts the box's typed width across the pallet's short side.
        r = pc.calculate(402, 583, 200, 1, "euro", 1500)
        self.assertEqual(key(r["layout"]), [(0, 0, 583, 402), (583, 0, 1166, 402)])

    def test_phase1_vs_best(self):
        # Classic MPLP instance (49x28, 8x3) scaled x24: five-block finds 56, L-approach 57.
        site = pc.calc_layer(192, 72, 1176, 672)
        best = pc.calc_layer(192, 72, 1176, 672, mode="best")
        self.assertEqual((site["count"], site["best_count"]), (56, 57))
        self.assertEqual(best["count"], 57)
        self.assertEqual(best["count"], best["upper_bound"])

    def test_layouts_valid(self):
        for a, b, W, L in ((95, 114, 1200, 800), (72, 168, 600, 960), (70, 70, 1200, 800), (304, 406, 1219, 1016)):
            for mode in ("onpallet", "best"):
                r = pc.calc_layer(a, b, W, L, mode=mode)
                ok, msg = valid(r["boxes"], W, L, a, b)
                self.assertTrue(ok, f"{a}x{b} on {W}x{L} {mode}: {msg}")
                self.assertEqual(len(r["boxes"]), r["count"])

    def test_box_does_not_fit(self):
        r = pc.calculate(900, 900, 300, 25, "euro", 1500)
        self.assertEqual(r["boxes_per_layer"], 0)


@needs_solver
class RecordedSiteRegression(unittest.TestCase):
    """Every recorded onpallet.com response must be reproduced exactly from the typed inputs."""

    def test_all_recorded_cases(self):
        n = 0
        for name in ("learn_raw.jsonl", "holdout_raw.jsonl"):
            for line in open(os.path.join(DATA, name)):
                rec = json.loads(line)
                if "pal" not in rec:
                    continue
                c, p = rec["case"], rec["pal"]
                pal = c["pallet"] if c["pallet"] != "custom" else f"custom:{c['cw']}x{c['cl']}"
                r = pc.calculate(c["w"], c["l"], c["h"], 1, pal, c["load_h"])
                with self.subTest(case=c["id"]):
                    self.assertEqual((r["pallet_w_mm"], r["pallet_l_mm"]), (p["palW"], p["palL"]))
                    self.assertEqual(r["layers"], p["loadh"] // p["height"])
                    self.assertEqual(key(r["layout"]), key(p["boxes"]))
                n += 1
        self.assertEqual(n, 203)


class Fallback(unittest.TestCase):
    def test_missing_solver_raises_without_opt_in(self):
        with mock.patch.object(pc, "RECPART_BIN", "/nonexistent/RecPartAlgorithm"):
            with self.assertRaises(pc.SolverUnavailable):
                pc.calc_layer(300, 400, 1200, 800)
            r = pc.calc_layer(300, 400, 1200, 800, allow_fallback=True)
            self.assertEqual((r["count"], r["solver"]), (8, "python"))

    def test_python_solver_hard_instance(self):
        s = pc.LayerSolver(140, 100, 860, 520)   # 43x26 / 7x5 scaled: needs a pinwheel
        self.assertEqual(s.solve()[0], 31)


class CommandLine(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, os.path.join(ROOT, "palletcalc.py"), *args],
                              capture_output=True, text=True, cwd=ROOT)

    @needs_solver
    def test_csv_round_trip_and_statuses(self):
        with tempfile.TemporaryDirectory() as d:
            inp, out = os.path.join(d, "in.csv"), os.path.join(d, "out.csv")
            with open(inp, "w") as f:
                f.write("id,width,length,height,weight,pallet,load_height,unit\n"
                        "A,300,400,250,10,euro,1500,mm\n"
                        "B,900,900,300,25,euro,1500,mm\n"
                        "C,300,400,250,10,euro,1500,feet\n")
            res = self.run_cli(inp, "-o", out)
            self.assertEqual(res.returncode, 0, res.stderr)
            rows = {r["id"]: r for r in csv.DictReader(open(out))}
            self.assertEqual((rows["A"]["status"], rows["A"]["total_boxes"]), ("ok", "48"))
            self.assertEqual(rows["B"]["status"], "does_not_fit")
            self.assertEqual(rows["C"]["status"], "error")
            again = self.run_cli(inp, "-o", out)
            self.assertNotEqual(again.returncode, 0)
            self.assertIn("already exists", again.stderr)

    def test_one_reports_errors_cleanly(self):
        res = self.run_cli("--one", "0", "400", "250", "1", "euro", "1500")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("greater than 0", res.stderr)
        self.assertNotIn("Traceback", res.stderr)


if __name__ == "__main__":
    unittest.main()
