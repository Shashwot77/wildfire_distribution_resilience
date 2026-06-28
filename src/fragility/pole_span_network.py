"""
plot_span_network.py
=====================================================================
Draw the IEEE 9500-node distribution system as a geographic network,
with each conductor SPAN rendered as a line connecting a pole to its
parent pole. Two panels side by side:

  LEFT  : lines colored by raw span_m_to_parent  (per-segment BFS span)
  RIGHT : lines colored by tributary_span_m      (collapsed L_c per pole)

Poles are plotted at their true (longitude, latitude). Feeders S1/S2/S3
are drawn together so the whole network is visible at once.

Big white background, big title, clear axis labels — presentation ready.
=====================================================================
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import Normalize
import matplotlib.cm as cm
import numpy as np
import pandas as pd
from pathlib import Path

# ── Load ──────────────────────────────────────────────────────────────────────
# This file: <PROJECT_ROOT>/src/fragility/pole_span_network.py
_HERE    = Path(__file__).resolve().parent      # src/fragility/
_PROJECT = _HERE.parents[1]                      # project root (2 levels up)

# ── Path resolution ───────────────────────────────────────────────────────────
# This file: <PROJECT_ROOT>/src/fragility/tributary_span.py
# parents[0] = src/fragility/
# parents[1] = src/
# parents[2] = PROJECT_ROOT/
OUT_DIR = _PROJECT / "outputs" / "bfs_trees"
IN = _PROJECT / "outputs" / "bfs_trees" / "pole_inventory_tributary.csv"
df = pd.read_csv(IN)

# Index poles by pole_id for fast parent lookup
df["pole_id"] = df["pole_id"].astype(str)
coord = df.set_index("pole_id")[["longitude", "latitude"]].to_dict("index")


def build_segments(span_col):
    """
    Build a list of line segments [(x0,y0),(x1,y1)] from each pole to its
    parent, plus the span value used to color each segment.
    """
    segs, vals = [], []
    for _, row in df.iterrows():
        pid = row["parent_pole_id"]
        if pd.isna(pid):
            continue
        pid = str(pid)
        if pid not in coord:
            continue
        x0, y0 = row["longitude"], row["latitude"]
        x1, y1 = coord[pid]["longitude"], coord[pid]["latitude"]
        v = row[span_col]
        if pd.isna(v):
            continue
        segs.append([(x0, y0), (x1, y1)])
        vals.append(float(v))
    return np.array(segs), np.array(vals)


# ── Figure setup ──────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(22, 12))
fig.patch.set_facecolor("white")

panels = [
    ("span_m_to_parent", "Raw BFS span\n(per-segment span to parent)", axes[0]),
    ("tributary_span_m", "Tributary span $L_c$\n(collapsed half-span load length)", axes[1]),
]

# Shared color scale so the two panels are directly comparable.
# Cap at the 97th percentile so a few long spans don't wash out the rest.
all_vals = pd.concat([
    df["span_m_to_parent"].dropna(),
    df["tributary_span_m"].dropna(),
])
vmax = np.percentile(all_vals, 97)
norm = Normalize(vmin=0, vmax=vmax)
cmap = matplotlib.colormaps["viridis"]

for span_col, title, ax in panels:
    ax.set_facecolor("white")
    segs, vals = build_segments(span_col)

    # Draw conductor spans as colored lines
    lc = LineCollection(segs, cmap=cmap, norm=norm, linewidths=1.4)
    lc.set_array(vals)
    ax.add_collection(lc)

    # Overlay poles as small dots
    ax.scatter(df["longitude"], df["latitude"], s=3,
               color="#333333", alpha=0.5, zorder=3)

    # Axis cosmetics
    ax.set_xlim(df["longitude"].min() - 0.005, df["longitude"].max() + 0.005)
    ax.set_ylim(df["latitude"].min() - 0.005, df["latitude"].max() + 0.005)
    ax.set_xlabel("Longitude (°)", fontsize=18, fontweight="bold", labelpad=10)
    ax.set_ylabel("Latitude (°)", fontsize=18, fontweight="bold", labelpad=10)
    ax.set_title(title, fontsize=22, fontweight="bold", pad=16)
    ax.tick_params(axis="both", labelsize=13)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linestyle=":", alpha=0.4, color="#999999")

    for spine in ax.spines.values():
        spine.set_edgecolor("#444444")
        spine.set_linewidth(1.2)

# ── Shared colorbar ───────────────────────────────────────────────────────────
sm = cm.ScalarMappable(cmap=cmap, norm=norm)
sm.set_array([])
cbar = fig.colorbar(sm, ax=axes, orientation="vertical",
                    fraction=0.025, pad=0.02)
cbar.set_label("Span length (m)", fontsize=18, fontweight="bold", labelpad=12)
cbar.ax.tick_params(labelsize=13)
cbar.ax.text(0.5, 1.02, f"capped at {vmax:.0f} m",
             transform=cbar.ax.transAxes, ha="center", fontsize=11,
             style="italic", color="#555555")

# ── Big main title ────────────────────────────────────────────────────────────
fig.suptitle(
    "IEEE 9500-Node Distribution System — Conductor Span Network",
    fontsize=30, fontweight="bold", y=0.98,
)
fig.text(0.5, 0.925,
         "Lines = conductor spans drawn at true geographic coordinates "
         "(Columbia Basin, WA) · colored by span length",
         ha="center", fontsize=15, style="italic", color="#444444")

out = OUT_DIR / "ieee9500_span_network.png"
Path(out).parent.mkdir(parents=True, exist_ok=True)
plt.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
print(f"Saved: {out}")
plt.close()