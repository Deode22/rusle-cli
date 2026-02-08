# testing/test_versions.py
import os
import pyproj

print("pyproj:", pyproj.__version__)
print("pyproj data dir:", pyproj.datadir.get_data_dir())

try:
    import rasterio
    print("rasterio:", rasterio.__version__)
    print("GDAL:", rasterio.__gdal_version__)
except Exception as e:
    print("rasterio import error:", e)

try:
    from pyproj import proj_version_str
    print("PROJ (from pyproj):", proj_version_str)
except Exception as e:
    print("proj_version_str error:", e)