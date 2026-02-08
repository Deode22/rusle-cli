"""
Módulo para obtención de NDVI y cálculo del factor C (gestión de cubiertas)
a partir de imágenes Sentinel-2 mediante Copernicus Data Space Ecosystem.

Orientado a zonas forestales, repoblaciones y evaluación de servicios ecosistémicos.
"""

import os
from dotenv import load_dotenv
import requests
import numpy as np
from datetime import datetime, timedelta
from shapely.geometry import mapping
from rasterio.features import geometry_mask
import geopandas as gpd
import rasterio
from io import BytesIO
import logging

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)


def bbox_from_gdf(gdf: gpd.GeoDataFrame):
    """
    Extrae el bounding box en EPSG:4326 a partir del extent del GeoDataFrame.
    
    Parámetros
    ----------
    gdf : gpd.GeoDataFrame
        GeoDataFrame con geometrías del área de estudio.
    
    Retorna
    -------
    bbox : list
        Lista [minx, miny, maxx, maxy] en EPSG:4326.
    gdf_4326 : gpd.GeoDataFrame
        GeoDataFrame reproyectado a EPSG:4326.
    
    Excepciones
    -----------
    ValueError
        Si el GeoDataFrame está vacío, no tiene geometría o no tiene CRS definido.
    """
    logger.debug("Extrayendo bounding box del GeoDataFrame")
    
    if gdf is None or len(gdf) == 0:
        logger.error("El GeoDataFrame está vacío")
        raise ValueError("El GeoDataFrame está vacío.")

    if "geometry" not in gdf.columns:
        logger.error("El GeoDataFrame no tiene columna 'geometry'")
        raise ValueError("El GeoDataFrame no tiene columna 'geometry'.")

    if gdf.crs is None:
        logger.error("El GeoDataFrame no tiene CRS definido")
        raise ValueError("El GeoDataFrame no tiene CRS definido (gdf.crs is None). Asigna uno antes.")

    # Reproyectar si no es EPSG:4326
    epsg = gdf.crs.to_epsg()
    if epsg != 4326:
        logger.debug(f"Reproyectando de EPSG:{epsg} a EPSG:4326")
        gdf = gdf.to_crs(epsg=4326)

    minx, miny, maxx, maxy = gdf.total_bounds
    bbox = [float(minx), float(miny), float(maxx), float(maxy)]
    
    logger.debug(f"Bounding box calculado: {bbox}")
    
    return bbox, gdf


def calcular_factor_C(ndvi_2d, metodo='vanderknijff'):
    """
    Calcula el factor C (gestión de cubiertas) a partir de NDVI.
    
    Para zonas forestales y repoblaciones, se recomienda el método exponencial
    de Van der Knijff et al. (2000), que captura la reducción no lineal de la
    erosión con el incremento de biomasa vegetal.
    
    Parámetros
    ----------
    ndvi_2d : np.ndarray
        Matriz 2D con valores de NDVI en rango [-1, 1].
    metodo : str
        'vanderknijff': Método exponencial (recomendado para zonas forestales).
        'lineal': Fórmula lineal empírica (0.431 - 0.805 * NDVI).
    
    Retorna
    -------
    c_array : np.ndarray
        Factor C en rango [0.001, 1.0].
    
    Referencias
    -----------
    Van der Knijff, J. M., Jones, R. J. A., & Montanarella, L. (2000).
    Soil erosion risk assessment in Europe. EUR 19044 EN.
    """
    logger.info(f"Calculando factor C mediante método: {metodo}")
    
    if metodo == 'vanderknijff':
        # Método exponencial: captura la protección no lineal de la vegetación
        # Especialmente relevante en repoblaciones donde pequeños incrementos
        # iniciales de cobertura reducen drásticamente la erosión
        
        alpha = 2.0
        beta = 1.0
        
        # Limitar NDVI para evitar inestabilidad numérica
        ndvi_safe = np.clip(ndvi_2d, 0.0, 0.95)
        
        logger.debug("Aplicando fórmula exponencial: C = exp(-2 * NDVI / (1 - NDVI))")
        c_array = np.exp(-alpha * (ndvi_safe / (beta - ndvi_safe)))
        
    elif metodo == 'lineal':
        # Método lineal empírico
        # Nota: Puede generar valores negativos en zonas de alta densidad vegetal
        
        logger.debug("Aplicando fórmula lineal: C = 0.431 - 0.805 * NDVI")
        c_array = 0.431 - 0.805 * ndvi_2d
        
    else:
        logger.error(f"Método '{metodo}' no implementado")
        raise ValueError(f"Método '{metodo}' no reconocido. Opciones: 'vanderknijff', 'lineal'")
    
    # Garantizar límites físicos del factor C
    # C = 1.0: Suelo desnudo (máxima erosión)
    # C = 0.001: Cobertura densa (mínima erosión, evita división por cero)
    c_array = np.clip(c_array, 0.001, 1.0)
    
    # Estadísticas para validación
    c_valid = c_array[np.isfinite(c_array)]
    if c_valid.size > 0:
        logger.info(f"Factor C calculado: mean={np.mean(c_valid):.4f}, "
                   f"min={np.min(c_valid):.4f}, max={np.max(c_valid):.4f}")
    else:
        logger.warning("No se calcularon valores válidos de factor C")
    
    return c_array


def dividir_bbox_en_tiles(bbox, num_tiles_x=2, num_tiles_y=2):
    """
    Divide un bounding box en tiles más pequeños para procesamiento por lotes.

    Parámetros
    ----------
    bbox : list
        Lista [minx, miny, maxx, maxy] en EPSG:4326.
    num_tiles_x : int
        Número de divisiones en el eje X (longitud).
    num_tiles_y : int
        Número de divisiones en el eje Y (latitud).

    Retorna
    -------
    tiles : list
        Lista de bounding boxes, cada uno como [minx, miny, maxx, maxy].
    """
    minx, miny, maxx, maxy = bbox

    width = (maxx - minx) / num_tiles_x
    height = (maxy - miny) / num_tiles_y

    tiles = []
    for i in range(num_tiles_y):
        for j in range(num_tiles_x):
            tile_minx = minx + j * width
            tile_miny = miny + i * height
            tile_maxx = tile_minx + width
            tile_maxy = tile_miny + height
            tiles.append([tile_minx, tile_miny, tile_maxx, tile_maxy])

    logger.debug(f"Bbox dividido en {len(tiles)} tiles ({num_tiles_x}x{num_tiles_y})")
    return tiles


def obtener_ndvi_valido(gdf: gpd.GeoDataFrame, dias=90, maxcc=20, width=512, height=512,
                        metodo_c='vanderknijff', client_id=None, client_secret=None,
                        num_tiles_x=1, num_tiles_y=1):
    """
    Obtiene NDVI válido usando Sentinel Hub Process API (Copernicus Data Space Ecosystem)
    y calcula el factor C para modelos de erosión (USLE/RUSLE).

    El proceso incluye:
    1. Autenticación OAuth con Copernicus Data Space
    2. Consulta de imágenes Sentinel-2 L2A con filtro de nubes (procesamiento por tiles)
    3. Cálculo de NDVI con máscara de calidad (SCL)
    4. Recorte al área de estudio (geometrías del GeoDataFrame)
    5. Cálculo del factor C según método seleccionado

    Parámetros
    ----------
    gdf : gpd.GeoDataFrame
        GeoDataFrame con geometrías del área de estudio.
    dias : int
        Ventana temporal hacia atrás desde hoy (días).
    maxcc : int
        Cobertura de nubes máxima permitida (%).
    width : int
        Ancho de la imagen solicitada (píxeles).
    height : int
        Alto de la imagen solicitada (píxeles).
    metodo_c : str
        Método para calcular factor C: 'vanderknijff' (recomendado) o 'lineal'.
    client_id : str, optional
        Client ID de Copernicus Data Space. Si None, debe estar en el código.
    client_secret : str, optional
        Client Secret de Copernicus Data Space. Si None, debe estar en el código.
    num_tiles_x : int
        Número de divisiones en el eje X (longitud) para procesamiento por lotes.
        Usar > 1 para evitar timeouts en áreas grandes.
    num_tiles_y : int
        Número de divisiones en el eje Y (latitud) para procesamiento por lotes.
        Usar > 1 para evitar timeouts en áreas grandes.

    Retorna
    -------
    valid_ndvi : np.ndarray (1D)
        Array con valores válidos de NDVI (sin NaN).
    ndvi_2d : np.ndarray (2D)
        Matriz 2D de NDVI (con NaN fuera del área de estudio).
    c_array : np.ndarray (2D)
        Matriz 2D del factor C.
    stats : dict
        Estadísticas del NDVI y metadatos de la consulta.
    bbox : list
        Bounding box utilizado [minx, miny, maxx, maxy] en EPSG:4326.

    Excepciones
    -----------
    Exception
        Si falla la autenticación o la consulta a Sentinel Hub.

    Referencias
    -----------
    Copernicus Data Space Ecosystem: https://dataspace.copernicus.eu/
    Sentinel Hub Process API: https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Process.html
    """
    logger.info("="*60)
    logger.info("OBTENCIÓN DE NDVI Y CÁLCULO DEL FACTOR C")
    logger.info("="*60)

    if client_id is None:
        CLIENT_ID = os.environ.get("CLIENT_ID")
    else:
        CLIENT_ID = client_id

    if client_secret is None:
        CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
    else:
        CLIENT_SECRET = client_secret

    if not CLIENT_ID or not CLIENT_SECRET or CLIENT_ID == "sh-":
        logger.error("Credenciales de Copernicus Data Space no configuradas")
        raise ValueError("Debe proporcionar client_id y client_secret válidos o configurar las variables de entorno CLIENT_ID y CLIENT_SECRET")
        raise ValueError("Debe proporcionar client_id y client_secret válidos")
    
    # Extraer bounding box del GeoDataFrame
    bbox, gdf_4326 = bbox_from_gdf(gdf)
    logger.info(f"Área de estudio: bbox={bbox}")

    # Dividir en tiles si es necesario
    if num_tiles_x > 1 or num_tiles_y > 1:
        tiles = dividir_bbox_en_tiles(bbox, num_tiles_x, num_tiles_y)
        logger.info(f"Procesando {len(tiles)} tiles para evitar timeouts")
    else:
        tiles = [bbox]

    # Autenticación OAuth
    logger.info("Autenticando con Copernicus Data Space Ecosystem")
    token_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"

    try:
        token_response = requests.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET
            },
            timeout=60
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]
        logger.info("Autenticación exitosa")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error en autenticación: {e}")
        raise Exception(f"Error obteniendo token: {e}")

    # Definir ventana temporal
    today = datetime.utcnow()
    start_date = (today - timedelta(days=dias)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")

    logger.info(f"Ventana temporal: {start_date} a {end_date} ({dias} días)")
    logger.info(f"Cobertura de nubes máxima: {maxcc}%")
    logger.info(f"Resolución solicitada: {width}x{height} píxeles")

    # Almacenamiento de resultados por tile
    ndvi_arrays = []
    transforms = []
    raster_crs_ref = None
    
    # Evalscript para Sentinel-2
    # Calcula NDVI y aplica máscara de calidad (SCL) para filtrar nubes, sombras y nieve
    evalscript = """
    //VERSION=3
    function setup() {
        return {
            input: [{
                bands: ["B04", "B08", "SCL"],
                units: "DN"
            }],
            output: {
                bands: 1,
                sampleType: "FLOAT32"
            }
        };
    }

    function evaluatePixel(sample) {
        // Máscara de calidad SCL (Scene Classification Layer):
        // 3=sombra de nube, 8=nube media, 9=nube alta, 10=cirrus, 11=nieve/hielo
        if ([3, 8, 9, 10, 11].includes(sample.SCL)) {
            return [NaN];
        }
        
        let denom = (sample.B08 + sample.B04);
        if (denom === 0) return [NaN];
        
        let ndvi = (sample.B08 - sample.B04) / denom;
        return [ndvi];
    }
    """
    
    # Payload para Process API
    payload = {
        "input": {
            "bounds": {
                "bbox": bbox,
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}
            },
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {
                    "timeRange": {
                        "from": f"{start_date}T00:00:00Z",
                        "to": f"{end_date}T23:59:59Z"
                    },
                    "maxCloudCoverage": maxcc,
                    "mosaickingOrder": "leastCC"  # Prioriza imágenes con menos nubes
                }
            }]
        },
        "output": {
            "width": int(width),
            "height": int(height),
            "responses": [{
                "identifier": "default",
                "format": {"type": "image/tiff"}
            }]
        },
        "evalscript": evalscript
    }
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    # Consulta a Process API por cada tile
    logger.info("Consultando Sentinel Hub Process API por tiles")
    process_url = "https://sh.dataspace.copernicus.eu/api/v1/process"

    for tile_idx, tile_bbox in enumerate(tiles, 1):
        logger.info(f"Procesando tile {tile_idx}/{len(tiles)}: {tile_bbox}")

        # Actualizar payload con bbox del tile actual
        payload["input"]["bounds"]["bbox"] = tile_bbox

        try:
            response = requests.post(process_url, json=payload, headers=headers, timeout=120)
            response.raise_for_status()
            logger.debug(f"Respuesta recibida (tile {tile_idx}): {len(response.content)} bytes")
        except requests.exceptions.RequestException as e:
            logger.error(f"Error en Process API (tile {tile_idx}): {e}")
            raise Exception(f"Error Process API (tile {tile_idx}): {e}")

        # Leer GeoTIFF desde memoria
        logger.debug(f"Procesando imagen GeoTIFF (tile {tile_idx})")
        with rasterio.open(BytesIO(response.content)) as src:
            ndvi_array = src.read(1)
            transform = src.transform
            raster_crs = src.crs

            ndvi_arrays.append(ndvi_array)
            transforms.append(transform)
            if raster_crs_ref is None:
                raster_crs_ref = raster_crs

            logger.debug(f"Dimensiones del raster (tile {tile_idx}): {ndvi_array.shape}")

    logger.info(f"Se procesaron {len(ndvi_arrays)} tiles correctamente")

    # Combinar arrays de tiles (usar el primero como referencia; en producción considerar mosaicado)
    ndvi_array = ndvi_arrays[0] if len(ndvi_arrays) == 1 else np.concatenate(ndvi_arrays)
    transform = transforms[0]
    raster_crs = raster_crs_ref
    
    # Aplicar máscara geométrica (recortar al área de estudio)
    logger.info("Aplicando máscara geométrica al área de estudio")
    gdf_mask = gdf_4326
    if raster_crs is not None and gdf_mask.crs != raster_crs:
        logger.debug(f"Reproyectando máscara de {gdf_mask.crs} a {raster_crs}")
        gdf_mask = gdf_mask.to_crs(raster_crs)
    
    # Unir todas las geometrías en una sola máscara
    geom = gdf_mask.geometry.union_all()
    
    # Crear máscara booleana: True dentro del polígono, False fuera
    inside = geometry_mask(
        [mapping(geom)],
        out_shape=ndvi_array.shape,
        transform=transform,
        invert=True,
        all_touched=False
    )
    
    # Aplicar máscara: NaN fuera del área de estudio
    ndvi_array = np.where(inside, ndvi_array, np.nan)
    
    # Filtrar valores válidos de NDVI
    valid_mask = (
        ~np.isnan(ndvi_array) &
        ~np.isinf(ndvi_array) &
        (ndvi_array >= -1) &
        (ndvi_array <= 1)
    )
    
    valid_ndvi = ndvi_array[valid_mask]
    ndvi_2d = np.where(valid_mask, ndvi_array, np.nan)
    
    pixeles_totales = ndvi_array.size
    pixeles_validos = valid_ndvi.size
    cobertura_pct = (pixeles_validos / pixeles_totales * 100) if pixeles_totales > 0 else 0
    
    logger.info(f"Píxeles válidos: {pixeles_validos}/{pixeles_totales} ({cobertura_pct:.2f}%)")
    
    if valid_ndvi.size == 0:
        logger.warning("No se encontraron píxeles válidos de NDVI")
        return None, None, None, None, bbox
    
    # Calcular factor C
    c_array = calcular_factor_C(ndvi_2d, metodo=metodo_c)
    
    # Estadísticas del NDVI
    stats = {
        "mean": float(valid_ndvi.mean()),
        "median": float(np.median(valid_ndvi)),
        "std": float(valid_ndvi.std()),
        "min": float(valid_ndvi.min()),
        "max": float(valid_ndvi.max()),
        "count": int(valid_ndvi.size),
        "coverage_pct": float(cobertura_pct),
        "date_range": f"{start_date} a {end_date}",
        "bbox_4326": bbox,
        "metodo_factor_c": metodo_c
    }
    
    logger.info("Estadísticas NDVI:")
    logger.info(f"  Media: {stats['mean']:.4f}")
    logger.info(f"  Mediana: {stats['median']:.4f}")
    logger.info(f"  Desviación estándar: {stats['std']:.4f}")
    logger.info(f"  Rango: [{stats['min']:.4f}, {stats['max']:.4f}]")
    
    logger.info("="*60)
    logger.info("Proceso completado exitosamente")
    logger.info("="*60)
    
    return valid_ndvi, ndvi_2d, c_array, stats, bbox


# Ejemplo de uso
if __name__ == "__main__":
    try:
        # Cargar área de estudio
        gdf = gpd.read_file("layers/test.gpkg")
        logger.info(f"GeoDataFrame cargado: {len(gdf)} geometrías")
        
        # Obtener NDVI y factor C
        valid_ndvi, ndvi_2d, c_array, stats, bbox = obtener_ndvi_valido(
            gdf=gdf,
            dias=90,
            maxcc=20,
            width=512,
            height=512,
            metodo_c='vanderknijff',
            client_id="tu_client_id",
            client_secret="tu_client_secret"
        )
        
        if valid_ndvi is not None:
            logger.info("Resultados obtenidos correctamente")
            logger.info(f"Estadísticas: {stats}")
        else:
            logger.warning("No se obtuvieron resultados válidos")
            
    except Exception as e:
        logger.error(f"Error durante la ejecución: {str(e)}", exc_info=True)
        raise