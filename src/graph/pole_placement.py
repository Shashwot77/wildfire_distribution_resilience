# =============================================================================
# FILE: src/graph/pole_placement.py
# LOCATION: wildfire_distribution_resilience/src/graph/pole_placement.py
#
# PURPOSE: Identify distribution poles in the IEEE 9500 system using the
#          BFS tree. Assign pole heights based on bus type and phase count.
#          Calculate span lengths between consecutive poles per feeder.
#          Generate three visualisation figures and CSV inventory files.
#
# POLE PLACEMENT RULES:
#   Bus types that get poles:
#     e-bus  — feeder exit bus
#     m-bus  — MV junction (backbone pole)
#     l-bus  — lateral tap (service transformer pole)
#     n-bus  — intermediate node (regulator/capacitor mid-line point)
#     p-bus  — pole device node (adjacent to regulator or capacitor)
#   Bus types skipped:
#     h, x, s, sx, d, r, q, f, NUM — substation/transformer/customer/switch
#
#   Height rules:
#     3-phase (phases >= 3) → 40 ft  (12.19 m)
#     1-phase (phases == 1) → 35 ft  (10.67 m)
#
# HOW TO RUN (from project root):
#   (.venv) PS> python src/graph/pole_placement.py
#
# OUTPUTS (saved to outputs/bfs_trees/):
#   pole_inventory.csv          — all 2545 poles, all feeders combined
#   pole_inventory_S1.csv       — S1 feeder only
#   pole_inventory_S2.csv       — S2 feeder only
#   pole_inventory_S3.csv       — S3 feeder only
#   poles_combined_map.png      — all feeders on one geographic map
#   poles_per_feeder.png        — three separate feeder maps
#   poles_span_distribution.png — span length histograms per feeder
# =============================================================================

import os
import re
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from collections import defaultdict, deque, Counter

# =============================================================================
# SECTION 0 — PATHS  (only change these two lines)
# =============================================================================

BASE_DSS  = r"data\ieee9500\ieee9500_base.dss"
BUSXY_DSS = r"data\ieee9500\ieee9500_busxy.dss"
OUT_DIR   = r"outputs\bfs_trees"

os.makedirs(OUT_DIR, exist_ok=True)

# =============================================================================
# SECTION 1 — LOAD DATA
# =============================================================================

print("=" * 60)
print("IEEE 9500 — Pole Placement Analysis")
print("=" * 60)

print("\n[1] Loading data ...")

busxy = {}
with open(BUSXY_DSS, 'r') as f:
    for line in f:
        parts = line.strip().split(',')
        if len(parts) == 3:
            try:
                busxy[parts[0].strip()] = (float(parts[1]), float(parts[2]))
            except ValueError:
                pass

with open(BASE_DSS, 'r') as f:
    content = f.read()

# ── Line and switch edges ──
edges = []
for m in re.finditer(r'new Line\.(\S+)[^\n]*', content):
    line = m.group(0)
    b1 = re.search(r'bus1=(\S+?)[\s.]', line)
    b2 = re.search(r'bus2=(\S+?)[\s.]', line)
    if not b1 or not b2:
        continue
    ph = re.search(r'phases=(\d)',       line)
    ln = re.search(r'length=([\d.]+)',   line)
    sp = re.search(r'spacing=(\S+)',     line)
    na = re.search(r'normamps=([\d.]+)', line)
    sw = 'switch=y' in line.lower()
    edges.append({
        'name'      : m.group(1),
        'bus1'      : b1.group(1).split('.')[0],
        'bus2'      : b2.group(1).split('.')[0],
        'etype'     : 'switch' if sw else 'line',
        'phases'    : int(ph.group(1))   if ph else 0,
        'length_ft' : float(ln.group(1)) if ln else 0.0,
        'spacing'   : sp.group(1)        if sp else '',
        'normamps'  : float(na.group(1)) if na else 0.0,
        'is_switch' : sw,
    })

# ── Transformer edges ──
for m in re.finditer(
        r'new Transformer\.(\S+)[^\n]*\n((?:~[^\n]*\n)*)', content):
    block = m.group(0)
    wdgs  = re.findall(r'wdg=(\d)[^\n]*bus=(\S+?)[\s.\n]', block)
    bwdg  = {int(w): b.split('.')[0] for w, b in wdgs}
    if 1 in bwdg and 2 in bwdg:
        edges.append({
            'name': m.group(1), 'bus1': bwdg[1], 'bus2': bwdg[2],
            'etype': 'transformer', 'phases': 0,
            'length_ft': 0.0, 'spacing': '', 'normamps': 0.0,
            'is_switch': False,
        })

# ── Switch open/close states ──
sw_states = {}
for line in content.split('\n'):
    s = line.strip().lower()
    match = re.match(r'(open|close)\s+line\.(\S+)\s+', s)
    if match:
        sw_states[match.group(2)] = match.group(1)

open_count = sum(1 for v in sw_states.values() if v == 'open')
print(f"  Buses with coordinates : {len(busxy)}")
print(f"  Total edges            : {len(edges)}")
print(f"  Open tie switches      : {open_count}")

# =============================================================================
# SECTION 2 — BUILD ADJACENCY LIST (open switches removed)
# =============================================================================

print("\n[2] Building adjacency list (removing open tie switches) ...")

adj = defaultdict(list)
tie_switches = []

for e in edges:
    if e['is_switch']:
        state = sw_states.get(e['name'].lower(), 'close')
        if state == 'open':
            tie_switches.append(e)
            continue          # N.O. tie switch — do NOT add to graph
    adj[e['bus1']].append((e['bus2'], e))
    adj[e['bus2']].append((e['bus1'], e))

print(f"  Tie switches removed   : {len(tie_switches)}")

# =============================================================================
# SECTION 3 — ASSIGN FEEDERS
# =============================================================================

print("\n[3] Assigning buses to feeders ...")

SOURCES = {
    'S1': 'hvmv11sub1_lsb',
    'S2': 'hvmv11sub2_lsb',
    'S3': 'hvmv11sub3_lsb',
}

dist = {}
for label, root in SOURCES.items():
    d = {}; q = deque([(root, 0)])
    while q:
        bus, depth = q.popleft()
        if bus in d:
            continue
        d[bus] = depth
        for nb, _ in adj[bus]:
            if nb not in d:
                q.append((nb, depth + 1))
    dist[label] = d

# Robust union — every bus any substation can reach
all_buses = (set(dist['S1'].keys()) |
             set(dist['S2'].keys()) |
             set(dist['S3'].keys()))

feeder_assign = {}
for bus in all_buses:
    feeder_assign[bus] = min(SOURCES,
                             key=lambda s: dist[s].get(bus, 99999))

# =============================================================================
# SECTION 4 — BFS (build rooted tree per feeder)
# =============================================================================

print("\n[4] Running BFS for all three feeders ...")

def get_prefix(b):
    return b[0] if b[0].isalpha() else 'NUM'

def bfs_feeder(root, label):
    tree    = {}
    visited = set()
    queue   = deque([(root, None, None, 0)])

    while queue:
        bus, parent, edge, depth = queue.popleft()

        if bus in visited:
            continue
        visited.add(bus)

        prefix  = get_prefix(bus)
        coords  = busxy.get(bus, (None, None))
        span_ft = edge.get('length_ft', 0.0) if edge else 0.0
        phases  = edge.get('phases',    0)    if edge else 0
        spacing = edge.get('spacing',   '')   if edge else ''

        tree[bus] = {
            'parent'    : parent,
            'children'  : [],
            'depth'     : depth,
            'feeder'    : label,
            'prefix'    : prefix,
            'lon'       : coords[0],
            'lat'       : coords[1],
            'span_ft'   : span_ft,
            'edge_type' : edge.get('etype', '') if edge else '',
            'phases'    : phases,
            'spacing'   : spacing,
        }

        if parent and parent in tree:
            tree[parent]['children'].append(bus)

        for nb, ne in adj[bus]:
            if nb not in visited and feeder_assign.get(nb, label) == label:
                queue.append((nb, bus, ne, depth + 1))

    return tree

trees = {}
for label, root in SOURCES.items():
    tree   = bfs_feeder(root, label)
    depths = [info['depth'] for info in tree.values()]
    print(f"  {label}: {len(tree)} buses, max depth = {max(depths)}")
    trees[label] = tree

# =============================================================================
# SECTION 5 — POLE PLACEMENT
# =============================================================================

print("\n[5] Placing poles ...")

# Bus types that represent physical overhead poles
POLE_BUS_TYPES = {'e', 'm', 'l', 'n', 'p'}

def is_overhead(spacing):
    """
    Returns True if the spacing template indicates an overhead ACSR conductor.
    n and p buses are only included if they sit on an overhead line.
    """
    if not spacing:
        return False
    return ('acsr' in spacing or
            spacing.startswith('3ph') or
            spacing.startswith('1ph') or
            spacing.startswith('2ph') or
            'tpx' in spacing)

def get_phase_count(bus, info, adj):
    """
    Determine the phase count for a bus.
    First try the edge that connected this bus to its parent in the BFS tree.
    If that is 0 (transformer edge or root), check all adjacent line edges.
    """
    # Phase count from the parent edge (stored in BFS)
    ph = info.get('phases', 0)
    if ph > 0:
        return ph

    # Fall back: scan all edges connected to this bus
    for nb, e in adj[bus]:
        if e.get('etype') == 'line' and e.get('phases', 0) > 0:
            return e['phases']

    # Second fallback: check switch edges
    for nb, e in adj[bus]:
        if e.get('phases', 0) > 0:
            return e['phases']

    return 1   # default to 1-phase if nothing found

poles = {}
pole_id_counter = 1

for label, tree in trees.items():
    for bus, info in tree.items():
        prefix = info['prefix']

        # Determine eligibility
        if prefix in ('e', 'm', 'l'):
            # Always a pole — these are the primary distribution bus types
            eligible = True
        elif prefix in ('n', 'p'):
            # Only a pole if connected via an overhead conductor
            eligible = is_overhead(info['spacing'])
            if not eligible:
                # Check adjacent edges too (sometimes spacing is on the other side)
                for nb, e in adj[bus]:
                    if is_overhead(e.get('spacing', '')):
                        eligible = True
                        break
        else:
            eligible = False

        if not eligible:
            continue

        # Must have geographic coordinates
        if info['lon'] is None:
            continue

        # Get accurate phase count
        ph = get_phase_count(bus, info, adj)

        # Assign pole height
        pole_height_ft = 40 if ph >= 3 else 35
        phase_type     = '3-phase' if ph >= 3 else '1-phase'

        poles[bus] = {
            'pole_id'           : f"P{pole_id_counter:04d}",
            'bus'               : bus,
            'feeder'            : label,
            'bus_type'          : prefix,
            'phase_count'       : ph,
            'phase_type'        : phase_type,
            'pole_height_ft'    : pole_height_ft,
            'pole_height_m'     : round(pole_height_ft * 0.3048, 2),
            'longitude'         : info['lon'],
            'latitude'          : info['lat'],
            'depth_in_tree'     : info['depth'],
            'parent_bus'        : info['parent'] if info['parent'] else '',
            'span_ft_to_parent' : info['span_ft'],
            'span_m_to_parent'  : round(info['span_ft'] * 0.3048, 2),
            'spacing_template'  : info['spacing'],
        }
        pole_id_counter += 1

# Add parent pole ID now that all poles are known
for bus, pole in poles.items():
    parent = pole['parent_bus']
    pole['parent_pole_id'] = (poles[parent]['pole_id']
                              if parent and parent in poles else '')

# Summary
fc = Counter(p['feeder']         for p in poles.values())
bc = Counter(p['bus_type']       for p in poles.values())
hc = Counter(p['pole_height_ft'] for p in poles.values())

print(f"\n  Total poles placed     : {len(poles)}")
print(f"  By feeder  : S1={fc['S1']}  S2={fc['S2']}  S3={fc['S3']}")
print(f"  By bus type: e={bc['e']}  m={bc['m']}  l={bc['l']}  "
      f"n={bc['n']}  p={bc['p']}")
print(f"  By height  : 40ft(3-phase)={hc[40]}  35ft(1-phase)={hc[35]}")

# =============================================================================
# SECTION 6 — SPAN STATISTICS
# =============================================================================

print("\n[6] Computing span statistics per feeder ...")

for label in ['S1', 'S2', 'S3']:
    fp    = {b: p for b, p in poles.items() if p['feeder'] == label}
    spans = [p['span_ft_to_parent'] for p in fp.values()
             if p['parent_bus'] in poles and p['span_ft_to_parent'] > 0]

    if not spans:
        print(f"  {label}: no pole-to-pole spans found")
        continue

    print(f"\n  Feeder {label}:")
    print(f"    Total poles            : {len(fp)}")
    print(f"    Pole-to-pole spans     : {len(spans)}")
    print(f"    Min span               : {min(spans):.1f} ft  "
          f"({min(spans)*0.3048:.1f} m)")
    print(f"    Max span               : {max(spans):.1f} ft  "
          f"({max(spans)*0.3048:.1f} m)")
    print(f"    Average span           : {np.mean(spans):.1f} ft  "
          f"({np.mean(spans)*0.3048:.1f} m)")
    print(f"    Median span            : {np.median(spans):.1f} ft  "
          f"({np.median(spans)*0.3048:.1f} m)")
    print(f"    Total overhead length  : "
          f"{sum(spans)*0.3048/1000:.2f} km")

# =============================================================================
# SECTION 7 — SAVE CSV FILES
# =============================================================================

print("\n[7] Saving pole inventory to CSV ...")

rows = []
for bus, pole in poles.items():
    rows.append({
        'pole_id'           : pole['pole_id'],
        'bus'               : bus,
        'feeder'            : pole['feeder'],
        'bus_type'          : pole['bus_type'],
        'phase_count'       : pole['phase_count'],
        'phase_type'        : pole['phase_type'],
        'pole_height_ft'    : pole['pole_height_ft'],
        'pole_height_m'     : pole['pole_height_m'],
        'longitude'         : pole['longitude'],
        'latitude'          : pole['latitude'],
        'depth_in_tree'     : pole['depth_in_tree'],
        'parent_bus'        : pole['parent_bus'],
        'parent_pole_id'    : pole['parent_pole_id'],
        'span_ft_to_parent' : pole['span_ft_to_parent'],
        'span_m_to_parent'  : pole['span_m_to_parent'],
        'spacing_template'  : pole['spacing_template'],
    })

df = pd.DataFrame(rows)

# Combined CSV
csv_all = os.path.join(OUT_DIR, 'pole_inventory.csv')
df.to_csv(csv_all, index=False)
print(f"  Saved -> {csv_all}  ({len(df)} rows)")

# Per-feeder CSVs
for label in ['S1', 'S2', 'S3']:
    df_f  = df[df['feeder'] == label].reset_index(drop=True)
    path  = os.path.join(OUT_DIR, f'pole_inventory_{label}.csv')
    df_f.to_csv(path, index=False)
    print(f"  Saved -> {path}  ({len(df_f)} rows)")

# =============================================================================
# SECTION 8 — VISUALISATION
# =============================================================================

print("\n[8] Generating figures ...")

FCOLS  = {'S1': '#378ADD', 'S2': '#1D9E75', 'S3': '#D85A30'}
FNAMES = {'S1': 'East',    'S2': 'South',   'S3': 'Northwest'}

# ── FIGURE 1: Combined map ────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(16, 12))
fig.patch.set_facecolor('#0D1117')
ax.set_facecolor('#0D1117')

# Span lines (background)
for bus, pole in poles.items():
    parent = pole['parent_bus']
    if parent and parent in poles:
        c = FCOLS[pole['feeder']]
        ax.plot([poles[parent]['longitude'], pole['longitude']],
                [poles[parent]['latitude'],  pole['latitude']],
                color=c, lw=1.5, alpha=0.45, zorder=1)

# Pole markers by type
for label in ['S1', 'S2', 'S3']:
    c  = FCOLS[label]
    fp = {b: p for b, p in poles.items() if p['feeder'] == label}

    e_xy  = [(p['longitude'], p['latitude']) for p in fp.values()
             if p['bus_type'] == 'e']
    m3_xy = [(p['longitude'], p['latitude']) for p in fp.values()
             if p['bus_type'] == 'm' and p['phase_count'] >= 3]
    m1_xy = [(p['longitude'], p['latitude']) for p in fp.values()
             if p['bus_type'] == 'm' and p['phase_count'] < 3]
    l_xy  = [(p['longitude'], p['latitude']) for p in fp.values()
             if p['bus_type'] == 'l']
    np_xy = [(p['longitude'], p['latitude']) for p in fp.values()
             if p['bus_type'] in ('n', 'p')]

    if e_xy:
        ax.scatter(*zip(*e_xy),  c='white', s=150, marker='*', zorder=8)
    if m3_xy:
        ax.scatter(*zip(*m3_xy), c=c, s=20, marker='s', alpha=0.7, zorder=4)
    if m1_xy:
        ax.scatter(*zip(*m1_xy), c=c, s=10, marker='o', alpha=0.5, zorder=3)
    if l_xy:
        ax.scatter(*zip(*l_xy),  c=c, s=14, marker='^', alpha=0.65, zorder=5)
    if np_xy:
        ax.scatter(*zip(*np_xy), c=c, s=8,  marker='D', alpha=0.4, zorder=3)

# Substation markers
for label, root in SOURCES.items():
    if root in busxy:
        rx, ry = busxy[root]
        ax.scatter([rx], [ry], c='yellow', s=320, marker='*', zorder=9)
        ax.text(rx + 0.003, ry + 0.004, f'S{label[1]}',
                color='yellow', fontsize=11, fontweight='bold', zorder=10)

ax.set_title('IEEE 9500 — Pole Placement Map\n'
             'e/m/l/n/p-bus poles  ·  35 ft (1-phase)  ·  40 ft (3-phase)',
             color='white', fontsize=20, fontweight='bold')
ax.set_xlabel('Longitude', color='white', fontsize=9)
ax.set_ylabel('Latitude',  color='white', fontsize=9)
ax.tick_params(colors='white', labelsize=8)
ax.set_aspect('equal')
ax.grid(True, alpha=0.15, color='white', linestyle='--', linewidth=0.4)
for spine in ax.spines.values():
    spine.set_edgecolor('#30363D')

legend_elements = [
    Line2D([0],[0],marker='*',color='w',markerfacecolor='white',
           markersize=9,  label='e-bus  feeder exit',        linestyle='None'),
    Line2D([0],[0],marker='s',color='w',markerfacecolor='#378ADD',
           markersize=8,  label='m-bus 3-phase (40 ft)',     linestyle='None'),
    Line2D([0],[0],marker='o',color='w',markerfacecolor='#378ADD',
           markersize=7,  label='m-bus 1-phase (35 ft)',     linestyle='None'),
    Line2D([0],[0],marker='^',color='w',markerfacecolor='#378ADD',
           markersize=8,  label='l-bus (35 or 40 ft)',       linestyle='None'),
    Line2D([0],[0],marker='D',color='w',markerfacecolor='#378ADD',
           markersize=6,  label='n/p-bus overhead (35/40ft)',linestyle='None'),
    Line2D([0],[0],color='#378ADD',lw=1.5,label='S1 spans (East)'),
    Line2D([0],[0],color='#1D9E75',lw=1.5,label='S2 spans (South)'),
    Line2D([0],[0],color='#D85A30',lw=1.5,label='S3 spans (Northwest)'),
    Line2D([0],[0],marker='*',color='w',markerfacecolor='yellow',
           markersize=14, label='Substation',                linestyle='None'),
]
ax.legend(handles=legend_elements, loc='lower right', fontsize=14,
          frameon=True, facecolor='#161B22',
          edgecolor='#30363D', labelcolor='white')

h40  = hc[40]; h35 = hc[35]
stats = (f"Total poles : {len(poles):,}\n"
         f"S1 : {fc['S1']} poles\n"
         f"S2 : {fc['S2']} poles\n"
         f"S3 : {fc['S3']} poles\n"
         f"40 ft (3φ) : {h40}\n"
         f"35 ft (1φ) : {h35}")
ax.text(0.02, 0.98, stats, transform=ax.transAxes,
        fontsize=8, va='top', color='#cdd6f4', fontfamily='monospace',
        bbox=dict(facecolor='#0D1117', edgecolor='#378ADD',
                  linewidth=0.8, boxstyle='round,pad=0.4'))

plt.tight_layout()
p1 = os.path.join(OUT_DIR, 'poles_combined_map.png')
plt.savefig(p1, dpi=160, bbox_inches='tight', facecolor='#0D1117')
plt.close()
print(f"  Saved -> {p1}")

# ── FIGURE 2: Per-feeder panels ───────────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(22, 8))
fig.patch.set_facecolor('#0D1117')
fig.suptitle('IEEE 9500 — Pole Placement per Feeder\n'
             'Span lines: lighter = shorter  ·  darker = longer',
             color='white', fontsize=20, fontweight='bold', y=1.01)

for idx, (label, _) in enumerate(trees.items()):
    ax = axes[idx]
    ax.set_facecolor('#0D1117')
    c  = FCOLS[label]
    fp = {b: p for b, p in poles.items() if p['feeder'] == label}

    span_vals = [p['span_ft_to_parent'] for p in fp.values()
                 if p['parent_bus'] in poles and p['span_ft_to_parent'] > 0]
    vmin = min(span_vals) if span_vals else 0
    vmax = max(span_vals) if span_vals else 1000

    # Span lines coloured by relative length
    for bus, pole in fp.items():
        parent = pole['parent_bus']
        if parent and parent in poles and pole['span_ft_to_parent'] > 0:
            norm  = (pole['span_ft_to_parent'] - vmin) / (vmax - vmin + 1)
            alpha = 0.2 + 0.7 * norm
            ax.plot([poles[parent]['longitude'], pole['longitude']],
                    [poles[parent]['latitude'],  pole['latitude']],
                    color=c, lw=0.6, alpha=alpha, zorder=1)

    e_xy  = [(p['longitude'],p['latitude']) for p in fp.values() if p['bus_type']=='e']
    m3_xy = [(p['longitude'],p['latitude']) for p in fp.values()
             if p['bus_type']=='m' and p['phase_count']>=3]
    m1_xy = [(p['longitude'],p['latitude']) for p in fp.values()
             if p['bus_type']=='m' and p['phase_count']<3]
    l_xy  = [(p['longitude'],p['latitude']) for p in fp.values() if p['bus_type']=='l']
    np_xy = [(p['longitude'],p['latitude']) for p in fp.values()
             if p['bus_type'] in ('n','p')]

    if e_xy:  ax.scatter(*zip(*e_xy),  c='white', s=200, marker='*', zorder=8)
    if m3_xy: ax.scatter(*zip(*m3_xy), c=c, s=25,  marker='s', alpha=0.9, zorder=4)
    if m1_xy: ax.scatter(*zip(*m1_xy), c=c, s=12,  marker='o', alpha=0.7, zorder=3)
    if l_xy:  ax.scatter(*zip(*l_xy),  c=c, s=18,  marker='^', alpha=0.85, zorder=5)
    if np_xy: ax.scatter(*zip(*np_xy), c=c, s=10,  marker='D', alpha=0.6, zorder=3)

    root = list(SOURCES.values())[idx]
    if root in busxy:
        ax.scatter([busxy[root][0]], [busxy[root][1]],
                   c='yellow', s=350, marker='*', zorder=9)

    h40_f = sum(1 for p in fp.values() if p['pole_height_ft'] == 40)
    h35_f = sum(1 for p in fp.values() if p['pole_height_ft'] == 35)
    spans_pp = [p['span_ft_to_parent'] for p in fp.values()
                if p['parent_bus'] in poles and p['span_ft_to_parent'] > 0]

    if spans_pp:
        info_txt = (f"Poles    : {len(fp)}\n"
                    f"40ft(3φ) : {h40_f}\n"
                    f"35ft(1φ) : {h35_f}\n"
                    f"Spans    : {len(spans_pp)}\n"
                    f"Min      : {min(spans_pp):.0f} ft\n"
                    f"Max      : {max(spans_pp):.0f} ft\n"
                    f"Avg      : {np.mean(spans_pp):.0f} ft\n"
                    f"Total    : {sum(spans_pp)*0.3048/1000:.1f} km")
    else:
        info_txt = f"Poles : {len(fp)}\nNo spans"

    ax.text(0.02, 0.98, info_txt, transform=ax.transAxes,
            fontsize=7.5, va='top', color='#cdd6f4', fontfamily='monospace',
            bbox=dict(facecolor='#0D1117', edgecolor=c,
                      linewidth=0.8, boxstyle='round,pad=0.35'))

    ax.set_title(f'Feeder {label} — {FNAMES[label]}\n{len(fp)} poles',
                 color=c, fontsize=16, fontweight='bold')
    ax.set_xlabel('Longitude', color='white', fontsize=12)
    ax.set_ylabel('Latitude',  color='white', fontsize=12)
    ax.tick_params(colors='white', labelsize=10)
    ax.set_aspect('equal')
    ax.grid(True, alpha=0.15, color='white', linestyle='--', linewidth=0.4)
    for spine in ax.spines.values():
        spine.set_edgecolor('#30363D')

plt.tight_layout()
p2 = os.path.join(OUT_DIR, 'poles_per_feeder.png')
plt.savefig(p2, dpi=160, bbox_inches='tight', facecolor='#0D1117')
plt.close()
print(f"  Saved -> {p2}")

# ── FIGURE 3: Span distribution ───────────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(18, 5))
fig.patch.set_facecolor('#0D1117')
fig.suptitle('IEEE 9500 — Span Length Distribution per Feeder\n'
             '(pole-to-pole spans only)',
             color='white', fontsize=20, fontweight='bold', y=1.02)

for idx, (label, _) in enumerate(trees.items()):
    ax = axes[idx]
    ax.set_facecolor('#161B22')
    c  = FCOLS[label]
    fp = {b: p for b, p in poles.items() if p['feeder'] == label}
    spans = [p['span_ft_to_parent'] for p in fp.values()
             if p['parent_bus'] in poles and p['span_ft_to_parent'] > 0]

    if not spans:
        ax.set_title(f'Feeder {label} — no spans', color=c, fontsize=11)
        continue

    ax.hist(spans, bins=40, color=c, alpha=0.8,
            edgecolor='#0D1117', linewidth=0.4)
    mean_s   = np.mean(spans)
    median_s = np.median(spans)
    ax.axvline(x=mean_s,   color='white',  lw=1.5, linestyle='--',
               label=f'Mean   {mean_s:.0f} ft')
    ax.axvline(x=median_s, color='yellow', lw=1.5, linestyle=':',
               label=f'Median {median_s:.0f} ft')

    ax.set_title(f'Feeder {label}', color=c, fontsize=11, fontweight='bold')
    ax.set_xlabel('Span length (ft)', color='white', fontsize=9)
    ax.set_ylabel('Number of spans',  color='white', fontsize=9)
    ax.tick_params(colors='white', labelsize=8)
    ax.legend(fontsize=8, facecolor='#0D1117',
              edgecolor='#30363D', labelcolor='white')
    ax.grid(True, alpha=0.2, color='white', linestyle='--')
    for spine in ax.spines.values():
        spine.set_edgecolor('#30363D')

    p25, p75, p95 = np.percentile(spans, [25, 75, 95])
    info_txt = (f"n      = {len(spans)}\n"
                f"Min    = {min(spans):.0f} ft\n"
                f"Max    = {max(spans):.0f} ft\n"
                f"P25    = {p25:.0f} ft\n"
                f"P75    = {p75:.0f} ft\n"
                f"P95    = {p95:.0f} ft\n"
                f"Total  = {sum(spans)*0.3048/1000:.1f} km")
    ax.text(0.97, 0.97, info_txt, transform=ax.transAxes,
            fontsize=8, va='top', ha='right',
            color='#cdd6f4', fontfamily='monospace',
            bbox=dict(facecolor='#0D1117', edgecolor=c,
                      linewidth=0.8, boxstyle='round,pad=0.35'))

plt.tight_layout()
p3 = os.path.join(OUT_DIR, 'poles_span_distribution.png')
plt.savefig(p3, dpi=160, bbox_inches='tight', facecolor='#0D1117')
plt.close()
print(f"  Saved -> {p3}")

# =============================================================================
# SUMMARY
# =============================================================================
print("\n" + "=" * 60)
print("DONE")
print("=" * 60)
print(f"\nOutputs in: {OUT_DIR}")
print(f"  pole_inventory.csv          ({len(poles)} poles, all feeders)")
print(f"  pole_inventory_S1.csv       ({fc['S1']} poles)")
print(f"  pole_inventory_S2.csv       ({fc['S2']} poles)")
print(f"  pole_inventory_S3.csv       ({fc['S3']} poles)")
print("  poles_combined_map.png")
print("  poles_per_feeder.png")
print("  poles_span_distribution.png")