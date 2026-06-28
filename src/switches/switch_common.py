""" 
Helper functions used by all five switch-type scripts. 
    Avoid repeating classification, parsing, and plotting code five times.
    Each .py script imports from this file.

"""

import re
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from collections import Counter

#=============================================================================
# Path
#=============================================================================

BASE_DSS = r"data\ieee9500\ieee9500_base.dss"
BUSXY_DSS = r"data\ieee9500\ieee9500_busxy.dss"
OUT_DIR   = r"outputs\bfs_trees"

FEEDER_COL = {'S1': '#378ADD', 'S2': '#1D9E75', 'S3': '#D85A30'}
SOURCES = {
    'S1': 'hvmv11sub1_lsb',
    'S2': 'hvmv11sub2_lsb',
    'S3': 'hvmv11sub3_lsb',
}

def load_dss_content():
    """" Read the base.dss file as raw text."""

    with open(BASE_DSS, 'r') as f:
        return f.read()
    

def load_busxy():
    busxy = {}
    with open(BUSXY_DSS, 'r') as f:
        for line in f:
            parts = line.strip().split(',')
            if len(parts) == 3:
                try:
                    busxy[parts[0].strip()] = (float(parts[1]), float(parts[2]))
                except ValueError:
                    pass
    return busxy

def load_switch_states_from_text(content):
    """ Parsing open/close command directly from DSS text."""
    sw_states = {}
    for line in content.split('\n'):
        s = line.strip().lower
        m = re.match(r'(open|close)\s+line\.(\S+)', s)
        if m:
            sw_states[m.group(2)] = m.group(1)
    return sw_states

def classify_switch(name, state):
    """
    Classify by switch state first, then by name pattern.
    
    """
    
    n = name.lower()

    if state == 'open':
        return 'N.O. Tie Switch'
    
    if n.startswith('hvmv') or n.startswith('2002200'):
        return 'Substation Breaker'
    
    der_patterns = ['dg', 'ln2001', 'ln2000', 'ln1047pv', 'ln5001chp']
    if any(n.startswith(p) for p in der_patterns):
        return 'DER / Microgrid Switch'
    
    if '48332' in n:
        return 'Customer Connection Switch'
    
    return 'Feeder Sectionalizing Switch'

def get_all_switches(content, busxy, sw_states, feeder_assign = None):
    """
    Parsing every switch element from the DSS file and returning a list of
    dictionaries, one per switch, with classification, coordinates, and feeder label (if available).

    """

    switches = []

    for m in re.finditer(
        r'new Line\.(\S+)[^\n]*switch=y[^\n]*', content, re.IGNORECASE):
        line = m.group(0)
        name = m.group(1)

        ph = re.search(r'phases=(\d)', line)
        b1 = re.search(r'bus1=(\S+?)[\s.]', line)
        b2 = re.search(r'bus2=(\S+?)[\s.]', line)
        b1n = b1.group(1) if b1 else ''
        b2n = b2.group(1) if b2 else ''

        state    = sw_states.get(name.lower(), 'close')
        category = classify_switch(name, state)
        coord = busxy.get(b1n) or busxy.get(b2n)

        feeder = 'unknown'
        if feeder_assign:
            feeder = feeder_assign.get(b1n, feeder_assign.get(b2n, 'Unknown'))
 
        switches.append({
            'switch_name': name,
            'category'   : category,
            'phases'     : int(ph.group(1)) if ph else 0,
            'phase_type' : '3-phase' if ph and int(ph.group(1)) >= 3 else '1-phase',
            'state'      : state.upper(),
            'bus1'       : b1n,
            'bus2'       : b2n,
            'longitude'  : coord[0] if coord else None,
            'latitude'   : coord[1] if coord else None,
            'feeder'     : feeder,
        })
 
    return switches

# =============================================================================
# PLOTTING — shared single-category map function
# =============================================================================
 
def plot_switch_category(switches, category, color, marker,
                         title, out_filename, feeder_lines=None,
                         busxy=None):
    """
    Generate a single map showing only one switch category,
    with all other switches as faint grey context points.
 
    Parameters
    ----------
    switches      : list of switch dicts (from get_all_switches)
    category      : str — which category to highlight
    color         : str — hex colour for this category
    marker        : str — matplotlib marker code
    title         : str — plot title
    out_filename  : str — output PNG filename (saved to OUT_DIR)
    feeder_lines  : dict {'S1':[(c1,c2),...], ...} or None — background lines
    busxy         : dict — needed to plot substation markers
    """
    os.makedirs(OUT_DIR, exist_ok=True)
 
    fig, ax = plt.subplots(figsize=(14, 10))
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FFFFFF")
 
    # Background feeder lines (faint)
    if feeder_lines:
        for label, lines in feeder_lines.items():
            c = FEEDER_COL.get(label, '#666666')
            for (x1, y1), (x2, y2) in lines:
                ax.plot([x1, x2], [y1, y2], color=c, lw=0.4, alpha=0.6, zorder=1)
 
    # Other switches as grey context dots
    for s in switches:
        if s['category'] != category and s['longitude'] is not None:
            ax.scatter([s['longitude']], [s['latitude']],
                      c='#444466', s=10, marker='.', alpha=0.4, zorder=2)
 
    # Target category — split by state
    target = [s for s in switches
              if s['category'] == category and s['longitude'] is not None]
    closed = [(s['longitude'], s['latitude']) for s in target if s['state'] == 'CLOSE']
    opened = [(s['longitude'], s['latitude']) for s in target if s['state'] == 'OPEN']
 
    if closed:
        xs, ys = zip(*closed)
        ax.scatter(xs, ys, c=color, marker=marker, s=85, zorder=6,
                  edgecolors='white', linewidths=0.6,
                  label=f'Normally Closed ({len(closed)})')
    if opened:
        xs, ys = zip(*opened)
        ax.scatter(xs, ys, c='#E74C3C', marker=marker, s=120, zorder=7,
                  edgecolors='white', linewidths=0.8,
                  label=f'Normally Open ({len(opened)})')
 
    # Substations
    if busxy:
        for label, root in SOURCES.items():
            if root in busxy:
                rx, ry = busxy[root]
                ax.scatter([rx], [ry], c='white', s=280, marker='*', zorder=9)
                ax.text(rx + 0.003, ry + 0.004, f'S{label[1]}',
                       color='white', fontsize=12, fontweight='bold', zorder=10)
 
    ax.set_title(title, color="#000000", fontsize=20, fontweight='bold')
    ax.set_xlabel('Longitude', color="#000000", fontsize=15)
    ax.set_ylabel('Latitude',  color="#000000", fontsize=15)
    ax.tick_params(colors="#000000", labelsize=14)
    ax.set_aspect('equal')
    ax.grid(True, alpha=0.12, color='#666666', linestyle='--', linewidth=0.4)
    for spine in ax.spines.values():
        spine.set_edgecolor("#000000")
    ax.legend(loc='lower right', fontsize=12, frameon=True,
             facecolor='#FFFFFF', edgecolor='#000000', labelcolor='#000000')
 
    plt.tight_layout()
    path = os.path.join(OUT_DIR, out_filename)
    plt.savefig(path, dpi=300, bbox_inches='tight', facecolor='#FFFFFF')
    plt.close()
    return path
 
 
def build_feeder_lines(edges, feeder_assign, busxy):
    """
    Build background feeder line segments for plotting.
    Uses the edges list and feeder_assign dict that already exist
    from your build_graph.py pipeline — does not recompute anything.
    """
    feeder_lines = {'S1': [], 'S2': [], 'S3': []}
    for e in edges:
        if e.get('is_switch'):
            continue
        fa = feeder_assign.get(e['bus1'], 'S1')
        c1 = busxy.get(e['bus1'])
        c2 = busxy.get(e['bus2'])
        if c1 and c2:
            feeder_lines.setdefault(fa, []).append((c1, c2))
    return feeder_lines
 
 
def save_csv(switches, category, filename):
    """Save one category's switches to CSV using pandas."""
    import pandas as pd
    df = pd.DataFrame([s for s in switches if s['category'] == category])
    path = os.path.join(OUT_DIR, filename)
    df.to_csv(path, index=False)
    return path, len(df)


    