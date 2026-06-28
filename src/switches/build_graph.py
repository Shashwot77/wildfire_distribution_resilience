# =============================================================================
# FILE: src/graph/build_graph.py
# LOCATION: wildfire_distribution_resilience/src/graph/build_graph.py
#
# PURPOSE: Build the adjacency list from raw edges (removing open tie
#          switches), and assign every bus to its nearest substation
#          feeder (S1, S2, or S3) using a distance BFS.
#
# PROJECT: wildfire_distribution_resilience
#          (previously developed under IEEE9500_Graph — now migrated here)
#
# HOW TO USE:
#   from load_data   import load_busxy, load_edges, load_switch_states
#   from build_graph import build_adjacency, assign_feeders
#
#   edges     = load_edges(BASE_DSS)
#   sw_states = load_switch_states(BASE_DSS)
#   adj, tie_switches = build_adjacency(edges, sw_states)
#
#   SOURCES = {'S1': 'hvmv11sub1_lsb', 'S2': 'hvmv11sub2_lsb', 'S3': 'hvmv11sub3_lsb'}
#   feeder_assign, dist = assign_feeders(SOURCES, adj)
# =============================================================================

from collections import defaultdict, deque


def build_adjacency(edges, sw_states):
    """
    Build an undirected adjacency list from the edge list, excluding
    any switch that is normally open (N.O.) in the base case.

    This is what physically separates the three feeders at the
    12.47 kV distribution level — open tie switches are never added
    to the adjacency list, so BFS cannot cross between feeders through
    them. (The 69 kV sub-transmission ring still connects all three
    substations through closed line segments — that boundary is
    enforced separately by the feeder filter in the BFS tree-building
    step, not here.)

    Parameters
    ----------
    edges     : list of dict — output of load_data.load_edges()
    sw_states : dict — output of load_data.load_switch_states()
                { switch_name_lowercase: 'open' or 'close' }

    Returns
    -------
    adj          : dict — { bus_name: [(neighbour_bus, edge_dict), ...] }
    tie_switches : list of dict — the edges that were excluded because
                   they are normally open (useful for restoration analysis)
    """
    adj = defaultdict(list)
    tie_switches = []

    for e in edges:
        if e['is_switch']:
            state = sw_states.get(e['name'].lower(), 'close')
            if state == 'open':
                tie_switches.append(e)
                continue   # N.O. switch — do NOT add to the graph

        # Undirected edge — add both directions
        adj[e['bus1']].append((e['bus2'], e))
        adj[e['bus2']].append((e['bus1'], e))

    return adj, tie_switches


def assign_feeders(SOURCES, adj):
    """
    Assign every bus in the network to its nearest substation feeder
    using a hop-count distance BFS run from all three substations.

    This is the "distance race" — for every bus, BFS measures the
    number of hops from each substation root. The substation with the
    fewest hops wins and claims that bus. Because the 69 kV ring is
    still present in `adj` (only the 12.47 kV tie switches were
    removed in build_adjacency), this BFS can travel through it, but
    the extra hops required to do so make the correct substation
    unambiguously closer in virtually every case.

    Parameters
    ----------
    SOURCES : dict — { 'S1': root_bus_name, 'S2': ..., 'S3': ... }
    adj     : dict — output of build_adjacency()

    Returns
    -------
    feeder_assign : dict — { bus_name: 'S1' / 'S2' / 'S3' }
    dist          : dict — { 'S1': {bus_name: hop_count}, 'S2': {...}, 'S3': {...} }
                    (kept for diagnostics / debugging — not needed after
                    feeder_assign is built)
    """
    dist = {}

    for label, root in SOURCES.items():
        d = {}
        q = deque([(root, 0)])
        while q:
            bus, depth = q.popleft()
            if bus in d:
                continue
            d[bus] = depth
            for neighbour, _ in adj[bus]:
                if neighbour not in d:
                    q.append((neighbour, depth + 1))
        dist[label] = d

    # Union of every bus reached by ANY of the three substations
    all_buses = set()
    for d in dist.values():
        all_buses |= set(d.keys())

    # For each bus, pick the substation with the smallest hop count.
    # .get(bus, 99999) means a substation that never reached this bus
    # effectively has infinite distance and can never win.
    feeder_assign = {}
    for bus in all_buses:
        feeder_assign[bus] = min(
            SOURCES,
            key=lambda s: dist[s].get(bus, 99999)
        )

    return feeder_assign, dist


def get_bus_prefix(bus_name):
    """
    Return the single-letter bus type prefix (e, m, l, x, s, sx, n, p, d, h, r)
    from a bus name. Falls back to 'NUM' if the name starts with a digit.

    Used throughout the project to classify bus roles:
        e  = feeder exit
        m  = MV junction (backbone pole)
        l  = lateral tap
        x  = service transformer secondary
        s  = service point
        sx = customer meter
        n  = intermediate node (regulator/capacitor mid-line)
        p  = pole device node
        d  = switch terminal
        h  = high-voltage (69 kV) bus
        r  = regulator bus
    """
    return bus_name[0] if bus_name[0].isalpha() else 'NUM'


def get_bus_voltage(prefix):
    """
    Return the nominal voltage level string for a given bus prefix.

    Used for filtering and CSV annotation throughout the project.
    """
    if prefix in ('x', 's', 'sx'):
        return '120/240 V'
    if prefix == 'h':
        return '69/115 kV'
    return '12.47 kV'


def get_line_type(spacing):
    """
    Classify a conductor spacing template string into a simplified
    line type category: '3ph_overhead', '1ph_overhead',
    'underground', or 'other'.

    Used by pole_placement.py to determine whether n-bus and p-bus
    nodes sit on overhead poles (eligible for pole placement) or
    underground conductors (not eligible).
    """
    if not spacing:
        return 'other'
    if 'axnj' in spacing:
        return 'underground'
    if spacing.startswith('3ph'):
        return '3ph_overhead'
    if spacing.startswith('1ph') or spacing.startswith('2ph'):
        return '1ph_overhead'
    return 'other'


# =============================================================================

# =============================================================================

if __name__ == '__main__':

    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))

    from load_data import load_busxy, load_edges, load_switch_states

    BASE_DSS  = r"data\ieee9500\ieee9500_base.dss"
    BUSXY_DSS = r"data\ieee9500\ieee9500_busxy.dss"

    print("=" * 60)
    print("build_graph.py — self test")
    print("=" * 60)

    print("\n[1] Loading data ...")
    busxy     = load_busxy(BUSXY_DSS)
    edges     = load_edges(BASE_DSS)
    sw_states = load_switch_states(BASE_DSS)
    print(f"  Buses: {len(busxy)}  Edges: {len(edges)}")

    print("\n[2] Building adjacency list ...")
    adj, tie_switches = build_adjacency(edges, sw_states)
    print(f"  Unique buses in graph     : {len(adj)}")
    print(f"  Open tie switches removed : {len(tie_switches)}")
    for e in tie_switches:
        print(f"    {e['name']:<30} {e['bus1']} <-> {e['bus2']}")

    print("\n[3] Assigning feeders ...")
    SOURCES = {
        'S1': 'hvmv11sub1_lsb',
        'S2': 'hvmv11sub2_lsb',
        'S3': 'hvmv11sub3_lsb',
    }
    feeder_assign, dist = assign_feeders(SOURCES, adj)

    for label in SOURCES:
        count = sum(1 for v in feeder_assign.values() if v == label)
        max_depth = max(dist[label].values()) if dist[label] else 0
        print(f"  {label}: {count} buses reached (max depth in distance BFS = {max_depth})")

    expected_total = 5294
    actual_total   = len(feeder_assign)
    if actual_total == expected_total and len(tie_switches) == 11:
        print(f"\n  [OK] {actual_total} buses assigned, 11 tie switches removed —"
              f" matches expected IEEE 9500 values.")
    else:
        print(f"\n  [CHECK] {actual_total} buses assigned, "
              f"{len(tie_switches)} tie switches removed — "
              f"verify your DSS files if this differs from expectations.")