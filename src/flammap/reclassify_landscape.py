"""  

For the reclassification of fuel model (band 4), canopy cover (band 5), 
canopy height/stand height (band 6), and canopy base height (band 7)

This script also merge all the bands (changed and unchanged) as a final GEOTIFF file.

"""

import os
import shutil
import numpy as np
import rasterio

BAND_DIR = r"C:\Users\C838122713\Desktop\Research\Project\wildfire_distribution_resilience\data\FlamMap\Landscape Output"
OUT_DIR = r"C:\Users\C838122713\Desktop\Research\Project\wildfire_distribution_resilience\data\FlamMap\Bands_modified"

#======================================================================================================
# RECLASSIFICATION RULES
#======================================================================================================

# Fuel model replacement rules (Scott and Burgan FBFM40 codes)
#
#   NB91 = Urban/developed    code 91  → replace with GR2 (102)
#   NB92 = Snow/ice           code 92  → replace with GR2 (102)
#   NB93 = Agriculture        code 93  → replace with GR3 (108)
#   NB99 = Bare/sparse        code 99  → replace with GR1 (101)
#   NB98 = Water              code 98  → NOT replaced (stays non-burnable)
#
#   GR1 = Short sparse dry climate grass  (low fire behaviour)
#   GR2 = Low load dry climate grass      (moderate fire behaviour)
#   GR3 = Low load very coarse grass      (moderate fire behaviour)

FUEL_RECLASS = {
    91:102,
    92:102,
    93:108,
    99:101,
}

# Canopy cover (percent, 0-100)
COVER_FOR_RECLASSED = 10        # cover assigned to pixels reclassified from NB
COVER_MIN_BURNABLE  = 15        # minimum floor for existing burnable pixels

CBH_FOR_RECLASSED = 3           # CBH stored as *10

HEIGHT_FOR_RECLASSED = 10       # height stored as *10

#======================================================================================================
# HELPER FUNCTION
#======================================================================================================

def reclassify(arr, rules):
    """
    replace pixel values in a numpy array according to a rule dictionary.
    {old_value --> new_value}
    pixels not listed in rules are left completely unchanged.

    """

    result = arr.copy()
    for old_value, new_value in rules.items():
        result[arr == old_value] = new_value
    return result

#======================================================================================================
# SETUP
#======================================================================================================

os.makedirs(OUT_DIR, exist_ok=True)     # create the output folder if does not already exist

print("=" * 60)
print("Landscape Reclassification for FlamMap")
print("=" * 60)
print(f"\nInput  folder : {BAND_DIR}")
print(f"Output folder : {OUT_DIR}")

if not os.path.exists(BAND_DIR):
    print("\nERROR: Input folder not found.")
    print(f" Expected: {BAND_DIR}")
    print(" Make sure you have extracted the LCP bands first.")
    exit(1)

# ====================================================================================================
# STEP 1: RECLASSIFY FUEL MODEL (Band 4)
# ====================================================================================================

print("\n[1] Reclassifying fuel model ...")


fuel_src = os.path.join(BAND_DIR, "fuel_model.tif")
fuel_dst = os.path.join(OUT_DIR,   "fuel_model_new.tif")

with rasterio.open(fuel_src) as src:
    profile = src.profile.copy()        # copied version
    fuel = src.read(1).astype(np.int16) # reading band 1 (i.e., fule mode of band 4), convert to 16-bit integer

was_nonburnable = np.isin(fuel, list(FUEL_RECLASS.keys()))

fuel_new = reclassify(fuel, FUEL_RECLASS)

n_changed = was_nonburnable.sum()
total     = fuel.size
print(f"  Changed {n_changed:,} pixels ({n_changed / total * 100:.1f}% of landscape)")
print(f"  Water pixels kept as non-burnable (NB98): {(fuel_new == 98).sum():,}")


# Write the modified fuel array to a new file

with rasterio.open(fuel_dst, "w", **profile) as dst:
    dst.write(fuel_new, 1)
 
print(f"  Saved -> {fuel_dst}")

#======================================================================================================
# RECLASSIFY CANOPY COVER (Band 5)
#======================================================================================================

print("\n[2] Reclassifying canopy cover ...")

cov_src = os.path.join(BAND_DIR, "canopy_cover.tif")
cov_dst = os.path.join(OUT_DIR,   "canopy_cover_new.tif")

with rasterio.open(cov_src) as src:
    profile_cov = src.profile.copy()
    cover       = src.read(1).astype(np.int16)

cover_new = cover.copy()

# Rule 1: Pixels that were non-burnable -> assign sparse grass cover
cover_new[was_nonburnable] = COVER_FOR_RECLASSED

# Rule 2: Existing burnable pixels with zero cover -> set minimum
# FlamMap raises warnings for burnable pixels with 0% canopy cover
burnable_zero = (~was_nonburnable) & (cover == 0) & (fuel_new != 98)
cover_new[burnable_zero] = COVER_MIN_BURNABLE

# Clamp values to the valid range 0-100
cover_new = np.clip(cover_new, 0, 100).astype(np.int16)

print(f"  Mean cover original : {cover.mean():.1f}%")
print(f"  Mean cover modified : {cover_new.mean():.1f}%")

# Write the modified canopy cover array to a new file
with rasterio.open(cov_dst, "w", **profile_cov) as dst:
    dst.write(cover_new, 1)

print(f"  Saved -> {cov_dst}")

#======================================================================================================
# RECLASSIFY CANOPY HEIGHT / STAND HEIGHT (Band 6)
#======================================================================================================

print("\n[3] Reclassifying canopy height ...")

ht_src = os.path.join(BAND_DIR, "canopy_height.tif")
ht_dst = os.path.join(OUT_DIR,   "canopy_height_new.tif")

with rasterio.open(ht_src) as src:
    profile_ht = src.profile.copy()
    height     = src.read(1).astype(np.int16)

height_new = height.copy()

# For reclassified pixels:
#   If original height > HEIGHT_FOR_RECLASSED → keep original (e.g. orchards)
#   If original height <= HEIGHT_FOR_RECLASSED → set to minimum grass height
# This prevents downgrading legitimate tall vegetation to 1.0 m grass
height_new[was_nonburnable] = np.where(
    height[was_nonburnable] > HEIGHT_FOR_RECLASSED,
    height[was_nonburnable],      # keep original — taller than grass minimum
    HEIGHT_FOR_RECLASSED          # assign minimum — shorter than grass minimum
)

# Check how many pixels were actually taller than the grass minimum
n_kept_tall = (height[was_nonburnable] > HEIGHT_FOR_RECLASSED).sum()
n_raised    = (height[was_nonburnable] <= HEIGHT_FOR_RECLASSED).sum()
print(f"  Reclassified pixels kept at original height : {n_kept_tall:,}")
print(f"  Reclassified pixels raised to {HEIGHT_FOR_RECLASSED} (= {HEIGHT_FOR_RECLASSED/10:.1f}m) : {n_raised:,}")

# Existing burnable pixels with zero height → set minimum
ht_zero = (~was_nonburnable) & (height == 0) & (fuel_new != 98)
height_new[ht_zero] = HEIGHT_FOR_RECLASSED
print(f"  Existing burnable zero-height pixels fixed  : {ht_zero.sum():,}")

height_new = np.clip(height_new, 0, 32767).astype(np.int16)

with rasterio.open(ht_dst, "w", **profile_ht) as dst:
    dst.write(height_new, 1)

print(f"  Saved -> {ht_dst}")

#======================================================================================================
# RECLASSIFY CANOPY BASE HEIGHT (Band 7)
#======================================================================================================

print("\n[4] Reclassifying canopy base height ...")
print(f"  Setting reclassified pixels to {CBH_FOR_RECLASSED} "
      f"= {CBH_FOR_RECLASSED / 10:.1f} metres")
 
cbh_src = os.path.join(BAND_DIR, "canopy_base_height.tif")
cbh_dst = os.path.join(OUT_DIR,   "canopy_base_height_new.tif")
 
with rasterio.open(cbh_src) as src:
    profile_cbh = src.profile.copy()
    cbh         = src.read(1).astype(np.int16)
 
cbh_new = cbh.copy()
cbh_new[was_nonburnable] = CBH_FOR_RECLASSED
cbh_new = np.clip(cbh_new, 0, 32767).astype(np.int16)
 
with rasterio.open(cbh_dst, "w", **profile_cbh) as dst:
    dst.write(cbh_new, 1)
 
print(f"  Saved -> {cbh_dst}")

#======================================================================================================
# COPY UNCHANGED BANDS (1, 2, 3, 8)
#======================================================================================================

print("\n[5] Copying unchanged bands ...")
 
unchanged_bands = [
    "elevation",            # band 1
    "slope",                # band 2
    "aspect",               # band 3
    "canopy_bulk_density",  # band 8
]
 
for band in unchanged_bands:
    src_path = os.path.join(BAND_DIR, f"{band}.tif")
    dst_path = os.path.join(OUT_DIR,   f"{band}.tif")
    shutil.copy2(src_path, dst_path)
    print(f"  Copied {band}.tif")

#======================================================================================================
# REASSEMBLE ALL 8 BANDS INTO FINAL GEOTIFF
#======================================================================================================

print("\n[6] Reassembling all 8 bands into landscape_modified.tif ...")
 
# Save the final file one level up from OUT_DIR
final_tif = os.path.join(
    os.path.dirname(OUT_DIR),
    "landscape_modified.tif"
)
 
# Band order MUST match the FlamMap LCP standard exactly
ordered_files = [
    os.path.join(OUT_DIR, "elevation.tif"),              # band 1 — unchanged
    os.path.join(OUT_DIR, "slope.tif"),                  # band 2 — unchanged
    os.path.join(OUT_DIR, "aspect.tif"),                 # band 3 — unchanged
    os.path.join(OUT_DIR, "fuel_model_new.tif"),         # band 4 — modified
    os.path.join(OUT_DIR, "canopy_cover_new.tif"),       # band 5 — modified
    os.path.join(OUT_DIR, "canopy_height_new.tif"),      # band 6 — modified
    os.path.join(OUT_DIR, "canopy_base_height_new.tif"), # band 7 — modified
    os.path.join(OUT_DIR, "canopy_bulk_density.tif"),    # band 8 — unchanged
]
 
band_labels = [
    "elevation", "slope", "aspect", "fuel_model",
    "canopy_cover", "canopy_height", "canopy_base_height",
    "canopy_bulk_density"
]
 
# Read the first band to get the spatial metadata for the output file
with rasterio.open(ordered_files[0]) as ref:
    out_profile = ref.profile.copy()
 
# Update profile: 8 bands, 16-bit integer
out_profile.update(count=8, dtype="int16")
 
# Write all 8 bands into the final file
with rasterio.open(final_tif, "w", **out_profile) as dst:
    for i, fpath in enumerate(ordered_files, start=1):
        with rasterio.open(fpath) as src:
            dst.write(src.read(1).astype(np.int16), i)
        print(f"  Written band {i}: {band_labels[i - 1]}")
 
print(f"\n  Final file -> {final_tif}")
 
# =============================================================================
# SUMMARY
# =============================================================================
 
print("\n" + "=" * 60)
print("DONE")
print("=" * 60)
print("\nModified bands saved to:")
print(f"  {OUT_DIR}")
print("\nFinal landscape file:")
print("  {final_tif}")
print("\nNext steps in FlamMap:")
print("  Landscape -> Generate New Landscape")
print("  Load each band file from the modified bands folder")
print("  OR load landscape_modified.tif directly")
print("  Save as: landscape_modified.lcp")
