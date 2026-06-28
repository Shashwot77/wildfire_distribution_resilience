# =============================================================================
# FILE: src/graph/load_data.py
# LOCATION: wildfire_distribution_resilience/src/graph/load_data.py
#
# PURPOSE: Load the three raw inputs needed for graph analysis:
#            1. Bus geographic coordinates  (busxy.dss)
#            2. Line / switch / transformer edges  (base.dss)
#            3. Switch open/close states  (base.dss)
#
# PROJECT: wildfire_distribution_resilience
#          (previously developed under IEEE9500_Graph — now migrated here)
#
# HOW TO USE:
#   from load_data import load_busxy, load_edges, load_switch_states
#   busxy     = load_busxy(r"data\ieee9500\ieee9500_busxy.dss")
#   edges     = load_edges(r"data\ieee9500\ieee9500_base.dss")
#   sw_states = load_switch_states(r"data\ieee9500\ieee9500_base.dss")
# =============================================================================

import re


def load_busxy(path):
    """
    Load bus geographic coordinates from the busxy.dss file.

    File format (comma-separated, no header):
        bus_name, longitude, latitude

    Parameters
    ----------
    path : str — path to ieee9500_busxy.dss

    Returns
    -------
    dict — { bus_name: (longitude, latitude) }
    """
    busxy = {}
    with open(path, 'r') as f:
        for line in f:
            parts = line.strip().split(',')
            if len(parts) == 3:
                try:
                    bus_name  = parts[0].strip()
                    longitude = float(parts[1])
                    latitude  = float(parts[2])
                    busxy[bus_name] = (longitude, latitude)
                except ValueError:
                    # Skip malformed lines (e.g. header rows, blank entries)
                    pass
    return busxy


def load_edges(path):
    """
    Load all electrical edges (lines, switches, transformers) from base.dss.

    Parses every 'new Line.*' and 'new Transformer.*' element and extracts
    bus connections, phase count, length, conductor spacing, and ampacity.

    Parameters
    ----------
    path : str — path to ieee9500_base.dss

    Returns
    -------
    list of dict — each dict represents one edge with keys:
        name, bus1, bus2, etype, phases, length_ft,
        spacing, normamps, is_switch
    """
    with open(path, 'r') as f:
        content = f.read()

    edges = []

    # ── Line elements (includes both regular lines and switches) ─────────────
    # NOTE: regex patterns use NO spaces around '=' — the DSS file format
    # writes 'phases=3' not 'phases = 3'. Spaces around '=' will cause
    # every match to silently fail and return 0.0 / '' for all fields.
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
        is_switch = 'switch=y' in line.lower()

        edges.append({
            'name'      : m.group(1),
            'bus1'      : b1.group(1).split('.')[0],
            'bus2'      : b2.group(1).split('.')[0],
            'etype'     : 'switch' if is_switch else 'line',
            'phases'    : int(ph.group(1))   if ph else 0,
            'length_ft' : float(ln.group(1)) if ln else 0.0,
            'spacing'   : sp.group(1)        if sp else '',
            'normamps'  : float(na.group(1)) if na else 0.0,
            'is_switch' : is_switch,
        })

    # ── Transformer elements ──────────────────────────────────────────────────
    # Transformers span multiple lines in the DSS file (wdg=1 ... wdg=2 ...)
    # so we match the full multi-line block starting with '~' continuation.
    for m in re.finditer(
            r'new Transformer\.(\S+)[^\n]*\n((?:~[^\n]*\n)*)', content):
        block = m.group(0)
        wdgs  = re.findall(r'wdg=(\d)[^\n]*bus=(\S+?)[\s.\n]', block)
        bus_by_winding = {int(w): b.split('.')[0] for w, b in wdgs}

        # Only keep two-winding transformers with both primary and secondary
        if 1 in bus_by_winding and 2 in bus_by_winding:
            edges.append({
                'name'      : m.group(1),
                'bus1'      : bus_by_winding[1],
                'bus2'      : bus_by_winding[2],
                'etype'     : 'transformer',
                'phases'    : 0,        # transformers don't carry a phase-per-edge value here
                'length_ft' : 0.0,      # transformers have no physical span
                'spacing'   : '',
                'normamps'  : 0.0,
                'is_switch' : False,
            })

    return edges


def load_switch_states(path):
    """
    Parse all 'open Line.*' / 'close Line.*' commands from base.dss.

    These commands appear separately from the 'new Line.*' definitions,
    typically near the end of the DSS file, and define which switches
    are normally open (N.O.) vs normally closed (N.C.) in the base case.

    Parameters
    ----------
    path : str — path to ieee9500_base.dss

    Returns
    -------
    dict — { switch_name_lowercase: 'open' or 'close' }
           Switches not mentioned default to 'close' when looked up
           with .get(name, 'close') by the caller.
    """
    with open(path, 'r') as f:
        content = f.read()

    sw_states = {}
    for line in content.split('\n'):
        stripped = line.strip().lower()
        match = re.match(r'(open|close)\s+line\.(\S+)\s+', stripped)
        if match:
            command     = match.group(1)   # 'open' or 'close'
            switch_name = match.group(2)
            sw_states[switch_name] = command

    return sw_states


# =============================================================================

# =============================================================================

if __name__ == '__main__':

    BASE_DSS  = r"data\ieee9500\ieee9500_base.dss"
    BUSXY_DSS = r"data\ieee9500\ieee9500_busxy.dss"

    print("=" * 60)
    print("load_data.py — self test")
    print("=" * 60)

    busxy = load_busxy(BUSXY_DSS)
    print(f"\n  Buses with coordinates : {len(busxy)}")

    edges = load_edges(BASE_DSS)
    print(f"  Total edges parsed     : {len(edges)}")

    n_lines  = sum(1 for e in edges if e['etype'] == 'line')
    n_sw     = sum(1 for e in edges if e['etype'] == 'switch')
    n_xfmr   = sum(1 for e in edges if e['etype'] == 'transformer')
    print(f"    Lines        : {n_lines}")
    print(f"    Switches     : {n_sw}")
    print(f"    Transformers : {n_xfmr}")

    sw_states = load_switch_states(BASE_DSS)
    n_open  = sum(1 for v in sw_states.values() if v == 'open')
    n_close = sum(1 for v in sw_states.values() if v == 'close')
    print(f"\n  Switch states loaded    : {len(sw_states)}")
    print(f"    Normally OPEN  (N.O.) : {n_open}")
    print(f"    Normally CLOSED(N.C.) : {n_close}")

    if len(busxy) == 5294 and len(edges) >= 5300 and n_open == 11:
        print("\n  [OK] All counts match expected IEEE 9500 values.")
    else:
        print("\n  [CHECK] Counts differ from expected IEEE 9500 values —"
              " verify your DSS files are correct.")