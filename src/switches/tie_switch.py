"""
PURPOSE: Locate and plot the N.O. Tie Switches.

"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
 
from load_data import load_busxy
from load_data import load_edges, load_switch_states
from build_graph import build_adjacency, assign_feeders
from switches.switch_common import (
    load_dss_content, get_all_switches, plot_switch_category,
    build_feeder_lines, save_csv, BASE_DSS, BUSXY_DSS, SOURCES, OUT_DIR
)
 
print("=" * 60)
print("N.O. Tie Switch — Location Analysis")
print("=" * 60)

print("\n[1] Loading data ...")
busxy       = load_busxy(BUSXY_DSS)
edges       = load_edges(BASE_DSS)
sw_states   = load_switch_states(BASE_DSS)

print("[2] Building adjacency list ...")
adj, tie_switches_removed = build_adjacency(edges, sw_states)

print("[3] Assigning feeders ...")
feeder_assign, _ = assign_feeders(SOURCES, adj)

# Switch-specific classification
print("\n[4] Classifying switches ...")
content  = load_dss_content()
switches = get_all_switches(content, busxy, sw_states, feeder_assign)

tie = [s for s in switches if s['category'] == 'N.O. Tie Switch']
print(f"  Total N.O. Tie Switches found: {len(tie)}")
for s in tie:
    print(f"    {s['switch_name']:<35} phases={s['phases']}  "
          f"feeder={s['feeder']}  {s['bus1']} <-> {s['bus2']}")

# Save CSV

print("\n[5] Saving CSV ...")
path, n = save_csv(switches, 'N.O. Tie Switch', 'switch_tie.csv')
print(f"  Saved -> {path}  ({n} rows)")

# Plot
print("\n[6] Generating map ...")
feeder_lines = build_feeder_lines(edges, feeder_assign, busxy)
img_path = plot_switch_category(
    switches, 'N.O. Tie Switch',
    color='#E74C3C', marker='D',
    title=f'N.O. Tie Switches ({len(tie)} total)\n'
          'Feeder boundary points — open by default in base case',
    out_filename='switch_map_tie.png',
    feeder_lines=feeder_lines, busxy=busxy
)
print(f"  Saved -> {img_path}")
 
print("\nDone.")