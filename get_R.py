import re
import logging
from typing import Tuple
import geopandas as gpd
import numpy as np
from owslib.wms import WebMapService

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

def factorR_wms(gdf: gpd.GeoDataFrame, debug: bool = False) -> Tuple[gpd.GeoDataFrame, float]:
    """
    Calcula un único valor de Factor R para todo el GeoDataFrame
    basado en el centroide de la unión de todas sus geometrías.

    Args:
        gdf: GeoDataFrame con las geometrías a analizar
        debug: Si True, activa logging a nivel DEBUG

    Returns:
        Tuple con el GeoDataFrame actualizado y el valor de Factor R

    Raises:
        ValueError: Si el GeoDataFrame no tiene CRS definido
    """
    if debug:
        logger.setLevel(logging.DEBUG)

    logger.info("Iniciando cálculo de Factor R mediante WMS")
    logger.debug(f"GeoDataFrame shape: {gdf.shape}")
    logger.debug(f"GeoDataFrame CRS: {gdf.crs}")

    if gdf.crs is None:
        logger.error("El GeoDataFrame no tiene CRS definido")
        raise ValueError("El GeoDataFrame no tiene CRS definido.")

    wms_url = "https://wms.mapama.gob.es/sig/Agricultura/CaractAgroClimaticas/wms.aspx"
    layer_name = "Factor R"
    wms_crs = "EPSG:25830"

    logger.info(f"Conectando al servicio WMS: {wms_url}")
    logger.debug(f"Layer: {layer_name}, CRS objetivo: {wms_crs}")

    try:
        wms = WebMapService(wms_url, version="1.3.0")
        logger.info("Conexión WMS establecida exitosamente")
        logger.debug(f"Capas disponibles: {list(wms.contents.keys())}")
    except Exception as e:
        logger.error(f"Error al conectar con el servicio WMS: {e}", exc_info=debug)
        raise

    logger.info("Calculando centroide global de las geometrías")
    try:
        original_crs = gdf.crs
        logger.debug(f"Reproyectando de {original_crs} a {wms_crs}")

        combined_geom = gdf.to_crs(wms_crs).unary_union
        centroid = combined_geom.centroid
        x, y = centroid.x, centroid.y

        logger.info(f"Centroide calculado: X={x:.2f}, Y={y:.2f} ({wms_crs})")
        logger.debug(f"Área combinada: {combined_geom.area:.2f} m²")
    except Exception as e:
        logger.error(f"Error al calcular centroide: {e}", exc_info=debug)
        raise

    bbox = (x - 50, y - 50, x + 50, y + 50)
    size = (101, 101)
    pixel = (50, 50)

    logger.debug(f"Parámetros de consulta WMS:")
    logger.debug(f"  - BBox: {bbox}")
    logger.debug(f"  - Size: {size}")
    logger.debug(f"  - Pixel: {pixel}")

    factor_r_final = np.nan

    try:
        logger.info("Realizando petición GetFeatureInfo al WMS")
        response = wms.getfeatureinfo(
            layers=[layer_name],
            srs=wms_crs,
            bbox=bbox,
            size=size,
            format="image/png",
            query_layers=[layer_name],
            info_format="text/html",
            xy=pixel
        )

        logger.debug("Respuesta WMS recibida, decodificando contenido HTML")
        html_content = response.read().decode("utf-8", errors="replace")

        if debug:
            logger.debug(f"Contenido HTML (primeros 500 caracteres): {html_content[:500]}")

        logger.debug("Extrayendo valor numérico mediante expresión regular")
        match = re.search(r'class="textogris11"[^>]*>([\d,.]+)', html_content)

        if match:
            val_str = match.group(1)
            factor_r_final = float(val_str.replace(',', '.'))
            logger.info(f"✓ Factor R extraído exitosamente: {factor_r_final}")
            logger.debug(f"Valor original en HTML: '{val_str}'")
        else:
            logger.warning("No se encontró el valor numérico en la respuesta HTML")
            logger.debug("Intentando patrones alternativos de búsqueda")

            alt_match = re.search(r'([\d,.]+)', html_content)
            if alt_match:
                val_str = alt_match.group(1)
                factor_r_final = float(val_str.replace(',', '.'))
                logger.info(f"✓ Factor R extraído con patrón alternativo: {factor_r_final}")
            else:
                logger.error("No se pudo extraer ningún valor numérico de la respuesta")

    except Exception as e:
        logger.error(f"Error al consultar el WMS: {e}", exc_info=debug)
        logger.debug(f"Tipo de error: {type(e).__name__}")

    logger.info(f"Asignando Factor R ({factor_r_final}) a todas las filas del GeoDataFrame")
    result = gdf.copy()
    result['factor_r'] = factor_r_final

    logger.info(f"Proceso completado. Filas procesadas: {len(result)}")
    logger.debug(f"Columnas resultantes: {result.columns.tolist()}")

    return result, factor_r_final