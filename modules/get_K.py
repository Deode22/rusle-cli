'''
Función para obtener el raster K de williams
'''

import re
import logging
import requests
import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.enums import Resampling
from rasterio.warp import reproject, calculate_default_transform
import geopandas as gpd
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

WCS_VERSION = "2.0.1"

PROP_TO_MAP = {
    "clay": "https://maps.isric.org/mapserv?map=/map/clay.map",
    "sand": "https://maps.isric.org/mapserv?map=/map/sand.map",
    "silt": "https://maps.isric.org/mapserv?map=/map/silt.map",
    "soc": "https://maps.isric.org/mapserv?map=/map/soc.map",
}

def get_session_with_retries(retries=5, backoff_factor=1.0, status_forcelist=(500, 502, 503, 504)):
    session = requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def get_capabilities_xml(prop: str, max_attempts=3) -> str:
    logger.debug(f"Obteniendo capabilities XML para propiedad: {prop}")
    url = PROP_TO_MAP[prop]
    params = {"service": "WCS", "request": "GetCapabilities", "version": WCS_VERSION}

    session = get_session_with_retries()

    for attempt in range(max_attempts):
        try:
            logger.info(f"Intento {attempt + 1}/{max_attempts} para obtener capabilities de {prop}...")
            r = session.get(url, params=params, timeout=120)
            r.raise_for_status()
            logger.debug(f"Capabilities XML obtenido exitosamente para {prop}")
            return r.text
        except requests.exceptions.Timeout as e:
            logger.warning(f"Timeout en intento {attempt + 1}/{max_attempts} para {prop}")
            if attempt < max_attempts - 1:
                wait_time = (2 ** attempt) * 5
                logger.info(f"Esperando {wait_time} segundos antes de reintentar...")
                time.sleep(wait_time)
            else:
                logger.error(f"Error al obtener capabilities para {prop} después de {max_attempts} intentos: {e}")
                raise
        except Exception as e:
            logger.error(f"Error al obtener capabilities para {prop}: {e}")
            raise

def find_coverage_id(cap_xml: str, prop: str, depth: str, stat: str) -> str:
    """
    Busca coverageId tipo: 'clay_0-5cm_mean' o 'clay_0-5cm_Q0.5'
    """
    target = f"{prop}_{depth}_{stat}"
    logger.debug(f"Buscando coverageId: {target}")
    ids = re.findall(r"<[^>]*CoverageId[^>]*>\s*([^<\s]+)\s*</", cap_xml)
    if target in ids:
        logger.debug(f"CoverageId encontrado: {target}")
        return target

    cand = [i for i in ids if i.lower() == target.lower()]
    if cand:
        logger.debug(f"CoverageId encontrado (case-insensitive): {cand[0]}")
        return cand[0]

    logger.error(f"No se encontró coverageId '{target}'")
    raise ValueError(
        f"No encontré coverageId '{target}'. "
        f"Ejemplos disponibles: {ids[:10]} ... (total {len(ids)})"
    )

def download_wcs_array(prop: str, coverage_id: str, bbox4326, max_attempts=3):
    """
    Descarga GeoTIFF vía WCS y devuelve (array, profile) en memoria.
    bbox4326 = (minLon, minLat, maxLon, maxLat)
    """
    minx, miny, maxx, maxy = bbox4326
    logger.info(f"Descargando {prop} desde WCS (coverageId: {coverage_id})")
    logger.debug(f"  BBox: {bbox4326}")

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

    session = get_session_with_retries()

    for attempt in range(max_attempts):
        try:
            logger.info(f"Intento {attempt + 1}/{max_attempts} para descargar {prop}...")
            r = session.get(base, params=params, timeout=300)
            r.raise_for_status()
            logger.debug(f"Respuesta WCS recibida: {len(r.content)} bytes")
            break
        except requests.exceptions.Timeout as e:
            logger.warning(f"Timeout en intento {attempt + 1}/{max_attempts} para descargar {prop}")
            if attempt < max_attempts - 1:
                wait_time = (2 ** attempt) * 10
                logger.info(f"Esperando {wait_time} segundos antes de reintentar...")
                time.sleep(wait_time)
            else:
                logger.error(f"Error al descargar {prop} después de {max_attempts} intentos: {e}")
                raise
        except Exception as e:
            logger.error(f"Error al descargar {prop}: {e}")
            raise

    with MemoryFile(r.content) as memfile:
        with memfile.open() as ds:
            arr = ds.read(1).astype(np.float32)
            profile = ds.profile
            nodata = ds.nodata
            logger.debug(f"  Shape: {arr.shape}, NoData: {nodata}")

    if nodata is not None:
        arr = np.where(arr == nodata, np.nan, arr)
        valid_pixels = np.sum(np.isfinite(arr))
        logger.debug(f"  Píxeles válidos: {valid_pixels}/{arr.size}")

    logger.info(f"✓ {prop} descargado exitosamente")
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

def williams_k_epic(sand_pct, silt_pct, clay_pct, soc_pct):
    """
    Factor K de Williams (EPIC model - ecuación 2.96).
    
    Args:
        sand_pct, silt_pct, clay_pct: % (0-100)
        soc_pct: % carbono orgánico (0-100)
    
    Returns:
        K en t·h/(MJ·mm) (unidades SI del USLE métrico)
    """
    # Conversión a fracciones
    silt_frac = silt_pct / 100.0
    
    # SN1 = 1 - (sand/100)
    sn1 = 1.0 - (sand_pct / 100.0)
    
    # Término 1: efecto de arena gruesa
    fsand = 0.2 + 0.3 * np.exp(-0.0256 * sand_pct * (1.0 - silt_frac))
    
    # Término 2: relación limo/(limo+arcilla)
    fsl_cl = np.where(
        (clay_pct + silt_pct) > 0,
        (silt_pct / (clay_pct + silt_pct)) ** 0.3,
        0.0
    )
    
    # Término 3: reducción por carbono orgánico (C)
    forgc = 1.0 - (0.25 * soc_pct / (soc_pct + np.exp(3.72 - 2.95 * soc_pct)))
    
    # Término 4: reducción por arenas muy altas (SN1)
    fhisand = 1.0 - (0.7 * sn1 / (sn1 + np.exp(-5.51 + 22.9 * sn1)))
    
    # Factor K final (sin el 0.1317, que es una conversión de unidades opcional)
    K = fsand * fsl_cl * forgc * fhisand
    
    return K

def factor_K_williams(gdf: gpd.GeoDataFrame, depth="0-5cm", stat="mean"):
    """
    Calcula el Factor K (erodibilidad del suelo) usando la fórmula EPIC completa de Williams (1990).

    Args:
        gdf: GeoDataFrame con geometría(s) para definir ROI (bbox).
        depth: profundidad SoilGrids (ej: "0-5cm", "5-15cm", ...).
        stat: estadístico ("mean", "Q0.5", "Q0.05", "Q0.95").

    Returns:
        dict con:
            - 'sand': array (g/kg)
            - 'silt': array (g/kg)
            - 'clay': array (g/kg)
            - 'soc': array (dg/kg) - decagramos por kg
            - 'sand_pct': array (%)
            - 'silt_pct': array (%)
            - 'clay_pct': array (%)
            - 'soc_pct': array (%)
            - 'K': array (t·h/(MJ·mm))
            - 'profile': rasterio profile (metadatos geoespaciales)
    """
    logger.info("=" * 60)
    logger.info("CÁLCULO DEL FACTOR K (ERODIBILIDAD DEL SUELO)")
    logger.info("Método: EPIC - Williams et al. (1990)")
    logger.info("=" * 60)
    logger.info(f"Parámetros: depth={depth}, stat={stat}")

    bbox = gdf_to_bbox4326(gdf)
    print(f"Bbox EPSG:4326: {bbox}")
    logger.debug(f"Bbox calculado: {bbox}")

    logger.info("Identificando coverageIds en SoilGrids...")
    cov = {}
    for i, prop in enumerate(["sand", "silt", "clay", "soc"]):
        if i > 0:
            logger.info("Esperando 3 segundos antes de la siguiente petición...")
            time.sleep(3)
        cap = get_capabilities_xml(prop)
        cov[prop] = find_coverage_id(cap, prop, depth, stat)
        print(f"{prop}: coverageId = {cov[prop]}")
        logger.debug(f"CoverageId para {prop}: {cov[prop]}")

    logger.info("Descargando datos de SoilGrids...")
    sand_arr, sand_prof = download_wcs_array("sand", cov["sand"], bbox)
    time.sleep(2)
    silt_arr, silt_prof = download_wcs_array("silt", cov["silt"], bbox)
    time.sleep(2)
    clay_arr, clay_prof = download_wcs_array("clay", cov["clay"], bbox)
    time.sleep(2)
    soc_arr, soc_prof = download_wcs_array("soc", cov["soc"], bbox)

    def profiles_match(p1, p2):
        return (p1["width"] == p2["width"] and p1["height"] == p2["height"]
                and p1["transform"] == p2["transform"] and p1["crs"] == p2["crs"])

    logger.info("Verificando y alineando grillas...")
    if not profiles_match(silt_prof, sand_prof):
        print("Re-muestreando silt a grilla de sand...")
        logger.debug("Re-muestreando silt a grilla de sand")
        silt_arr = resample_array_to_match(silt_arr, silt_prof, sand_prof)

    if not profiles_match(clay_prof, sand_prof):
        print("Re-muestreando clay a grilla de sand...")
        logger.debug("Re-muestreando clay a grilla de sand")
        clay_arr = resample_array_to_match(clay_arr, clay_prof, sand_prof)

    if not profiles_match(soc_prof, sand_prof):
        print("Re-muestreando soc a grilla de sand...")
        logger.debug("Re-muestreando soc a grilla de sand")
        soc_arr = resample_array_to_match(soc_arr, soc_prof, sand_prof)

    logger.info("Convirtiendo unidades (g/kg → %)...")
    sand_pct = sand_arr / 10.0
    silt_pct = silt_arr / 10.0
    clay_pct = clay_arr / 10.0
    soc_pct = soc_arr / 10.0
    logger.debug(f"Conversión completada. Rango sand: {np.nanmin(sand_pct):.2f}-{np.nanmax(sand_pct):.2f}%")

    logger.info("Validando suma de texturas...")
    total_texture = sand_pct + silt_pct + clay_pct
    valid_texture = np.abs(total_texture - 100.0) < 5.0

    if not np.all(valid_texture[np.isfinite(total_texture)]):
        invalid_count = np.sum(~valid_texture & np.isfinite(total_texture))
        print(f"ADVERTENCIA: {invalid_count} píxeles con suma de texturas != 100% (tolerancia ±5%)")
        print(f"  Rango de suma: {np.nanmin(total_texture):.1f} - {np.nanmax(total_texture):.1f}%")
        logger.warning(f"{invalid_count} píxeles con suma de texturas fuera de rango (±5%). Rango: {np.nanmin(total_texture):.1f}-{np.nanmax(total_texture):.1f}%")
    else:
        logger.debug("Validación de texturas completada: todos los píxeles dentro de tolerancia")

    logger.info("Calculando Factor K con fórmula EPIC completa...")
    logger.debug("  Fórmula: K = fsand × fsl-cl × fhisand × forgc × 0.1317")
    k = williams_k_epic(sand_pct, silt_pct, clay_pct, soc_pct)

    mask = (np.isfinite(sand_pct) & np.isfinite(silt_pct) &
            np.isfinite(clay_pct) & np.isfinite(soc_pct))
    k = np.where(mask, k, np.nan)

    valid_k_pixels = np.sum(np.isfinite(k))
    logger.debug(f"Píxeles válidos con K calculado: {valid_k_pixels}/{k.size}")

    print(f"\nEstadísticas del Factor K:")
    print(f"  K min:  {np.nanmin(k):.4f} t·h/(MJ·mm)")
    print(f"  K mean: {np.nanmean(k):.4f} t·h/(MJ·mm)")
    print(f"  K max:  {np.nanmax(k):.4f} t·h/(MJ·mm)")

    logger.info(f"Estadísticas finales - Factor K: min={np.nanmin(k):.4f}, mean={np.nanmean(k):.4f}, max={np.nanmax(k):.4f} t·h/(MJ·mm)")
    logger.info("✓ Cálculo del Factor K completado exitosamente")
    logger.info("=" * 60)

    return {
        "sand": sand_arr,
        "silt": silt_arr,
        "clay": clay_arr,
        "soc": soc_arr,
        "sand_pct": sand_pct,
        "silt_pct": silt_pct,
        "clay_pct": clay_pct,
        "soc_pct": soc_pct,
        "K": k,
        "profile": sand_prof,
    }


""" # ============ EJEMPLO DE USO ============
if __name__ == "__main__":
    gdf = gpd.read_file('layers/test.gpkg')

    result = factor_K_williams(gdf, depth="0-5cm", stat="mean")

    print(f"\nK shape: {result['K'].shape}")
    print(f"K min/max: {np.nanmin(result['K']):.4f} / {np.nanmax(result['K']):.4f}")
    print(f"K mean: {np.nanmean(result['K']):.4f}")

    print(f"\nSOC mean: {np.nanmean(result['soc_pct']):.2f}%")
    print(f"Sand mean: {np.nanmean(result['sand_pct']):.1f}%")
    print(f"Silt mean: {np.nanmean(result['silt_pct']):.1f}%")
    print(f"Clay mean: {np.nanmean(result['clay_pct']):.1f}%") """
