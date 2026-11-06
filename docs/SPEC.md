# Pallet Load Calculator: Technical Specification

This document specifies what `palletcalc.py` computes, the rules by which it reproduces the
reference calculator [onpallet.com](https://onpallet.com), the evidence supporting each
rule, and the validation methodology. Usage is described in [README.md](../README.md).
This project is not affiliated with onpallet.com or Lorenz Pan AG. All observations below
were made through the site's public web interface.

**Status (2026-11-06):** identical to the reference on every comparable case tested
(290 layouts box for box, 43 results pages figure for figure).

---

## 1. Problem definition

### 1.1 Inputs

| symbol | meaning | source column |
|---|---|---|
| `w`, `l` | box width and length, typed order | `width`, `length` |
| `h` | box height | `height` |
| `m` | box weight (kg or lbs, unit-free) | `weight` |
| `P` | pallet: one of the standard pallets or custom `Pw x Pl` | `pallet` |
| `H` | maximum load height, excluding the pallet | `load_height` |
| `u` | input unit, `mm` or `in` | `unit` |

### 1.2 Model

Every layer is identical. Boxes stand upright (height `h` vertical) and may only turn 90 degrees
on the pallet face. They may not overhang the pallet. Layers stack straight up to the
load height. The layer problem is the **Manufacturer's Pallet Loading Problem (MPLP)**:

> Given a rectangle `L x W` (the pallet, `L >= W`) and identical rectangles `a x b` (the
> box face), place as many as possible, each orthogonally in either orientation, inside
> the pallet without overlap.

MPLP's complexity class is open (not known to be NP-hard). Exact methods exist for
small instances. Practical solvers combine recursive partitioning with upper bounds that
prove optimality in most real cases.

The whole load is then

```
n_layer  = MPLP(pallet, box face)      boxes per layer
layers   = floor(H / h)
total    = n_layer * layers
```

---

## 2. Input normalization rules (derived)

Each rule lists its evidence. "Learn" and "holdout" refer to the datasets in section 6.

| # | Rule | Evidence |
|---|---|---|
| R1 | **mm input is rounded to whole mm, half up** (JavaScript `Math.round`). The page does this when you leave a field, which always happens before *Calculate*. | `onpallet.js` `checkInputValues` (`fac == 1` branch). Summary page S11 (300.4 / 399.6 / 1500.5 mm). |
| R2 | **inch input is rounded to 0.1 in, half up**, by the same handler. | `onpallet.js`; the browser turned 9.25 -> 9.3 and 7.35 -> 7.4 (S10). |
| R3 | **inches are converted as `x * 25.4` mm.** Box **width and length are then rounded down to whole mm** for the layout. Box **height, load height and custom pallet sides stay exact** (fractional mm). | 12 in -> 304 mm box (`pal.php`). S10: box face 236 x 345 mm, while `height` = 187.96 and `palW` = 1117.6 in the site's own layout data. |
| R4 | **Input limits** (the site silently clamps outside them): box sides 70 to 1300 mm, box height 70 to 2400, load height 300 to 2600, custom pallet sides 200 to 1300. **The calculator reports an error instead of clamping**, because silent changes would defeat data validation. Weight is handled separately (R10). | `onpallet.js` `loadformfields`. |
| R5 | **Standard pallets** (`palW x palL`, mm): euro 1200 x 800, industrial 1200 x 1000, US 1219 x 1016, half 800 x 600, australian 1165 x 1165. | `palW`/`palL` in `pal.php` responses. |
| R6 | **Custom pallets always use the longer side as `palW`**, whatever the typed order. | Holdout H045, H046, H047, H051, H052, H055, H057, H058 (typed short side first, the site swapped). |
| R6a | **In inch mode, the site labels a custom pallet's sides as `palW` = second typed side, `palL` = first typed side**, without sorting. The layout still uses the long side first (R7), so only the labels differ, and the results page shows the pallet as typed. The calculator keeps long-side-first labels so its output stays consistent with the layout. | Targeted I07, I11, I20, I21 (typed long side first, labels swapped); I06, I08, I10, I15 (typed short side first, agree by coincidence). |
| R7 | **The solver receives the pallet as (long, short) and the box as (width, length) in typed order, not sorted.** Box order only matters for ties: when both orientations give the same count, the first dimension runs along the pallet's long side. | Learn set, phase 1: typed (w, l) gives 144/144 identical layouts; (l, w) gives 113/144; sorted gives 135/144 (the 9 misses are all ties). |
| R8 | **`layers = floor(H / h)`**, using exact values (R3). | All 29 results pages; holdout varies `h` and `H`. |
| R8a | **In inch mode, the site computes layers as `floor((H_in * 25.4) / (h_in * 25.4))` in plain double-precision floating point, with no tolerance.** When the load height is an exact multiple of the box height, rounding error can drop a layer (48 in / 8 in gives 5.999999999999999, so 5 layers). The default mode reproduces this; `--mode best` uses the exact count. | Targeted Y08 (8 / 48 in: 5 layers), Y09, Y11, Y12; Y10 (10 / 60 in) and mm multiples are unaffected. |
| R9 | **Pallet heights** added for "loading height with pallet": euro 145, industrial 145, US 142, half 158, australian 151, custom 145 mm. | Difference between the two height rows on the results pages, one per pallet type. |
| R10 | **Weight** only affects `total_weight`, never the layout. The page rounds it to 0.1 and clamps it to at most 1300 in mm/kg mode. Its configured minimum of 0.1 rounds to 0 in practice. In inch/lb mode the page converts the 1300 limit as if weight were a length and caps weight at **51.2 lb** (1300 / 25.4), which is a site bug. The calculator accepts any non-negative weight and does not clamp. | Browser test on the page: 5000 kg -> 1300, 0 -> 0, 0.05 -> 0.1; in inch mode 60 lb and 5000 lb -> 51.2. |

---

## 3. Layer algorithm

### 3.1 What onpallet runs: phase 1, the recursive five-block algorithm

onpallet's layouts are reproduced exactly by **phase 1 of the Recursive Partitioning
Algorithm** of Birgin, Lobato and Morabito (2010), the "recursive five-block heuristic"
that refines Morabito and Morales (1998). The authors' C++ code is in
`third_party/RecursivePartitioningAlgorithm` (`bd.cpp`). Its main ingredients:

1. **Raster points.** Only cut positions that are non-negative integer combinations
   `i*a + j*b` need to be considered. Every sub-rectangle `(x, y)` is first *normalized*
   to the largest raster point not above each side. This loses nothing and makes
   subproblems shareable.
2. **Bounds per subproblem.**
   - The lower bound is the best homogeneous grid: `max(floor(x/a)*floor(y/b), floor(x/b)*floor(y/a))`.
   - The upper bound is the **Barnes bound**, which is tighter than the area bound
     `floor(x*y / (a*b))`.
   - When the bounds meet, the subproblem is solved and proven optimal.
3. **Five-block partitions.** For a rectangle `L x W` it tries every first-order
   non-guillotine cut `0 < x1 < x2 < L`, `0 < y1 < y2 < W` (with symmetry pruning
   `x1 <= L/2`, and `y1 + y2 <= W` when `x1 + x2 = L`). Each cut splits the rectangle into
   five blocks arranged as a pinwheel around a centre block. Vertical and horizontal
   guillotine cuts (`x1 = x2` or `y1 = y2`, up to half the side) are tried after these.
   Each block is solved by the same procedure, recursively, with memoization on
   normalized `(x, y)`.
4. **Pruning and early exit.** A partition is expanded only if the sum of its blocks'
   upper bounds beats the current best. The search stops as soon as the best equals the
   upper bound. Search order (non-guillotine first, then vertical, then horizontal, with
   increasing cut positions) decides which layout wins among equal counts. That is why
   the calculator uses this exact code rather than a re-implementation.
5. **Two passes.** A shallow pass runs first. If it does not prove optimality, the
   search restarts with full recursion depth.

The output is a list of box rectangles `(x1, y1, x2, y2)` in the solver's frame
(x = long pallet side). The calculator maps them to the pallet frame, transposing when
`palW < palL`.

### 3.2 Phase 2, the L-approach (`--mode best` only)

When phase 1 cannot prove optimality, the authors' program goes on to the
**L-approach**. It recursively divides the pallet into rectangles *and L-shaped pieces*,
which reaches staircase-like patterns that five-block cuts cannot. onpallet does not run
it, so the calculator only uses it in `--mode best` and for the `best_possible_per_layer`
column. In testing it found one extra box on 12 of 290 cases; the site returned the phase-1 count in every one of them. Both results are proven
optimal and checked for overlaps.

Local change: the environment variable `RECPART_PHASE1_ONLY=1` makes the program stop
after phase 1 and output the phase-1 layout. This is marked in `RecPartAlgorithm.cpp`
as required by GPLv3.

### 3.3 Pure-Python fallback (`--allow-fallback`)

`LayerSolver` in `palletcalc.py` combines a guillotine dynamic program over raster
points with one top-level five-block search, whose block widths are multiples of `a`
or `b`. It matched the site's counts on 140/144 learn cases, and fell one box short on
the other 4. It is only used when the C++ solver is unavailable and the user opts in.

### 3.4 Pipeline

1. Read the typed row.
2. Apply the browser rounding (R1, R2) and the unit conversion (R3), then check limits (R4).
3. Look up the pallet (R5) or orient the custom pallet (R6).
4. Round the box face and pallet down to whole mm for the solver.
5. Run RecPartAlgorithm phase 1 with input `(pallet long side, pallet short side)` and
   `(box width, box length)` in typed order (R7).
6. Map the layout back to the pallet frame.
7. Compute the summary figures (section 4).

---

## 4. Output formulas

All values come from the exact quantities of R3. Display rounding is 1 decimal,
dropping a trailing `.0` (onpallet shows `86%`, not `86.0%`).

| output | formula | site label |
|---|---|---|
| `boxes_per_layer` | `n_layer` (number of rectangles returned) | (results counter) |
| `layers` | `floor(H / h)`; in inch mode computed as in R8a | n layers |
| `total_boxes` | `n_layer * layers` | n packages |
| `total_weight` | `total * m` (pallet weight not included) | Total weight |
| `stack_height_mm` | `layers * h` (not the entered load height) | Loading height |
| `height_with_pallet_mm` | `layers * h + pallet height (R9)` | Loading height with pallet |
| `layer_area_used_pct` | `n_layer * a * b / (palW * palL)` | Surface usage |
| `volume_used_pct` | `surface * layers * h / H` | Volume usage |

For inch rows the site displays heights in inches: the mm value / 25.4, rounded to 0.1.
The calculator adds `stack_height_in` and `height_with_pallet_in` for that. Note on
`boxcount`: the site's layout data carries `boxcount = n_layer + 1` on every response.
The page displays `boxcount - 1`, and the results page's *n packages* equals
`n_layer * layers`. So `n_layer` is the number of rectangles, confirmed on all 29 pages.

**Display formatting** (observed on all 29 recorded pages; the calculator outputs numbers,
these rules matter only when comparing with the site):

- Numbers: rounded to 1 decimal, trailing `.0` dropped, no thousands separator.
- Package size: width x length x height in typed order, as the browser sent them, followed
  by ` mm` or ` in` (for example `333 x 222 x 150 mm`).
- Pallet size, standard pallets: short side first; mm glued to the unit (`800 x 1200mm`);
  inches converted from mm to 0.1 (`31.5 x 47.2 in`).
- Pallet size, custom pallets: typed order (not the layout's long-side-first order), as sent
  (`1300 x 1000mm`, `47.5 x 42.5 in`).

---

## 5. onpallet.com protocol (reference)

Observed through the public web interface. It is documented because the validation
tooling uses it; the calculator itself never contacts the site.

| step | request | response |
|---|---|---|
| 1 | `GET /` | session cookie (`PHPSESSID`) |
| 2 | `POST /index.php` with `p_unit, p_width, p_length, p_height, p_weight, p_type, ps_custW, ps_custL, p_loadheight, calculate` | HTML page with an inline script containing `{"pid": "<32 hex>", "num": 0}` |
| 3 | `POST /pal.php` with `pal={"pid":...,"num":0}` (same session) | JSON `{status, palcount, pal:{boxes:[{a,b,c,d}], palW, palL, height, weight, loadh, boxcount, ...}}` |
| 4 | `POST /sel.php` with `pid, palnum, palchange` | results page ("Detail results" table, layer alignment options) |
| - | `GET /count.php` | "pallets served" counter, polled every 5 s |

- `p_type`: `ps_pal1` euro, `ps_pal2` industrial, `ps_pal3` US, `ps_pal4` half,
  `ps_pal5` australian, `ps_palX` custom.
- Quirk: `ps_custW`/`ps_custL` must be non-empty (the page sends the minimums, 200 mm
  or 7.9 in) even for standard pallets. If they're blank, inch-mode requests fail
  server-side with a truncated page and no `pid`.
- `pal.php` status codes:
  - `0` ok.
  - `-6` box does not fit (seen for 1300 x 1300 and 900 x 900 boxes on euro).
  - `-7` the site gave up. This happens on some dense layouts (77 x 108 on industrial,
    90 x 95 on US...) but not all: 70 x 70 on euro with 187 boxes works. Probably a
    time or effort limit.
  - `-8` unknown `pid` or no session.
- Anonymous users get `palcount = 1` (only the best layout). Logged-in users may get
  alternatives; this was not investigated.
- Layer alignment modes on the results page (parallel, h-mirrored, v-mirrored,
  rotated) only mirror every other layer when drawing. Counts are unaffected.
- The layout coordinates in the page's live data are shifted to centre the drawing
  (`centerBoxes`). `pal.php` returns the raw coordinates.

---

## 6. Validation

### 6.1 Datasets (`validation/data/`)

| set | cases | design | site answered |
|---|---|---|---|
| learn | 150 | 90 random realistic boxes (100 to 600 mm) on all standard pallets; 20 small boxes (70 to 160); 15 custom pallets; 12 exact-fit / oversize / square edge cases; 6 layer-count edge cases; 7 classic hard MPLP instances, scaled | 144 (6 errors) |
| holdout | 60 | new random seed, never used for rule discovery; varied `h` and `H`; 15 custom pallets (several typed short side first) | 59 (1 error) |
| summary pages | 29 | every pallet type in mm and inches; decimal inches and mm; custom pallets in both units and both typed orders; weight clamps and rounding; box counts from 2 to 8806; load height equal to, a multiple of, and below box height; inputs pre-rounded and clamped exactly like the browser | 29 |
| targeted | 88 | designed for thin spots: 21 inch-mode layouts, 20 orientation ties, 10 new phase-1 gap instances (found by an offline scan of about 28,000 instances), 24 edge sizes, 13 layer edges; 14 also record the results page | 87 (1 error: `-6`) |

### 6.2 Results

| check | result |
|---|---|
| Layouts identical box for box (learn + holdout + targeted) | **290 / 290** |
| End to end from typed inputs (pallet dims, layers, layout) | **290 / 290** (4 differ only in the inch custom pallet labels, R6a) |
| Results-page figures (n packages, layers, heights, surface %, volume %, weight, package and pallet size text) | **29 / 29** (3 differ only in total weight, by design, R10) |
| `--mode best` vs site | 278 equal, **12 better by one box**, 0 worse (layer counts compared separately: best mode does not reproduce R8a) |
| Pure-Python fallback, counts | 140 / 144 (4 cases one box short) |

### 6.3 How the algorithm was identified

1. The scripts and network traffic showed the layout is computed on the server, so the
   method can't be read directly.
2. A home-built solver matched counts on 140/144 but fell short on small boxes. The
   site's layouts there were provably optimal staircase patterns.
3. The literature pointed to Birgin, Lobato and Morabito. Their program found every count
   the site found and beat it on 2 cases.
4. Their phase 1 alone matched the site's counts on 144/144. The 2 cases where the full
   program beat the site are exactly the documented gap between phase 1 and phase 2
   (the paper's 49 x 28 / 8 x 3 example: 56 vs 57).
5. Phase-1 layouts were identical on 135/144. The 9 misses were all orientation ties,
   resolved by R7 (typed box order): 144/144.
6. The holdout set then exposed R6 (custom pallet orientation), and the results pages
   exposed R3's exact-height detail for inches.
7. A targeted set of 88 cases exposed two inch-mode quirks of the site: the floating-point
   layer count (R8a) and the swapped custom pallet labels (R6a).

### 6.4 Re-running

All checks run offline against the recorded data:

```bash
make test       # unit tests, golden cases, regression over all 290 recorded layouts
make validate   # end-to-end check and results-page figures
MODE=best python3 validation/compare.py validation/data/learn_raw.jsonl validation/data/holdout_raw.jsonl
```

Recorded data:

| file | content |
|---|---|
| `validation/data/learn_cases.json`, `holdout_cases.json` | generated inputs |
| `validation/data/learn_raw.jsonl`, `holdout_raw.jsonl` | site layout response per input |
| `validation/data/summary_pages.json` | figures from the site's results table, per case |

To check whether the site has changed, record a fresh sample and compare. These commands
contact onpallet.com; keep the delay and the sample small.

```bash
python3 validation/collect.py validation/data/holdout_cases.json /tmp/recheck.jsonl --delay 1.5
python3 validation/end_to_end.py /tmp/recheck.jsonl
```

---

## 7. Known differences and open questions

**Intentional differences**

- Out-of-range inputs raise errors instead of being clamped (R4).
- Inputs the site rejects with `-7` are answered.
- Boxes that don't fit report `status = does_not_fit` instead of the site's error page.
- Weight is not clamped (R10). For inch rows heavier than 51.2 lb, and mm rows heavier than
  1300 kg, the calculator's `total_weight` uses the real weight; the site's total weight
  is understated. Box counts and layouts are unaffected.

- Custom pallet labels in inch mode stay long side first (R6a); the site swaps them.

**Not modelled** (the site doesn't either)

- Maximum pallet weight.
- Box crush strength.
- Overhang.
- Interlocking stability.
- Mixed-orientation layers.

**Open questions**

- **`-7` errors:** the exact trigger is unknown.
- **Decimals sent without the browser's rounding:** if a request skips the browser (pasted
  decimals sent directly), the server appears to floor box sides but use the raw load
  height in the volume figure. Real browser use always rounds first (R1/R2), so the
  replica follows the browser.
- **Logged-in users:** the extra alternative layouts they get are not reproduced.
- **Site changes:** if onpallet changes its algorithm or parameters, re-run section 6.4.

---

## 8. References

- E. G. Birgin, R. D. Lobato, R. Morabito. *An effective recursive partitioning approach
  for the packing of identical rectangles in a rectangle.* Journal of the Operational
  Research Society 61 (2010) 306-320. doi:10.1057/jors.2008.141.
  Code: [lobato.it/packing](http://lobato.it/packing/) (GPLv3).
- R. Morabito, S. Morales. *A simple and effective recursive procedure for the
  manufacturer's pallet loading problem.* JORS 49 (1998) 819-828.
- E. G. Birgin, R. Morabito, F. H. Nishihara. *A note on an L-approach for solving the
  manufacturer's pallet loading problem.* JORS 56 (2005) 1448-1451.
- E. R. Barnes. *Packing problems and inequalities.* (Barnes upper bound.)
