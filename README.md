# Pallet Load Calculator

[![CI](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)

An offline command-line calculator for uniform pallet loads. It computes how many identical
boxes fit on a pallet layer and in a full pallet load.

The default mode reproduces the results of the free online calculator at
[onpallet.com](https://onpallet.com) exactly, so existing data can be checked against it
in bulk without network access. An optional mode finds better layouts where they exist.

> This project is independent. It is not affiliated with, endorsed by, or connected to
> onpallet.com or Lorenz Pan AG.

## Features

- Batch processing from CSV, or single calculations from the command line.
- Layer layouts identical, box for box, to onpallet.com on all 203 validation cases,
  including a held-out set.
- Full load summary: boxes per layer, layers, total boxes, total weight, stack height,
  height including pallet, surface and volume utilization.
- `best` mode, using the L-approach, finds layouts with more boxes where onpallet.com's
  algorithm stops short. Each result is flagged when it is provably optimal.
- Millimetre and inch input, with the same rounding as the reference site.
- Strict input validation. Unknown units, non-positive or out-of-range dimensions, and
  boxes that do not fit are reported, never silently corrected.
- Standard pallets (EUR, industrial, US 48 x 40 in, half, Australian) and custom sizes.

## Requirements

- Python 3.9 or later (standard library only)
- A C++ compiler and `make`, to build the bundled solver
  - macOS: `xcode-select --install`
  - Debian/Ubuntu: `sudo apt install build-essential`
  - Windows: build under WSL; the solver uses POSIX headers and does not build with MSVC.

## Installation

```bash
git clone <repository-url> pallet-load-calculator
cd pallet-load-calculator
make            # builds the bundled solver
make test       # optional: runs the test suite
```

To install the `palletcalc` command into your environment:

```bash
pip install .
export PALLETCALC_SOLVER="$PWD/third_party/RecursivePartitioningAlgorithm/RecPartAlgorithm"
```

The solver is located through `PALLETCALC_SOLVER`, then the bundled build, then
`RecPartAlgorithm` on `PATH`. The examples below assume you run from the repository; with the
installed command, use `palletcalc` in place of `python3 palletcalc.py`.

## Usage

### Batch (CSV)

```bash
python3 palletcalc.py input.csv -o results.csv
```

The output file is not overwritten unless `--force` is given.

### Single calculation

```bash
python3 palletcalc.py --one WIDTH LENGTH HEIGHT WEIGHT PALLET LOAD_HEIGHT [--unit mm|in]
python3 palletcalc.py --one 300 400 250 10 euro 1500
```

### Options

| option | description |
|---|---|
| `-o`, `--output FILE` | output CSV (default `results.csv`) |
| `--force` | overwrite an existing output file |
| `--mode onpallet` | reproduce onpallet.com exactly (default) |
| `--mode best` | return the best layout found; may exceed onpallet.com by one box on hard instances |
| `--unit mm\|in` | unit for `--one` (default `mm`) |
| `--allow-fallback` | if the C++ solver is unavailable, use the pure-Python solver (not site-exact) |
| `--version` | print the version |

## Input format

A CSV file with a header row; see [`examples/input.csv`](examples/input.csv).

| column | required | description |
|---|---|---|
| `id` | no | product identifier, copied to the output |
| `width`, `length`, `height` | yes | box dimensions |
| `weight` | yes | weight per box (kg for mm rows, lb for inch rows) |
| `pallet` | yes | `euro`, `industrial`, `us`, `half`, `australian`, or `custom:WxL` |
| `load_height` | yes | maximum load height, excluding the pallet |
| `unit` | no | `mm` (default) or `in` (also `inch`, `inches`) |

Accepted ranges, matching onpallet.com:
- box sides: 70 to 1300 mm
- box height: 70 to 2400 mm
- load height: 300 to 2600 mm
- custom pallet sides: 200 to 1300 mm

## Output

Each input row is copied to the output, with these columns appended:

| column | description |
|---|---|
| `boxes_per_layer`, `layers`, `total_boxes` | load composition |
| `total_weight` | `total_boxes * weight`; pallet weight is not included |
| `pallet_w_mm`, `pallet_l_mm` | pallet dimensions used |
| `layer_area_used_pct` | share of the pallet surface covered by one layer |
| `volume_used_pct` | share of the available load volume used |
| `stack_height_mm`, `height_with_pallet_mm` | load height without and with the pallet (`_in` variants for inch rows) |
| `best_possible_per_layer` | best layer count found by either algorithm |
| `provably_optimal` | `True` if no layout can hold more boxes |
| `solver` | `recpart-phase1`, `recpart-full`, or `python` |
| `status` | `ok`, `does_not_fit`, or `error` |
| `error` | reason, when `status` is not `ok` |

## Accuracy

The calculator was validated against onpallet.com responses for 210 generated cases. Of
these, 203 were answered by the site; the other 7 returned server errors.

| check | result |
|---|---|
| layer layouts, box for box | 203 / 203 identical |
| end to end from raw inputs (pallet size, layers, layout) | 203 / 203 |
| results-page figures (12 pages across all pallet types and units) | 12 / 12 |
| `--mode best` | 2 cases improved by one box, none worse |

The methodology, the derived rules and the evidence for each are documented in
[`docs/SPEC.md`](docs/SPEC.md).

## Limitations

- Every layer is identical, boxes stand upright, and there is no overhang.
- Mixed products, weight limits, box crush strength and load stability are not modelled.
- Where onpallet.com returns a server error (very dense layouts), this tool returns a
  result, so there is no site value to compare against.
- Fidelity to onpallet.com was established by testing, not by access to its source code.
  If the site changes, re-run the validation (see [Testing](#testing)).

## Testing

```bash
make test       # unit tests and regression against all recorded reference cases
make validate   # end-to-end and results-page validation
```

All tests run offline against the reference data recorded in `validation/data/`. To record
new reference data from onpallet.com (rate-limited; use sparingly), see
[`docs/SPEC.md`](docs/SPEC.md#64-re-running).

## Project structure

```
palletcalc.py                  calculator: command-line interface and library
docs/SPEC.md                   technical specification and validation report
examples/input.csv             example input
tests/                         unit and regression tests
validation/                    validation scripts and recorded reference data
third_party/RecursivePartitioningAlgorithm/
                               layer solver by Birgin, Lobato and Morabito (GPLv3)
```

## How it works

Layer layouts come from the Recursive Partitioning Algorithm of Birgin, Lobato and
Morabito (2010). onpallet.com's results match phase 1 of that algorithm, the recursive
five-block heuristic. `--mode best` also runs phase 2, the L-approach. The authors'
reference implementation is bundled with one marked modification: an environment switch
that stops after phase 1. See [`docs/SPEC.md`](docs/SPEC.md) for the formal description.

## Acknowledgements

The layer solver is the work of Ernesto G. Birgin, Rafael D. Lobato and Reinaldo
Morabito. If you use this project in published work, please cite:

> E. G. Birgin, R. D. Lobato and R. Morabito. An effective recursive partitioning
> approach for the packing of identical rectangles in a rectangle. *Journal of the
> Operational Research Society* 61 (2010), 306-320. doi:10.1057/jors.2008.141

## License

Distributed under the GNU General Public License v3.0 or later, as required by the
bundled solver. See [`LICENSE`](LICENSE) and
[`third_party/RecursivePartitioningAlgorithm/LICENSE`](third_party/RecursivePartitioningAlgorithm/LICENSE).

"onpallet" is used only to identify the reference calculator. All trademarks belong to
their respective owners.
