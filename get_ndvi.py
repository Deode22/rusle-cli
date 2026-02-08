'''
Función para obtener el ndvi 
'''

import requests
import numpy as np
from datetime import datetime, timedelta
from shapely.geometry import mapping
from rasterio.features import geometry_mask
import numpy as np

import geopandas as gpd
import rasterio
from io import BytesIO

def bbox_from_gdf(gdf: gpd.GeoDataFrame):
    """
    Devuelve bbox [minx, miny, maxx, maxy] en EPSG:4326 a partir del extent del GDF.
    Si el CRS no es 4326, reproyecta.
    """
    if gdf is None or len(gdf) == 0:
        raise ValueError("El GeoDataFrame está vacío.")

    if "geometry" not in gdf.columns:
        raise ValueError("El GeoDataFrame no tiene columna 'geometry'.")

    if gdf.crs is None:
        raise ValueError("El GeoDataFrame no tiene CRS definido (gdf.crs is None). Asigna uno antes.")

    # Reproyectar si no es EPSG:4326
    epsg = gdf.crs.to_epsg()
    if epsg != 4326:
        gdf = gdf.to_crs(epsg=4326)

    minx, miny, maxx, maxy = gdf.total_bounds
    return [float(minx), float(miny), float(maxx), float(maxy)], gdf


def obtener_ndvi_valido(gdf: gpd.GeoDataFrame, dias=90, maxcc=20, width=512, height=512):
    """
    Obtiene NDVI válido usando Sentinel Hub Process API.
    El bbox sale del extent del GDF (en EPSG:4326; reproyecta si hace falta).
    """
    # Nota: no hardcodees credenciales en código; usa variables de entorno si puedes.
    CLIENT_ID = "sh-48cd7ecb-e398-4c07-bf7a-2d0c5df1843e"
    CLIENT_SECRET = "WbAGISqNR6XhHyxmVB2qlmPcbdMaHJGZ"

    bbox, gdf_4326 = bbox_from_gdf(gdf)

    # 1) Token OAuth
    token_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    token_response = requests.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        },
        timeout=60
    )
    if token_response.status_code != 200:
        raise Exception(f"Error obteniendo token: {token_response.status_code} - {token_response.text}")

    access_token = token_response.json()["access_token"]

    # 2) Fechas
    today = datetime.utcnow()
    start_date = (today - timedelta(days=dias)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")

    # 3) Process API
    process_url = "https://sh.dataspace.copernicus.eu/api/v1/process"

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
        // SCL: 3=sombra, 8=nube media, 9=nube alta, 10=cirrus, 11=nieve/hielo
        if ([3, 8, 9, 10, 11].includes(sample.SCL)) {
            return [NaN];
        }
        let denom = (sample.B08 + sample.B04);
        if (denom === 0) return [NaN];
        let ndvi = (sample.B08 - sample.B04) / denom;
        return [ndvi];
    }
    """

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
                    "mosaickingOrder": "leastCC"
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

    response = requests.post(process_url, json=payload, headers=headers, timeout=120)
    if response.status_code != 200:
        raise Exception(f"Error Process API {response.status_code}: {response.text}")

    # 4) Leer TIFF
    with rasterio.open(BytesIO(response.content)) as src:
        ndvi_array = src.read(1)
        transform = src.transform
        raster_crs = src.crs  # debería venir en el GeoTIFF

    # 1) Asegura que la máscara (gdf) está en el mismo CRS que el raster
    gdf_mask = gdf_4326
    if raster_crs is not None and gdf_mask.crs != raster_crs:
        gdf_mask = gdf_mask.to_crs(raster_crs)

    # 2) Unir geometrías (una sola máscara)
    geom = gdf_mask.geometry.union_all()  

    # 3) Crear máscara booleana: True = dentro del polígono, False = fuera
    inside = geometry_mask(
        [mapping(geom)],
        out_shape=ndvi_array.shape,
        transform=transform,
        invert=True,          # invert=True => True dentro
        all_touched=False     # True es más “permisivo” en bordes
    )

    # 4) Poner NaN fuera del polígono
    ndvi_array = np.where(inside, ndvi_array, np.nan)

    # 5) (Opcional) ahora ya aplicas tu máscara de valores válidos como antes
    valid_mask = (
        ~np.isnan(ndvi_array) &
        ~np.isinf(ndvi_array) &
        (ndvi_array >= -1) &
        (ndvi_array <= 1)
    )
    valid_ndvi = ndvi_array[valid_mask]
    ndvi_2d = np.where(valid_mask, ndvi_array, np.nan)

    # Calcular factor C: C = 0.431 - 0.805 * NDVI
    c_array = 0.431 - 0.805 * ndvi_2d

    if valid_ndvi.size == 0:
        return None, None, None, None, bbox

    stats = {
        "mean": float(valid_ndvi.mean()),
        "median": float(np.median(valid_ndvi)),
        "std": float(valid_ndvi.std()),
        "min": float(valid_ndvi.min()),
        "max": float(valid_ndvi.max()),
        "count": int(valid_ndvi.size),
        "coverage": float(valid_ndvi.size / ndvi_array.size * 100),
        "date_range": f"{start_date} a {end_date}",
        "bbox_4326": bbox
    }

    return valid_ndvi, ndvi_2d, c_array, stats, bbox


# Ejemplo de uso:
# gdf = gpd.read_file("mi_poligono.gpkg")  # o el que sea
# valid_ndvi, ndvi_2d, stats, bbox = obtener_ndvi_valido(gdf, dias=90, maxcc=50)