# =============================================================================
# FILE: config.py
# LOCATION: project root  (wildfire_distribution_resilience/config.py)
# PURPOSE: Central configuration — all file paths in one place.
#          Every other script imports CFG from here instead of
#          hardcoding paths.
#
# SETUP:
#   1. Copy .env.example to .env
#   2. Edit .env with your actual folder paths
#   3. Every script that needs a path does: from config import CFG
# =============================================================================

import os
from pathlib import Path
from dotenv import load_dotenv

# Load the .env file from the project root
# This fills in os.getenv() calls below with your local paths
load_dotenv(Path(__file__).parent / '.env')


class CFG:
    """
    Central configuration class.
    All paths are pathlib.Path objects so you can do:
        CFG.DATA_DIR / 'ieee9500' / 'ieee9500_base.dss'
    instead of string concatenation.
    """

    # Project root = the folder containing this config.py file
    ROOT = Path(__file__).parent

    # ── Main directories ──────────────────────────────────────────────────────
    DATA_DIR   = Path(os.getenv('DATA_DIR',   str(ROOT / 'data')))
    OUTPUT_DIR = Path(os.getenv('OUTPUT_DIR', str(ROOT / 'outputs')))

    # ── IEEE 9500 files ───────────────────────────────────────────────────────
    IEEE9500_BASE  = Path(os.getenv(
        'IEEE9500_BASE',
        str(DATA_DIR / 'ieee9500' / 'ieee9500_base.dss')
    ))
    IEEE9500_BUSXY = Path(os.getenv(
        'IEEE9500_BUSXY',
        str(DATA_DIR / 'ieee9500' / 'ieee9500_busxy.dss')
    ))

    # ── FlamMap / Landscape files ─────────────────────────────────────────────
    LANDSCAPE_ORIGINAL = Path(os.getenv(
        'LANDSCAPE_ORIGINAL',
        str(DATA_DIR / 'landfire' / 'landscape_original.tif')
    ))
    LANDSCAPE_MODIFIED = Path(os.getenv(
        'LANDSCAPE_MODIFIED',
        str(OUTPUT_DIR / 'flammap' / 'landscape_modified.tif')
    ))

    # ── Output sub-directories ────────────────────────────────────────────────
    OUT_BFS     = OUTPUT_DIR / 'bfs_trees'
    OUT_FLAMMAP = OUTPUT_DIR / 'flammap'
    OUT_PINN    = OUTPUT_DIR / 'pinn'
    OUT_POWER   = OUTPUT_DIR / 'power_flow'
    OUT_FIGURES = OUTPUT_DIR / 'figures'


# =============================================================================
# QUICK TEST — run this file directly to verify paths are correct:
#   (.venv) PS> python config.py
# =============================================================================

if __name__ == '__main__':

    print("=" * 55)
    print("config.py — path verification")
    print("=" * 55)

    checks = [
        ('Project root',         CFG.ROOT),
        ('data/ folder',         CFG.DATA_DIR),
        ('outputs/ folder',      CFG.OUTPUT_DIR),
        ('ieee9500_base.dss',    CFG.IEEE9500_BASE),
        ('ieee9500_busxy.dss',   CFG.IEEE9500_BUSXY),
        ('landscape_original',   CFG.LANDSCAPE_ORIGINAL),
    ]

    all_ok = True
    for label, path in checks:
        exists = path.exists()
        status = 'OK' if exists else 'NOT FOUND'
        print(f"  [{status:<9}] {label:<25} {path}")
        if not exists:
            all_ok = False

    if all_ok:
        print("\n  All paths verified.")
    else:
        print("\n  Some paths are missing.")
        print("  Copy .env.example to .env and fill in your real paths.")