'''
Función para obtener el raster K de williams
'''

import re
import requests
import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.enums import Resampling
from rasterio.warp import reproject, calculate_default_transform
import geopandas as gpd

WCS_VERSION = "2.0.1"

PROP_TO_MAP = {
    "clay": "https://maps.isric.org/mapserv?map=/map/clay.map",
    "sand": "https://maps.isric.org/mapserv?map=/map/sand.map",
    "silt": "https://maps.isric.org/mapserv?map=/map/silt.map",
}

def get_capabilities_xml(prop: str) -> str:
    url = PROP_TO_MAP[prop]
    params = {"service": "WCS", "request": "GetCapabilities", "version": WCS_VERSION}
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.text

def find_coverage_id(cap_xml: str, prop: str, depth: str, stat: str) -> str:
    """
    Busca coverageId tipo: 'clay_0-5cm_mean' o 'clay_0-5cm_Q0.5'
    """
    target = f"{prop}_{depth}_{stat}"
    ids = re.findall(r"<[^>]*CoverageId[^>]*>\s*([^<\s]+)\s*</", cap_xml)
    if target in ids:
        return target

    cand = [i for i in ids if i.lower() == target.lower()]
    if cand:
        return cand[0]

    raise ValueError(
        f"No encontré coverageId '{target}'. "
        f"Ejemplos disponibles: {ids[:10]} ... (total {len(ids)})"
    )

def download_wcs_array(prop: str, coverage_id: str, bbox4326):
    """
    Descarga GeoTIFF vía WCS y devuelve (array, profile) en memoria.
    bbox4326 = (minLon, minLat, maxLon, maxLat)
    """
    minx, miny, maxx, maxy = bbox4326
    base = PROP_TO_MAP[prop]
    params = {
        "service": "WCS",
        "request": "GetCoverage",
        "version": WCS_VERSION,
        "coverageId": coverage_id,
        "format": "GEOTIFF_INT16",
        "subset": [f"X({minx},{maxx})", f"Y({miny},{maxy})"],
        "subsettingCrs": "http://www.opengis.net/def/crs/EPSG/0/4326",
        "outputCrs": "http://www.opengis.net/def/crs/EPSG/0/4326",
    }
    r = requests.get(base, params=params, timeout=300)
    r.raise_for_status()

    # leer desde memoria
    with MemoryFile(r.content) as memfile:
        with memfile.open() as ds:
            arr = ds.read(1).astype(np.float32)
            profile = ds.profile
            nodata = ds.nodata

    # manejar nodata (típicamente -32768 en INT16)
    if nodata is not None:
        arr = np.where(arr == nodata, np.nan, arr)

    return arr, profile

def resample_array_to_match(src_arr, src_profile, ref_profile):
    """
    Re-muestrea src_arr para que coincida con ref (shape/transform/crs).
    Devuelve array re-muestreado.
    """
    dst = np.empty((ref_profile["height"], ref_profile["width"]), dtype=src_arr.dtype)

    reproject(
        source=src_arr,
        destination=dst,
        src_transform=src_profile["transform"],
        src_crs=src_profile["crs"],
        dst_transform=ref_profile["transform"],
        dst_crs=ref_profile["crs"],
        resampling=Resampling.bilinear,
    )
    return dst

def gdf_to_bbox4326(gdf: gpd.GeoDataFrame):
    """
    Extrae bbox (minLon, minLat, maxLon, maxLat) en EPSG:4326.
    Si gdf no está en 4326, lo reproyecta.
    """
    if gdf.crs is None:
        raise ValueError("GeoDataFrame sin CRS definido. Asigna uno con gdf.set_crs(...)")

    if gdf.crs.to_epsg() != 4326:
        print(f"Reproyectando de {gdf.crs} a EPSG:4326...")
        gdf = gdf.to_crs(epsg=4326)

    bounds = gdf.total_bounds  # (minx, miny, maxx, maxy)
    return tuple(bounds)

def williams_k(sand_pct, silt_pct, clay_pct):
    """
    Factor K de Williams (1975).
    Entradas en % (0-100).
    Salida: K en t·h/(MJ·mm)
    """
    SN1 = 1.0 - (sand_pct / 100.0)

    term1 = 0.2 + 0.3 * np.exp(-0.0256 * sand_pct * (1.0 - (silt_pct / 100.0)))
    term2 = 1.0 - (0.25 * clay_pct / (clay_pct + np.exp(3.72 - 2.95 * clay_pct)))
    term3 = 1.0 - (0.7 * SN1 / (SN1 + np.exp(-5.51 + 22.9 * SN1)))

    return term1 * term2 * term3

def calculate_factor_K_williams(gdf: gpd.GeoDataFrame, depth="0-5cm", stat="mean"):
    """
    Calcula el Factor K (erodibilidad del suelo) usando Williams (1975).

    Args:
        gdf: GeoDataFrame con geometría(s) para definir ROI (bbox).
        depth: profundidad SoilGrids (ej: "0-5cm", "5-15cm", ...).
        stat: estadístico ("mean", "Q0.5", "Q0.05", "Q0.95").

    Returns:
        dict con:
            - 'sand': array (g/kg)
            - 'silt': array (g/kg)
            - 'clay': array (g/kg)
            - 'sand_pct': array (%)
            - 'silt_pct': array (%)
            - 'clay_pct': array (%)
            - 'K': array (t·h/(MJ·mm))
            - 'profile': rasterio profile (metadatos geoespaciales)
    """
    # 1) extraer bbox en EPSG:4326
    bbox = gdf_to_bbox4326(gdf)
    print(f"Bbox EPSG:4326: {bbox}")

    # 2) descubrir coverageIds
    cov = {}
    for prop in ["sand", "silt", "clay"]:
        cap = get_capabilities_xml(prop)
        cov[prop] = find_coverage_id(cap, prop, depth, stat)
        print(f"{prop}: coverageId = {cov[prop]}")

    # 3) descargar arrays en memoria
    sand_arr, sand_prof = download_wcs_array("sand", cov["sand"], bbox)
    silt_arr, silt_prof = download_wcs_array("silt", cov["silt"], bbox)
    clay_arr, clay_prof = download_wcs_array("clay", cov["clay"], bbox)

    # 4) asegurar misma grilla (usar sand como referencia)
    def profiles_match(p1, p2):
        return (p1["width"] == p2["width"] and p1["height"] == p2["height"]
                and p1["transform"] == p2["transform"] and p1["crs"] == p2["crs"])

    if not profiles_match(silt_prof, sand_prof):
        print("Re-muestreando silt a grilla de sand...")
        silt_arr = resample_array_to_match(silt_arr, silt_prof, sand_prof)

    if not profiles_match(clay_prof, sand_prof):
        print("Re-muestreando clay a grilla de sand...")
        clay_arr = resample_array_to_match(clay_arr, clay_prof, sand_prof)

    # 5) convertir g/kg → % (SoilGrids usa g/kg, 0-1000)
    sand_pct = sand_arr / 10.0
    silt_pct = silt_arr / 10.0
    clay_pct = clay_arr / 10.0

    # 6) calcular K
    k = williams_k(sand_pct, silt_pct, clay_pct)

    # máscara nodata
    mask = np.isfinite(sand_pct) & np.isfinite(silt_pct) & np.isfinite(clay_pct)
    k = np.where(mask, k, np.nan)

    return {
        "sand": sand_arr,       # g/kg
        "silt": silt_arr,       # g/kg
        "clay": clay_arr,       # g/kg
        "sand_pct": sand_pct,   # %
        "silt_pct": silt_pct,   # %
        "clay_pct": clay_pct,   # %
        "K": k,                 # t·h/(MJ·mm)
        "profile": sand_prof,   # metadatos raster (CRS, transform, etc.)
    }

'''
# ============ EJEMPLO DE USO ============
if __name__ == "__main__":
    gdf = gpd.read_file('test.gpkg')

    # Calcular K
    result = calculate_factor_K_williams(gdf, depth="0-5cm", stat="mean")

    print(f"\nK shape: {result['K'].shape}")
    print(f"K min/max: {np.nanmin(result['K']):.4f} / {np.nanmax(result['K']):.4f}")
    print(f"K mean: {np.nanmean(result['K']):.4f}")
'''