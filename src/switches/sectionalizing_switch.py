import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
 
from load_data   import load_busxy, load_edges, load_switch_states
from build_graph import build_adjacency, assign_feeders
from switches.switch_common import (
    load_dss_content, get_all_switches, plot_switch_category,
    build_feeder_lines, save_csv, BASE_DSS, BUSXY_DSS, SOURCES, OUT_DIR
)
from collections import Counter
 
print("=" * 60)
print("Feeder Sectionalizing Switch — Location Analysis")
print("=" * 60)
 
print("\n[1] Loading data (using existing load_data.py) ...")
busxy     = load_busxy(BUSXY_DSS)
edges     = load_edges(BASE_DSS)
sw_states = load_switch_states(BASE_DSS)
 
print("[2] Building adjacency list (using existing build_graph.py) ...")
adj, tie_switches_removed = build_adjacency(edges, sw_states)
 
print("[3] Assigning feeders (using existing build_graph.py) ...")
feeder_assign, _ = assign_feeders(SOURCES, adj)
 
print("\n[4] Classifying switches ...")
content  = load_dss_content()
switches = get_all_switches(content, busxy, sw_states, feeder_assign)
 
sect = [s for s in switches if s['category'] == 'Feeder Sectionalizing Switch']
print(f"  Total Feeder Sectionalizing Switches: {len(sect)}")
 
fc = Counter(s['feeder'] for s in sect)
pc = Counter(s['phase_type'] for s in sect)
print(f"  By feeder : S1={fc.get('S1',0)}  S2={fc.get('S2',0)}  S3={fc.get('S3',0)}")
print(f"  By phase  : 3-phase={pc.get('3-phase',0)}  1-phase={pc.get('1-phase',0)}")
 
print("\n[5] Saving CSV ...")
path, n = save_csv(switches, 'Feeder Sectionalizing Switch',
                   'switch_sectionalizing.csv')
print(f"  Saved -> {path}  ({n} rows)")
 
print("\n[6] Generating map ...")
feeder_lines = build_feeder_lines(edges, feeder_assign, busxy)
img_path = plot_switch_category(
    switches, 'Feeder Sectionalizing Switch',
    color='#000000', marker='s',
    title=f'Feeder Sectionalizing Switches ({len(sect)} total)\n'
          'Mid-feeder isolation points — used for fault sectioning',
    out_filename='switch_map_sectionalizing.png',
    feeder_lines=feeder_lines, busxy=busxy
)
print(f"  Saved -> {img_path}")
 
print("\nDone.")