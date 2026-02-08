"""
Cálculo de RUSLE: A = R * K * LS * C * P
Genera tres escenarios de evolución del factor C
"""

import os
import argparse
from datetime import datetime
from pathlib import Path
import numpy as np
import geopandas as gpd
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.features import rasterize

from get_mdt import obtener_mdt
from get_C import obtener_ndvi_valido
from get_R import factorR_wms
from get_K import factor_K_williams
from calc_LS import calcular_LS


def resample_to_reference(source_array, source_transform, source_crs,
                          ref_shape, ref_transform, ref_crs):
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
        resampling=Resampling.bilinear
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


def eliminar_outliers(data, lower_pct=2.5, upper_pct=97.5):
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


def main(capa: str, output: str, factor_c: list = None, factor_p: float = 1.0):
    gdf = gpd.read_file(capa)

    print("=" * 60)
    print("CÁLCULO DE RUSLE - A = R * K * LS * C * P")
    print("=" * 60)

    print("\n[1/4] Calculando Factor R (Erosividad)...")
    _, factor_R = factorR_wms(gdf)
    print(f"  R = {factor_R:.2f} MJ·mm·ha⁻¹·h⁻¹·año⁻¹")

    print("\n[2/4] Calculando Factor K (Erodibilidad del suelo)...")
    k_result = factor_K_williams(gdf, depth="0-5cm", stat="mean")
    K_array = k_result['K']
    K_profile = k_result['profile']
    print(f"  K mean = {np.nanmean(K_array):.4f} t·h/(MJ·mm)")

    print("\n[3/4] Obteniendo MDT y calculando Factor LS...")
    mdt_result = obtener_mdt(capa)
    elevation = mdt_result['data']
    mdt_transform = mdt_result['transform']
    mdt_crs = mdt_result['crs']
    LS_array, _ = calcular_LS(
        elevation,
        mdt_transform,
        gdf,
        nodata=None,
        metodo='desmet_govers',  # o 'moore_burch'
        validar=True
    )

    print("\n[4/4] Calculando Factor C (Cobertura vegetal)...")
    _, _, C_array, _, bbox = obtener_ndvi_valido(gdf, dias=90, maxcc=20)
    if C_array is None:
        raise ValueError("No se pudo obtener el NDVI/Factor C")
    C_array = np.clip(C_array, 0, 1)
    print(f"  C mean = {np.nanmean(C_array):.4f}")

    P = factor_p
    print(f"\n  P = {P}")

    print("\n[Resampleando factores a grilla común...]")
    ref_shape = C_array.shape

    minx, miny, maxx, maxy = bbox
    ref_transform = rasterio.transform.from_bounds(minx, miny, maxx, maxy, ref_shape[1], ref_shape[0])
    ref_crs = "EPSG:4326"

    K_resampled = resample_to_reference(
        K_array, K_profile['transform'], K_profile['crs'],
        ref_shape, ref_transform, ref_crs
    )

    LS_resampled = resample_to_reference(
        LS_array, mdt_transform, mdt_crs,
        ref_shape, ref_transform, ref_crs
    )

    print("\n" + "=" * 60)
    print("CALCULANDO RUSLE")
    print("=" * 60)

    mascara_gdf = crear_mascara_gdf(gdf, ref_shape, ref_transform, ref_crs)

    A_original = factor_R * K_resampled * LS_resampled * C_array * P
    print("[Eliminando outliers (percentiles 2.5-97.5)...]")
    A_original = eliminar_outliers(A_original)
    print(f"\nEscenario actual (C original): A mean = {np.nanmean(A_original):.4f} t/ha/año")

    os.makedirs(output, exist_ok=True)
    print(f"\nGuardando rasters en: {output}")

    guardar_raster(A_original, ref_transform, ref_crs,
                   os.path.join(output, "A_rusle_actual.tif"))
    print("  - A_rusle_actual.tif")

    if factor_c is not None:
        c_medio_val, c_largo_val = factor_c

        if c_medio_val is None:
            C_medio = C_array * 0.5
            c_medio_str = "C*0.5"
        else:
            C_medio = np.full_like(C_array, c_medio_val)
            c_medio_str = str(c_medio_val)
        C_medio = np.where(mascara_gdf, C_medio, np.nan)

        if c_largo_val is None:
            C_largo = C_array * 0.1
            c_largo_str = "C*0.1"
        else:
            C_largo = np.full_like(C_array, c_largo_val)
            c_largo_str = str(c_largo_val)
        C_largo = np.where(mascara_gdf, C_largo, np.nan)

        A_medio = factor_R * K_resampled * LS_resampled * C_medio * P
        A_largo = factor_R * K_resampled * LS_resampled * C_largo * P

        A_medio = eliminar_outliers(A_medio)
        A_largo = eliminar_outliers(A_largo)

        print(f"Escenario medio plazo (C={c_medio_str}): A mean = {np.nanmean(A_medio):.4f} t/ha/año")
        print(f"Escenario largo plazo (C={c_largo_str}): A mean = {np.nanmean(A_largo):.4f} t/ha/año")

        guardar_raster(A_medio, ref_transform, ref_crs,
                       os.path.join(output, "A_rusle_medio-plazo.tif"))
        print("  - A_rusle_medio-plazo.tif")

        guardar_raster(A_largo, ref_transform, ref_crs,
                       os.path.join(output, "A_rusle_largo-plazo.tif"))
        print("  - A_rusle_largo-plazo.tif")

    print("\n" + "=" * 60)
    print("PROCESO COMPLETADO")
    print("=" * 60)


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
    parser.add_argument("-c", "--capa", required=True, help="Ruta al archivo vectorial (gpkg, shp, geojson...)")
    parser.add_argument("-o", "--output", default=None, help="Ruta de la carpeta de salida (default: Descargas/RUSLE_output_YYYYMMDD)")
    parser.add_argument("-fc", "--factor-c", nargs='*', metavar="VAL", help="Valores de C medio/largo plazo. Sin args: C*0.5/C*0.1. Con args: -fc 0.1 0.02 o -fc _ 0.01")
    parser.add_argument("-p", "--factor-p", type=float, default=1.0, help="Valor del factor P (default: 1.0)")

    args = parser.parse_args()

    if args.output is None:
        fecha = datetime.now().strftime("%Y%m%d")
        args.output = str(Path.home() / "Downloads" / f"RUSLE_output_{fecha}")

    factor_c_parsed = parse_factor_c(args.factor_c)
    main(args.capa, args.output, factor_c_parsed, args.factor_p)
