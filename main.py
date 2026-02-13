"""
Cálculo de RUSLE: A = R * K * LS * C * P
Genera tres escenarios de evolución del factor C
"""

import os
import sys
import logging
import argparse
from datetime import datetime
from pathlib import Path
import numpy as np
import geopandas as gpd
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.features import rasterize
from shapely.geometry import box

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

from modules.get_mdt import obtener_mdt
from modules.get_C import obtener_ndvi_valido
from modules.get_R import factorR_wms
from modules.get_K import factor_K_williams
from modules.calc_LS import calcular_LS
from modules.informe import generar_informe_rusle

def crear_grilla_utm_10m(gdf, resolucion=10):
    """
    Construye una grilla UTM a 10m de resolución desde los límites del GeoDataFrame.
    """
    from pyproj import CRS, Transformer
    bounds_4326 = gdf.to_crs("EPSG:4326").total_bounds
    lon_center = (bounds_4326[0] + bounds_4326[2]) / 2
    lat_center = (bounds_4326[1] + bounds_4326[3]) / 2
    utm_zone = int((lon_center + 180) / 6) + 1
    hemisphere = 'north' if lat_center >= 0 else 'south'
    utm_crs = CRS.from_dict({
        'proj': 'utm', 'zone': utm_zone, 'datum': 'WGS84', hemisphere: True
    })

    transformer = Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True)
    x_min, y_min = transformer.transform(bounds_4326[0], bounds_4326[1])
    x_max, y_max = transformer.transform(bounds_4326[2], bounds_4326[3])

    x_min = np.floor(x_min / resolucion) * resolucion
    y_max = np.ceil(y_max / resolucion) * resolucion

    ncols = int(np.ceil((x_max - x_min) / resolucion))
    nrows = int(np.ceil((y_max - y_min) / resolucion))

    ref_transform = rasterio.transform.from_origin(x_min, y_max, resolucion, resolucion)
    ref_shape = (nrows, ncols)

    logger.info(f"Grilla UTM {utm_zone}{hemisphere[0].upper()} a {resolucion}m: {ncols}x{nrows} px")
    return ref_shape, ref_transform, utm_crs


def resample_to_reference(source_array, source_transform, source_crs,
                          ref_shape, ref_transform, ref_crs,
                          resampling=Resampling.bilinear):
    """
    Resamplea un array para que coincida con una referencia.
    """
    dst = np.empty(ref_shape, dtype=np.float32)

    reproject(
        source=source_array.astype(np.float32),
        destination=dst,
        src_transform=source_transform,
        src_crs=source_crs,
        dst_transform=ref_transform,
        dst_crs=ref_crs,
        resampling=resampling
    )

    return dst


def crear_mascara_gdf(gdf, shape, transform, crs):
    """
    Crea una máscara raster a partir del GDF.
    """
    gdf_reproj = gdf.to_crs(crs)
    geometries = gdf_reproj.geometry.values
    mask = rasterize(
        geometries,
        out_shape=shape,
        transform=transform,
        fill=0,
        default_value=1,
        dtype=np.uint8
    )
    return mask.astype(bool)


def eliminar_outliers(data, lower_pct=0.1, upper_pct=99.9):
    """
    Elimina outliers usando percentiles.
    Valores fuera del rango se convierten en NaN.
    """
    valid = data[np.isfinite(data)]
    if len(valid) == 0:
        return data

    lower = np.percentile(valid, lower_pct)
    upper = np.percentile(valid, upper_pct)

    result = data.copy()
    result[(data < lower) | (data > upper)] = np.nan
    return result


def guardar_raster(data, transform, crs, filepath, nodata=-9999):
    """
    Guarda un array como GeoTIFF.
    """
    data_out = np.where(np.isfinite(data), data, nodata)

    with rasterio.open(
        filepath, 'w',
        driver='GTiff',
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=np.float32,
        crs=crs,
        transform=transform,
        nodata=nodata,
        compress='lzw'
    ) as dst:
        dst.write(data_out.astype(np.float32), 1)


def crear_bbox_desde_coordenadas(lat, lon, lado_metros):
    """
    Crea un GeoDataFrame con un bbox cuadrado centrado en las coordenadas dadas.

    Args:
        lat: Latitud (ej: 40.57232729502867)
        lon: Longitud (ej: -4.403293925819235)
        lado_metros: Lado del cuadrado en metros (ej: 100 para 100x100m)

    Returns:
        GeoDataFrame con el bbox en EPSG:4326

    Note:
        SoilGrids tiene resolución de 250m, se recomienda lado_metros >= 500m
    """
    from pyproj import Transformer, CRS

    MIN_LADO_RECOMENDADO = 500
    if lado_metros < MIN_LADO_RECOMENDADO:
        logger.warning(f"Lado del bbox ({lado_metros}m) es menor que el recomendado ({MIN_LADO_RECOMENDADO}m)")
        logger.warning(f"   SoilGrids tiene resolución de 250m, bbox pequeños pueden fallar")

    utm_zone = int((lon + 180) / 6) + 1
    hemisphere = 'north' if lat >= 0 else 'south'
    utm_crs = CRS.from_dict({
        'proj': 'utm',
        'zone': utm_zone,
        'datum': 'WGS84',
        hemisphere: True
    })

    transformer_to_utm = Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True)
    transformer_to_wgs = Transformer.from_crs(utm_crs, "EPSG:4326", always_xy=True)

    x_utm, y_utm = transformer_to_utm.transform(lon, lat)

    half_side = lado_metros / 2

    x_min_utm = x_utm - half_side
    x_max_utm = x_utm + half_side
    y_min_utm = y_utm - half_side
    y_max_utm = y_utm + half_side

    lon_min, lat_min = transformer_to_wgs.transform(x_min_utm, y_min_utm)
    lon_max, lat_max = transformer_to_wgs.transform(x_max_utm, y_max_utm)

    bbox_geom = box(lon_min, lat_min, lon_max, lat_max)

    gdf = gpd.GeoDataFrame([{'geometry': bbox_geom}], crs="EPSG:4326")

    logger.info(f"Bbox creado: centro ({lat:.6f}, {lon:.6f}), lado {lado_metros}m")
    logger.info(f"  UTM zona {utm_zone}{hemisphere[0].upper()}")
    logger.info(f"  Coordenadas WGS84: ({lat_min:.6f}, {lon_min:.6f}) a ({lat_max:.6f}, {lon_max:.6f})")

    return gdf


def main(capa: str = None, output: str = None, factor_c: list = None, factor_p: float = 1.0,
         cambio_r: float = None, cambio_k: float = None, cambio_ls: float = None, cambio_c: float = None,
         coordenadas: tuple = None, lado_bbox: int = None):

    if coordenadas is not None and lado_bbox is not None:
        lat, lon = coordenadas
        gdf = crear_bbox_desde_coordenadas(lat, lon, lado_bbox)
        area_nombre = f"bbox_{lat:.6f}_{lon:.6f}_{lado_bbox}m"
    elif capa is not None:
        gdf = gpd.read_file(capa)
        area_nombre = Path(capa).stem
    else:
        raise ValueError("Debe especificar -c/--capa o --coordenadas con --lado-bbox")

    logger.info("─" * 60)
    logger.info("CÁLCULO DE RUSLE - A = R * K * LS * C * P")
    logger.info("─" * 60)

    if cambio_r is not None:
        logger.info(f"\n[1/4] Usando Factor R manual: {cambio_r:.2f} MJ·mm·ha⁻¹·h⁻¹·año⁻¹")
        factor_R = cambio_r
    else:
        logger.info("\n[1/4] Calculando Factor R (Erosividad)...")
        _, factor_R = factorR_wms(gdf)
        logger.info(f"  R = {factor_R:.2f} MJ·mm·ha⁻¹·h⁻¹·año⁻¹")

    if cambio_k is not None:
        logger.info(f"\n[2/4] Usando Factor K manual: {cambio_k:.4f} t·h/(MJ·mm)")
        K_array = None
        K_profile = None
        K_manual = cambio_k
    else:
        logger.info("\n[2/4] Calculando Factor K (Erodibilidad del suelo)...")
        k_result = factor_K_williams(gdf, depth="0-5cm", stat="mean")
        K_array = k_result['K']
        K_profile = k_result['profile']
        K_manual = None
        logger.info(f"  K mean = {np.nanmean(K_array):.4f} t·h/(MJ·mm)")

    if cambio_ls is not None:
        logger.info(f"\n[3/4] Usando Factor LS manual: {cambio_ls:.4f}")
        LS_array = None
        mdt_transform = None
        mdt_crs = None
        LS_manual = cambio_ls
    else:
        logger.info("\n[3/4] Obteniendo MDT y calculando Factor LS...")
        mdt_result = obtener_mdt(gdf)
        elevation = mdt_result['data']
        mdt_transform = mdt_result['transform']
        mdt_crs = mdt_result['crs']
        LS_array, _ = calcular_LS(
            elevation,
            mdt_transform,
            gdf,
            nodata=None,
            metodo='desmet_govers',
            validar=True
        )
        LS_manual = None

    if cambio_c is not None:
        logger.info(f"\n[4/4] Usando Factor C manual: {cambio_c:.4f}")
        C_array = None
        bbox = None
        C_manual = cambio_c
    else:
        logger.info("\n[4/4] Calculando Factor C (Cobertura vegetal)...")
        _, _, C_array, _, bbox = obtener_ndvi_valido(gdf, dias=90, maxcc=20)
        if C_array is None:
            raise ValueError("No se pudo obtener el NDVI/Factor C")
        C_array = np.clip(C_array, 0, 1)
        C_manual = None
        logger.info(f"  C mean = {np.nanmean(C_array):.4f}")

    P = factor_p
    logger.info(f"\n  P = {P}")

    logger.info("\n[Resampleando factores a grilla UTM 10m...]")

    ref_shape, ref_transform, ref_crs = crear_grilla_utm_10m(gdf, resolucion=10)

    if K_array is not None:
        K_resampled = resample_to_reference(
            K_array, K_profile['transform'], K_profile['crs'],
            ref_shape, ref_transform, ref_crs,
            resampling=Resampling.cubic
        )
    else:
        K_resampled = np.full(ref_shape, K_manual, dtype=np.float32)

    if LS_array is not None:
        LS_resampled = resample_to_reference(
            LS_array, mdt_transform, mdt_crs,
            ref_shape, ref_transform, ref_crs,
            resampling=Resampling.bilinear
        )
    else:
        LS_resampled = np.full(ref_shape, LS_manual, dtype=np.float32)

    if C_array is not None:
        c_minx, c_miny, c_maxx, c_maxy = bbox
        c_transform = rasterio.transform.from_bounds(
            c_minx, c_miny, c_maxx, c_maxy, C_array.shape[1], C_array.shape[0]
        )
        C_resampled = resample_to_reference(
            C_array, c_transform, "EPSG:4326",
            ref_shape, ref_transform, ref_crs,
            resampling=Resampling.bilinear
        )
    else:
        C_resampled = np.full(ref_shape, C_manual, dtype=np.float32)

    logger.info("\n" + "─" * 60)
    logger.info("CALCULANDO RUSLE")
    logger.info("─" * 60)

    mascara_gdf = crear_mascara_gdf(gdf, ref_shape, ref_transform, ref_crs)

    A_original = factor_R * K_resampled * LS_resampled * C_resampled * P
    logger.info("[Eliminando outliers...]")
    A_original = eliminar_outliers(A_original)
    logger.info(f"\nEscenario actual (C original): A mean = {np.nanmean(A_original):.4f} t/ha/año")

    os.makedirs(output, exist_ok=True)
    logger.info(f"\nGuardando rasters en: {output}")

    guardar_raster(A_original, ref_transform, ref_crs,
                   os.path.join(output, "A_rusle_actual.tif"))
    logger.info("  - A_rusle_actual.tif")

    if factor_c is not None:
        c_medio_val, c_largo_val = factor_c

        if c_medio_val is None:
            if cambio_c is not None:
                C_medio = np.full_like(C_resampled, C_manual * 0.5)
            else:
                C_medio = C_resampled * 0.5
            c_medio_str = "C*0.5"
        else:
            C_medio = np.full_like(C_resampled, c_medio_val)
            c_medio_str = str(c_medio_val)
        C_medio = np.where(mascara_gdf, C_medio, np.nan)

        if c_largo_val is None:
            if cambio_c is not None:
                C_largo = np.full_like(C_resampled, C_manual * 0.1)
            else:
                C_largo = C_resampled * 0.1
            c_largo_str = "C*0.1"
        else:
            C_largo = np.full_like(C_resampled, c_largo_val)
            c_largo_str = str(c_largo_val)
        C_largo = np.where(mascara_gdf, C_largo, np.nan)

        A_medio = factor_R * K_resampled * LS_resampled * C_medio * P
        A_largo = factor_R * K_resampled * LS_resampled * C_largo * P

        A_medio = eliminar_outliers(A_medio)
        A_largo = eliminar_outliers(A_largo)

        logger.info(f"Escenario medio plazo (C={c_medio_str}): A mean = {np.nanmean(A_medio):.4f} t/ha/año")
        logger.info(f"Escenario largo plazo (C={c_largo_str}): A mean = {np.nanmean(A_largo):.4f} t/ha/año")

        guardar_raster(A_medio, ref_transform, ref_crs,
                       os.path.join(output, "A_rusle_medio-plazo.tif"))
        logger.info("  - A_rusle_medio-plazo.tif")

        guardar_raster(A_largo, ref_transform, ref_crs,
                       os.path.join(output, "A_rusle_largo-plazo.tif"))
        logger.info("  - A_rusle_largo-plazo.tif")

    logger.info("\n" + "─" * 60)
    logger.info("GENERANDO INFORME PDF")
    logger.info("─" * 60)

    try:
        raster_path = os.path.join(output, "A_rusle_actual.tif")
        pdf_path = os.path.join(output, "informe_erosion.pdf")

        generar_informe_rusle(
            output_pdf=pdf_path,
            R_value=factor_R,
            K_array=K_resampled,
            LS_array=LS_resampled,
            C_array=C_resampled,
            P_value=P,
            A_array=A_original,
            metodo_LS="Desmet & Govers (1996)",
            raster_path=raster_path
        )
        logger.info(f"  - informe_erosion.pdf")
    except Exception as e:
        logger.error(f"Error al generar informe PDF: {e}")
        logger.info("  (Continuando sin informe)")

    logger.info("\n" + "─" * 60)
    logger.info("PROCESO COMPLETADO")
    logger.info("─" * 60)


def parse_factor_c(args):
    """
    Parsea el argumento -fc:
    - Sin valores: (None, None) -> C*0.5, C*0.1
    - Con dos valores: (val1, val2) o None si es '_'
    """
    if args is None:
        return None
    if len(args) == 0:
        return (None, None)
    if len(args) == 2:
        c_medio = None if args[0] == '_' else float(args[0])
        c_largo = None if args[1] == '_' else float(args[1])
        return (c_medio, c_largo)
    raise ValueError("-fc requiere 0 o 2 argumentos (ej: -fc, -fc 0.1 0.02, -fc _ 0.01)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cálculo de RUSLE con escenarios de factor C")

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("-c", "--capa", help="Ruta al archivo vectorial (gpkg, shp, geojson...)")
    input_group.add_argument("--coordenadas", "-coords", nargs=2, type=float, metavar=("LAT", "LON"),
                            help="Coordenadas del centro (lat, lon) ej: 40.5723 -4.4033")

    parser.add_argument("--lado-bbox", "--lado", type=int, metavar="METROS",
                       help="Lado del bbox en metros (requerido con --coordenadas). Mínimo recomendado: 500m")
    parser.add_argument("-o", "--output", default=None, help="Ruta de la carpeta de salida (default: Descargas/RUSLE_output_YYYYMMDD)")
    parser.add_argument("-fc", "--factor-c", nargs='*', metavar="VAL", help="Valores de C medio/largo plazo. Sin args: C*0.5/C*0.1. Con args: -fc 0.1 0.02 o -fc _ 0.01")
    parser.add_argument("-p", "--factor-p", type=float, default=1.0, help="Valor del factor P (default: 1.0)")
    parser.add_argument("-cr", "--cambio-r", type=float, default=None, help="Valor manual del factor R (Erosividad)")
    parser.add_argument("-ck", "--cambio-k", type=float, default=None, help="Valor manual del factor K (Erodibilidad)")
    parser.add_argument("-cls", "--cambio-ls", type=float, default=None, help="Valor manual del factor LS (Topografía)")
    parser.add_argument("-cc", "--cambio-c", type=float, default=None, help="Valor manual del factor C (Cobertura)")

    args = parser.parse_args()

    if args.coordenadas and not args.lado_bbox:
        parser.error("--coordenadas requiere --lado-bbox")

    if args.lado_bbox and not args.coordenadas:
        parser.error("--lado-bbox requiere --coordenadas")

    if args.output is None:
        fecha = datetime.now().strftime("%Y%m%d-%H%M")
        args.output = str(Path.home() / "Downloads" / f"RUSLE_output_{fecha}")

    factor_c_parsed = parse_factor_c(args.factor_c)

    coordenadas_tuple = tuple(args.coordenadas) if args.coordenadas else None

    main(capa=args.capa, output=args.output, factor_c=factor_c_parsed, factor_p=args.factor_p,
         cambio_r=args.cambio_r, cambio_k=args.cambio_k, cambio_ls=args.cambio_ls, cambio_c=args.cambio_c,
         coordenadas=coordenadas_tuple, lado_bbox=args.lado_bbox)
