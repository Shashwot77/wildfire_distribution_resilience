"""
tributary_span.py
=================================================================
Compute per-pole TRIBUTARY SPAN for the IEEE 9500 pole inventory.
Used as the conductor-load length L_c in the Darestani & Shafieezadeh
wood-pole wind fragility demand model:

    F_c = q_z · G · C_f · d_c · L_c · sin(θ)


Run from ANY directory:
    python src/fragility/tributary_span.py
    python src/fragility/tributary_span.py <in_csv> <out_dir>

=================================================================
REAL COLUMN NAMES (from your actual pole_inventory.csv)
---------------------------------------------------------
  pole_id            unique pole identifier (P0001 …)
  bus                OpenDSS bus name
  bus_type           e / m / l / n / p
  feeder             S1 / S2 / S3
  parent_bus         immediate BFS parent bus name
  span_m_to_parent   OpenDSS segment length to parent (m)
  phase_count        1 or 3
  pole_height_ft     35 or 40
  pole_height_m
  longitude / latitude
  spacing_template   ACSR overhead conductor template string
  … (other columns passed through unchanged)

=================================================================
BUS-TYPE CLASSIFICATION 
-----------------------------------------------------
  e / m / l   → REAL pole  (substation exit, backbone, lateral tap)
  n           → REAL pole  (regulator exit node OR cap-bank tap)
                144 n-buses have a real-pole parent (cap-bank style)
                 39 n-buses have a p-bus parent    (regulator pair)
  p           → PASS-THROUGH (device entry stub)
                p is always a short stub (median 7.9 m, max 189 m).
                It can be followed by n, m, or l — in all cases it
                is a device mounting point, NOT a separate structure.
                We collapse it: its span_m_to_parent is added to the
                next real pole's incoming gap.
  d           → ALREADY EXCLUDED from your inventory (d-buses appear
                only as parent_bus values, never as bus values).

ROOT DETECTION
--------------
  106 poles have a parent_bus that is NOT in the bus column.
  These are poles immediately downstream of:
    • d-bus switch terminals (d…_int)
    • Substation numeric buses (196-…, 221-…, 226-…)
    • Other excluded bus types (r, f, hv, q, reg)
  They are treated as feeder roots: real_gap_m = NaN, incoming half = 0.

=================================================================
TRIBUTARY SPAN FORMULA
-----------------------
For a real pole B with real-pole neighbours A (upstream) and
C1, C2, … (downstream):

    L_c(B) = 0.5 * real_gap(B)              ← incoming half-span
           + 0.5 * Σ real_gap(Ci)           ← outgoing half-spans

where real_gap(B) is the accumulated conductor length from B back
to its nearest real-pole ancestor (sum of all segment spans through
any p-bus stubs in between).

Dead-end poles (no real-pole children) receive only the incoming
half and are flagged is_deadend=True. Add the longitudinal
conductor-tension dead-end load separately in fragility model.
=================================================================
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

# ── Path resolution ───────────────────────────────────────────────────────────
# This file: <PROJECT_ROOT>/src/fragility/tributary_span.py
# parents[0] = src/fragility/
# parents[1] = src/
# parents[2] = PROJECT_ROOT/
_HERE    = Path(__file__).resolve().parent
_PROJECT = _HERE.parents[1]
_BFS_DIR = _PROJECT / "outputs" / "bfs_trees"

DEFAULT_IN  = _BFS_DIR / "pole_inventory.csv"
DEFAULT_OUT = _BFS_DIR                          # directory; files written below

# ── Column names (matching your real CSV exactly) ─────────────────────────────
COL_BUS    = "bus"
COL_TYPE   = "bus_type"
COL_PARENT = "parent_bus"
COL_SPAN   = "span_m_to_parent"
COL_FEEDER = "feeder"
COL_ID     = "pole_id"

# ── Classification sets ───────────────────────────────────────────────────────
REAL_POLE_TYPES = {"e", "m", "l", "n"}
PASSTHRU_TYPES  = {"p"}
# d-buses are already absent from the inventory (pre-filtered by your BFS code)


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 0 — Audit
# ─────────────────────────────────────────────────────────────────────────────
def audit(df: pd.DataFrame) -> None:
    """
    Print a full audit of the inventory before processing.
    Catches any bus type not accounted for in REAL_POLE_TYPES or PASSTHRU_TYPES,
    and reports how many poles are true feeder roots (parent not in bus column).
    """
    known = REAL_POLE_TYPES | PASSTHRU_TYPES
    counts = df[COL_TYPE].value_counts(dropna=False)
    print("\n── Bus-type inventory ──────────────────────────────────")
    print(counts.to_string())

    unknown = set(counts.index.astype(str)) - known
    if unknown:
        print(f"\n⚠  UNKNOWN types (treated as pass-through): {unknown}")
        print("   If these are real poles, add them to REAL_POLE_TYPES.")
    else:
        print("✓  All bus types accounted for.")

    all_buses = set(df[COL_BUS].astype(str))
    roots = df[~df[COL_PARENT].astype(str).isin(all_buses)]
    print(f"\n── Root poles (parent not in inventory): {len(roots)} ──")
    print(roots[COL_TYPE].value_counts().to_string())

    print(f"\n── Feeder breakdown ───────────────────────────────────")
    print(df[COL_FEEDER].value_counts().to_string())
    print()


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 1 — Classify
# ─────────────────────────────────────────────────────────────────────────────
def classify(df: pd.DataFrame) -> dict[str, bool]:
    """
    Return {bus -> is_real_pole} for every row.

    Rules (verified against your file):
      e / m / l / n  → True  (real pole)
      p              → False (device-entry stub, always short, collapse through)
      anything else  → False (treat unknown types as pass-through, warn above)
    """
    return {
        row[COL_BUS]: str(row[COL_TYPE]).strip().lower() in REAL_POLE_TYPES
        for _, row in df.iterrows()
    }


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 2 — Collapse: find real-pole ancestors and accumulate true gap lengths
# ─────────────────────────────────────────────────────────────────────────────
def build_collapsed_graph(
    df: pd.DataFrame,
    is_real: dict[str, bool],
) -> tuple[dict, dict]:
    """
    For every REAL pole, walk upward through pass-through nodes (p-stubs,
    any unknown types) accumulating span_m_to_parent until landing on
    another real pole or a root (parent not in inventory).

    Parameters
    ----------
    df      : full pole inventory
    is_real : output of classify()

    Returns
    -------
    real_parent : dict[bus -> str | None]
        Nearest real-pole ancestor in the collapsed graph.
        None  → this pole is a feeder root (no real parent above it).
    real_gap_m  : dict[bus -> float]
        True conductor length (m) from this pole to real_parent,
        accumulated across all collapsed stubs in between.
        NaN   → feeder root (no upstream real pole).
    """
    # Fast O(1) lookup dicts
    parent_of: dict[str, str | None] = {}
    span_of:   dict[str, float]      = {}
    all_buses  = set(df[COL_BUS].astype(str))

    for _, row in df.iterrows():
        bus = str(row[COL_BUS])
        p   = str(row[COL_PARENT])
        # A parent is valid only if it exists in the inventory
        parent_of[bus] = p if p in all_buses else None
        try:
            span_of[bus] = float(row[COL_SPAN])
        except (TypeError, ValueError):
            span_of[bus] = 0.0

    real_parent: dict[str, str | None] = {}
    real_gap_m:  dict[str, float]      = {}

    for bus in all_buses:
        if not is_real.get(bus, False):
            # Pass-through node — not assigned a tributary entry
            real_parent[bus] = None
            real_gap_m[bus]  = np.nan
            continue

        # ── Walk upward from this real pole ──────────────────────────────
        # Start by adding this pole's own segment to its BFS parent.
        accumulated = span_of.get(bus, 0.0)
        p = parent_of.get(bus)

        # Keep walking while the immediate ancestor is a pass-through stub.
        # This collapses p-bus stubs into their downstream real pole's gap.
        while p is not None and not is_real.get(p, False):
            accumulated += span_of.get(p, 0.0)
            p = parent_of.get(p)
        # ─────────────────────────────────────────────────────────────────

        real_parent[bus] = p   # None if no real ancestor (feeder root)
        real_gap_m[bus]  = accumulated if p is not None else np.nan

    return real_parent, real_gap_m


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 3 — Assign tributary span to every real pole
# ─────────────────────────────────────────────────────────────────────────────
def compute_tributary(
    df:          pd.DataFrame,
    is_real:     dict[str, bool],
    real_parent: dict[str, str | None],
    real_gap_m:  dict[str, float],
) -> tuple[dict, dict, dict]:
    """
    Assign L_c to every real pole:

        L_c(B) = 0.5 * real_gap_m[B]               (incoming half-span)
               + 0.5 * sum(real_gap_m[C] for C in real_children[B])

    Dead-end poles (no real-pole children) get only the incoming half.

    Returns
    -------
    L_c             : dict[bus -> float]  tributary span (m); NaN for pass-through
    is_deadend      : dict[bus -> bool]
    n_real_children : dict[bus -> int]
    """
    # Build collapsed child lists
    real_children: dict[str, list[str]] = defaultdict(list)
    for bus, rp in real_parent.items():
        if is_real.get(bus, False) and rp is not None:
            real_children[rp].append(bus)

    L_c:             dict[str, float] = {}
    is_deadend:      dict[str, bool]  = {}
    n_real_children: dict[str, int]   = {}

    for bus in df[COL_BUS].astype(str):
        if not is_real.get(bus, False):
            L_c[bus]             = np.nan
            is_deadend[bus]      = False
            n_real_children[bus] = 0
            continue

        # Incoming half
        incoming = real_gap_m.get(bus, np.nan)
        incoming_half = 0.0 if (incoming is None or np.isnan(incoming)) \
                            else 0.5 * incoming

        # Outgoing half (sum over all downstream real poles)
        kids = real_children.get(bus, [])
        outgoing_half = 0.5 * sum(
            real_gap_m[k] for k in kids
            if not (real_gap_m[k] is None or np.isnan(real_gap_m[k]))
        )

        L_c[bus]             = incoming_half + outgoing_half
        n_real_children[bus] = len(kids)
        is_deadend[bus]      = (len(kids) == 0)

    return L_c, is_deadend, n_real_children


# ─────────────────────────────────────────────────────────────────────────────
# Output helpers
# ─────────────────────────────────────────────────────────────────────────────
def _print_stats(df_real: pd.DataFrame, label: str = "ALL") -> None:
    """Print tributary span vs raw span comparison for a subset."""
    pct = [0.05, 0.25, 0.50, 0.75, 0.95]
    stats = pd.concat([
        df_real["tributary_span_m"]
            .describe(percentiles=pct)
            .rename("tributary_span_m"),
        df_real[COL_SPAN]
            .describe(percentiles=pct)
            .rename("raw_span_m_to_parent"),
    ], axis=1)
    print(f"\nDistribution over real poles — {label} (n={len(df_real)}):")
    print(stats.round(2).to_string())


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main(
    in_path:  Path | str = DEFAULT_IN,
    out_dir:  Path | str = DEFAULT_OUT,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Run all three stages and write outputs.

    Outputs written to out_dir:
      pole_inventory_tributary.csv    — all poles, new columns appended
      tributary_S1.csv                — real poles only, feeder S1
      tributary_S2.csv                — real poles only, feeder S2
      tributary_S3.csv                — real poles only, feeder S3

    Returns
    -------
    df      : full DataFrame (all poles, all columns)
    real_df : real-poles-only DataFrame
    """
    in_path = Path(in_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Reading : {in_path}")
    df = pd.read_csv(in_path)

    # Normalise key columns
    df[COL_BUS]    = df[COL_BUS].astype(str)
    df[COL_PARENT] = df[COL_PARENT].fillna("").astype(str)
    df[COL_TYPE]   = df[COL_TYPE].astype(str).str.strip().str.lower()

    # ── Audit ────────────────────────────────────────────────────────────
    audit(df)

    # ── Three stages ─────────────────────────────────────────────────────
    is_real                          = classify(df)
    real_parent, real_gap_m          = build_collapsed_graph(df, is_real)
    L_c, is_deadend, n_real_children = compute_tributary(
        df, is_real, real_parent, real_gap_m
    )

    # ── Attach new columns ───────────────────────────────────────────────
    df["is_real_pole"]     = df[COL_BUS].map(is_real)
    df["real_parent_bus"]  = df[COL_BUS].map(real_parent)
    df["real_gap_m"]       = df[COL_BUS].map(real_gap_m).round(3)
    df["n_real_children"]  = df[COL_BUS].map(n_real_children)
    df["is_deadend"]       = df[COL_BUS].map(is_deadend)
    df["tributary_span_m"] = df[COL_BUS].map(L_c).round(3)

    real_df = df[df["is_real_pole"]].copy()

    # ── Write full output ────────────────────────────────────────────────
    full_out = out_dir / "pole_inventory_tributary.csv"
    df.to_csv(full_out, index=False)
    print(f"Wrote (all poles)  : {full_out}")

    # ── Write per-feeder outputs (real poles only) ───────────────────────
    feeders = sorted(df[COL_FEEDER].dropna().unique())
    for feeder in feeders:
        feeder_df = real_df[real_df[COL_FEEDER] == feeder].copy()
        feeder_out = out_dir / f"tributary_{feeder}.csv"
        feeder_df.to_csv(feeder_out, index=False)
        print(f"Wrote ({feeder}, real)  : {feeder_out}  [{len(feeder_df)} poles]")

    # ── Summary ──────────────────────────────────────────────────────────
    n_total    = len(df)
    n_real     = int(df["is_real_pole"].sum())
    n_passthru = n_total - n_real
    n_dead     = int(real_df["is_deadend"].sum())
    n_roots    = int(real_df["real_gap_m"].isna().sum())

    print(f"""
╔══════════════════════════════════════════════════════════╗
  TRIBUTARY SPAN — SUMMARY
  ──────────────────────────────────────────────────────────
  Total poles in inventory          : {n_total}
  Real poles (fragility set)        : {n_real}
    of which p-bus (pass-through)   : {n_passthru}
  Feeder roots (no real parent)     : {n_roots}
  Dead-end poles (flag for tension) : {n_dead}
╚══════════════════════════════════════════════════════════╝""")

    # Overall stats
    _print_stats(real_df, label="ALL FEEDERS")

    # Per-feeder stats
    for feeder in feeders:
        _print_stats(
            real_df[real_df[COL_FEEDER] == feeder],
            label=feeder
        )

    print("""
NOTE: tributary_span_m is L_c in the fragility demand model.
      Dead-end poles (is_deadend=True) carry conductor tension:
      add a longitudinal dead-end load separately for those poles.
      See Darestani & Shafieezadeh (2019), Eq. for F_c.
""")

    return df, real_df


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    inp     = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_IN
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT
    main(inp, out_dir)