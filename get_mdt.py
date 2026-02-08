'''
Función para obtener datos de elevación desde la API del IGN
'''

import rasterio
from rasterio.io import MemoryFile
from rasterio.merge import merge
from rasterio.features import geometry_mask
import requests
from math import ceil
import geopandas as gpd
import numpy as np
from time import sleep


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
    """
    Descarga datos de elevación del servicio IDEE para un área definida en un GeoPackage.
    
    Parámetros:
    -----------
    geopackage_path : str
        Ruta al archivo GeoPackage con la geometría del área de interés
    output_path : str, optional
        Ruta donde guardar el raster resultante. Si es None, trabaja solo en memoria
    base_url : str
        URL base del servicio de cobertura
    coverage_id : str
        ID de la cobertura a descargar
    max_tile_size : float
        Tamaño máximo de cada tile en grados (default: 0.01 ≈ 1 km)
    retries : int
        Número de reintentos en caso de error
    timeout : int
        Timeout para las peticiones HTTP en segundos
    verbose : bool
        Si True, imprime información del progreso
        
    Retorna:
    --------
    dict con las siguientes claves:
        - 'data': numpy array con los datos de elevación
        - 'transform': transformación afín del raster
        - 'crs': sistema de coordenadas
        - 'nodata': valor de nodata
        - 'bounds': límites del área
        - 'gdf': GeoDataFrame original (reproyectado si fue necesario)
        - 'file_path': ruta del archivo guardado (None si solo está en memoria)
    """
    
    def log(msg):
        if verbose:
            print(msg)
    
    def get_with_retry(url, retries=retries, timeout=timeout):
        """Descarga con reintentos automáticos en caso de error 500"""
        for attempt in range(retries):
            try:
                r = requests.get(url, timeout=timeout)
                if r.status_code == 200:
                    return r
                elif r.status_code == 500:
                    log(f"⚠️ Error 500, reintento {attempt+1}/{retries}...")
                    if attempt < retries - 1:
                        sleep(3)
                else:
                    return r
            except Exception as e:
                log(f"⚠️ Excepción: {e}, reintento {attempt+1}/{retries}...")
                if attempt < retries - 1:
                    sleep(3)
        return r
    
    # Cargar el GeoDataFrame
    gdf = gpd.read_file(geopackage_path)
    
    log(f"📍 GeoDataFrame cargado:")
    log(f"  - Filas: {len(gdf)}")
    log(f"  - CRS: {gdf.crs}")
    log(f"  - Bounds: {gdf.total_bounds}\n")
    
    # Asegurar que está en EPSG:4326 (WGS84)
    if gdf.crs.to_epsg() != 4326:
        log(f"⚠️ Reproyectando de {gdf.crs} a EPSG:4326...")
        gdf = gdf.to_crs(epsg=4326)
    
    # Obtener el bbox del GeoDataFrame
    minx, miny, maxx, maxy = gdf.total_bounds
    
    # Calcular número de tiles necesarios
    width = maxx - minx
    height = maxy - miny
    n_tiles_x = ceil(width / max_tile_size)
    n_tiles_y = ceil(height / max_tile_size)
    total_tiles = n_tiles_x * n_tiles_y
    
    log(f"🔲 Área total: {width:.6f}° x {height:.6f}°")
    log(f"📦 Dividiendo en {n_tiles_x} x {n_tiles_y} = {total_tiles} tiles")
    log(f"📏 Tamaño de tile: {max_tile_size}° (~{max_tile_size*111:.1f} km)\n")
    
    # Descargar tiles
    tiles_data = []
    
    for i in range(n_tiles_x):
        for j in range(n_tiles_y):
            tile_minx = minx + i * max_tile_size
            tile_maxx = min(tile_minx + max_tile_size, maxx)
            tile_miny = miny + j * max_tile_size
            tile_maxy = min(tile_miny + max_tile_size, maxy)
            
            tile_num = i * n_tiles_y + j + 1
            log(f"⬇️  Tile {tile_num}/{total_tiles} [{tile_minx:.5f},{tile_miny:.5f},{tile_maxx:.5f},{tile_maxy:.5f}]... ")
            
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
                            log(f"✅ ({src.width}x{src.height} px, {len(r.content)/1024:.1f} KB)")
                else:
                    log(f"❌ Error {r.status_code}")
                    if r.status_code == 500:
                        log(f"   URL: {cog_url}")
            except Exception as e:
                log(f"❌ Excepción: {e}")
    
    if not tiles_data:
        raise ValueError("❌ No se pudo descargar ningún tile")
    
    log(f"\n✅ Descargados {len(tiles_data)}/{total_tiles} tiles correctamente\n")
    
    # Obtener metadatos del primer tile
    first_tile = tiles_data[0]
    src_crs = first_tile['crs']
    nodata_value = first_tile['nodata']
    
    log(f"📊 Información del raster:")
    log(f"  - CRS: {src_crs}")
    log(f"  - NoData: {nodata_value}\n")
    
    # Crear datasets temporales para merge
    log("🔗 Uniendo tiles...")
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
    
    # Merge
    mosaic, mosaic_transform = merge(temp_datasets)
    
    # Cerrar datasets temporales
    for ds in temp_datasets:
        ds.close()
    
    log(f"✅ Mosaico creado: {mosaic.shape}\n")
    
    # Recortar por capa de máscara
    log("✂️  Aplicando máscara de geometría...")
    mask_array = geometry_mask(
        gdf.geometry,
        transform=mosaic_transform,
        invert=True,
        out_shape=(mosaic.shape[1], mosaic.shape[2])
    )
    
    # Aplicar máscara al mosaico
    mosaic_masked = np.where(mask_array, mosaic[0], nodata_value if nodata_value is not None else np.nan)
    
    log(f"✅ Máscara aplicada\n")
    
    # Guardar si se especifica output_path
    file_path = None
    if output_path:
        log(f"💾 Guardando resultado en {output_path}...")
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
        log(f"✅ Archivo guardado correctamente\n")
        file_path = output_path
    else:
        log(f"💾 Datos mantenidos en memoria (no se guardó archivo)\n")
    
    # Retornar resultados
    return {
        'data': mosaic_masked,
        'transform': mosaic_transform,
        'crs': src_crs,
        'nodata': nodata_value,
        'bounds': (minx, miny, maxx, maxy),
        'gdf': gdf,
        'file_path': file_path
    }

'''
# Ejemplos de uso:
if __name__ == "__main__":
    # Uso 1: Solo en memoria (por defecto)
    result = obtener_mdt('test.gpkg')
    elevation_array = result['data']
    print(f"Forma del array: {elevation_array.shape}")
    print(f"Rango de elevación: {np.nanmin(elevation_array):.2f} - {np.nanmax(elevation_array):.2f} m")
    print(f"Archivo guardado: {result['file_path']}\n")
    
    # Uso 2: Guardar en disco
    result = obtener_mdt('test.gpkg', output_path='elevation.tif')
    print(f"Archivo guardado en: {result['file_path']}")
    
    # Uso 3: Sin mensajes de progreso
    result = obtener_mdt('test.gpkg', verbose=False)
'''