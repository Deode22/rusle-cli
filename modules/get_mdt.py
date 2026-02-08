import os
import sys
import logging
import rasterio
from rasterio.io import MemoryFile
from rasterio.merge import merge
from rasterio.features import geometry_mask
import requests
from math import ceil
import geopandas as gpd
import numpy as np
from time import sleep

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def obtener_mdt(
    geopackage_path,
    output_path=None,
    base_url="https://api-coverages.idee.es",
    coverage_id="EL.ElevationGridCoverage_4258_5_PB",
    max_tile_size=0.01,
    retries=3,
    timeout=120,
    verbose=True
):
    if verbose:
        logger.setLevel(logging.INFO)
    else:
        logger.setLevel(logging.WARNING)

    def get_with_retry(url, retries=retries, timeout=timeout):
        for attempt in range(retries):
            try:
                r = requests.get(url, timeout=timeout)
                if r.status_code == 200:
                    return r
                elif r.status_code == 500:
                    if attempt < retries - 1:
                        sleep(3)
                else:
                    return r
            except Exception:
                if attempt < retries - 1:
                    sleep(3)
        return r

    if isinstance(geopackage_path, gpd.GeoDataFrame):
        gdf = geopackage_path
        logger.info(f"GeoDataFrame recibido: {len(gdf)} filas, CRS: {gdf.crs}")
    else:
        gdf = gpd.read_file(geopackage_path)
        logger.info(f"GeoDataFrame cargado: {len(gdf)} filas, CRS: {gdf.crs}")

    if gdf.crs.to_epsg() != 4326:
        logger.info(f"Reproyectando de {gdf.crs} a EPSG:4326")
        gdf = gdf.to_crs(epsg=4326)

    minx, miny, maxx, maxy = gdf.total_bounds

    width = maxx - minx
    height = maxy - miny
    n_tiles_x = ceil(width / max_tile_size)
    n_tiles_y = ceil(height / max_tile_size)
    total_tiles = n_tiles_x * n_tiles_y

    logger.info(f"Area: {width:.6f}° x {height:.6f}° | Tiles: {n_tiles_x}x{n_tiles_y} = {total_tiles}")

    tiles_data = []

    for i in range(n_tiles_x):
        for j in range(n_tiles_y):
            tile_minx = minx + i * max_tile_size
            tile_maxx = min(tile_minx + max_tile_size, maxx)
            tile_miny = miny + j * max_tile_size
            tile_maxy = min(tile_miny + max_tile_size, maxy)

            tile_num = i * n_tiles_y + j + 1

            print(f"\rDescargando tiles: {tile_num}/{total_tiles} ({tile_num*100//total_tiles}%)", end='', flush=True)

            cog_url = f"{base_url}/collections/{coverage_id}/coverage?f=COG&bbox={tile_minx},{tile_miny},{tile_maxx},{tile_maxy}&bbox-crs=4326"

            try:
                r = get_with_retry(cog_url)

                if r.status_code == 200:
                    with MemoryFile(r.content) as memfile:
                        with memfile.open() as src:
                            tiles_data.append({
                                'data': src.read(1),
                                'transform': src.transform,
                                'crs': src.crs,
                                'nodata': src.nodata,
                                'dtype': src.dtypes[0]
                            })
                else:
                    logger.warning(f"Error {r.status_code} en tile {tile_num}")
            except Exception as e:
                logger.warning(f"Excepcion en tile {tile_num}: {e}")

    print()

    if not tiles_data:
        raise ValueError("No se pudo descargar ningun tile")

    logger.info(f"Descargados {len(tiles_data)}/{total_tiles} tiles correctamente")

    first_tile = tiles_data[0]
    src_crs = first_tile['crs']
    nodata_value = first_tile['nodata']

    logger.info("Uniendo tiles...")
    temp_datasets = []
    temp_memfiles = []

    for tile_info in tiles_data:
        memfile_temp = MemoryFile()
        temp_memfiles.append(memfile_temp)

        temp_dataset = memfile_temp.open(
            driver='GTiff',
            height=tile_info['data'].shape[0],
            width=tile_info['data'].shape[1],
            count=1,
            dtype=tile_info['dtype'],
            crs=tile_info['crs'],
            transform=tile_info['transform'],
            nodata=tile_info['nodata']
        )
        temp_dataset.write(tile_info['data'], 1)
        temp_datasets.append(temp_dataset)

    mosaic, mosaic_transform = merge(temp_datasets)

    for ds in temp_datasets:
        ds.close()

    logger.info(f"Mosaico creado: {mosaic.shape}")

    logger.info("Aplicando mascara de geometria...")
    mask_array = geometry_mask(
        gdf.geometry,
        transform=mosaic_transform,
        invert=True,
        out_shape=(mosaic.shape[1], mosaic.shape[2])
    )

    mosaic_masked = np.where(mask_array, mosaic[0], nodata_value if nodata_value is not None else np.nan)

    logger.info("Mascara aplicada")

    file_path = None
    if output_path:
        logger.info(f"Guardando resultado en {output_path}")
        with rasterio.open(
            output_path,
            'w',
            driver='GTiff',
            height=mosaic_masked.shape[0],
            width=mosaic_masked.shape[1],
            count=1,
            dtype=mosaic_masked.dtype,
            crs=src_crs,
            transform=mosaic_transform,
            nodata=nodata_value,
            compress='lzw'
        ) as dst:
            dst.write(mosaic_masked, 1)
        logger.info("Archivo guardado correctamente")
        file_path = output_path

    return {
        'data': mosaic_masked,
        'transform': mosaic_transform,
        'crs': src_crs,
        'nodata': nodata_value,
        'bounds': (minx, miny, maxx, maxy),
        'gdf': gdf,
        'file_path': file_path
    }