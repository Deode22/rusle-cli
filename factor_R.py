import cdsapi
import pandas as pd
import numpy as np
import xarray as xr
import zipfile
import os
from shapely.geometry import Point

def calcular_erosividad_desde_gdf(gdf, cds_api_key, start_year=2010, end_year=2024):
    """
    Calcula la climatología mensual y el factor R de erosividad para el centroide de un GeoDataFrame.
    
    Parámetros:
    -----------
    gdf : GeoDataFrame
        GeoDataFrame con geometrías (debe tener CRS definido)
    cds_api_key : str
        Clave API de Copernicus Climate Data Store
    start_year : int, opcional
        Año inicial para la descarga (por defecto 2010)
    end_year : int, opcional
        Año final para la descarga (por defecto 2024)
    
    Retorna:
    --------
    dict con:
        - df_climatologia: DataFrame con precipitación mensual promedio (mm)
        - R_factor: Factor de erosividad (MJ·mm·ha⁻¹·h⁻¹·año⁻¹)
        - MFI: Índice de Fournier Modificado
        - P_anual: Precipitación anual total (mm)
        - centroide: tupla (lat, lon) del punto analizado
    """
    
    # Calcular centroide del GeoDataFrame
    gdf_wgs84 = gdf.to_crs(epsg=4326)
    centroide = gdf_wgs84.unary_union.centroid
    LAT = centroide.y
    LON = centroide.x
    
    print(f"Centroide calculado: LAT={LAT:.4f}, LON={LON:.4f}")
    
    # Configuración de descarga
    years = [str(y) for y in range(start_year, end_year + 1)]
    d = 0.1
    area = [LAT + d, LON - d, LAT - d, LON + d]
    target = 'temp.grib'
    
    try:
        # ========== DESCARGA ==========
        client = cdsapi.Client(
            url="https://cds.climate.copernicus.eu/api",
            key=cds_api_key
        )
        
        dataset = "reanalysis-era5-land-monthly-means"
        request = {
            "product_type": ["monthly_averaged_reanalysis"],
            "variable": ["total_precipitation"],
            "year": years,
            "month": [f"{m:02d}" for m in range(1, 13)],
            "time": ["00:00"],
            "area": area,
            "data_format": "grib",
            "download_format": "unarchived",
        }
        
        print("Descargando datos de ERA5-Land...")
        client.retrieve(dataset, request, target)
        print("Descarga completada.")
        
        # ========== EXTRACCIÓN SI ES ZIP ==========
        with open(target, "rb") as f:
            head = f.read(4)
        
        if head == b"PK\x03\x04":
            with zipfile.ZipFile(target, "r") as z:
                names = z.namelist()
                grib_name = [n for n in names if n.lower().endswith(".grib")][0]
                z.extract(grib_name, ".")
            grib_path = grib_name
        else:
            grib_path = target
        
        # ========== ABRIR AMBOS TIPOS DE GRIB ==========
        print("Procesando datos GRIB...")
        ds1 = xr.open_dataset(
            grib_path,
            engine="cfgrib",
            backend_kwargs={
                "indexpath": "",
                "filter_by_keys": {
                    "typeOfLevel": "surface",
                    "stepType": "avgas",
                },
            },
        )
        
        ds2 = xr.open_dataset(
            grib_path,
            engine="cfgrib",
            backend_kwargs={
                "indexpath": "",
                "filter_by_keys": {
                    "typeOfLevel": "surface",
                    "stepType": "avgad",
                },
            },
        )
        
        # ========== COMBINAR DATASETS ==========
        ds_combined = xr.concat([ds1, ds2], dim="time").sortby("time")
        
        # ========== PROCESAMIENTO ==========
        point = ds_combined["tp"].sel(
            latitude=LAT,
            longitude=LON,
            method="nearest"
        )
        
        s = point.to_series().sort_index()
        
        # Conversión: m → mm (multiplicar por días del mes)
        mm_per_month = (s * 1000.0) * s.index.days_in_month
        
        # Climatología mensual (media de cada mes)
        df_climatologia = (
            mm_per_month
            .groupby(mm_per_month.index.month)
            .mean()
            .reindex(range(1, 13))
            .rename("precipitacion_total_mm")
            .to_frame()
        )
        df_climatologia.index.name = "mes"
        
        # ========== CALCULAR FACTOR R ==========
        precip_mensual = df_climatologia['precipitacion_total_mm'].values
        P_anual = np.sum(precip_mensual)
        MFI = np.sum(precip_mensual**2) / P_anual
        R_factor = 1.735 * (10 ** (1.5 * np.log10(MFI) - 0.08188))
        
        # Cerrar datasets
        ds1.close()
        ds2.close()
        ds_combined.close()
        
        print(f"\n✓ Climatología calculada")
        print(f"✓ Factor R: {R_factor:.2f} MJ·mm·ha⁻¹·h⁻¹·año⁻¹")
        
        return {
            'df_climatologia': df_climatologia,
            'R_factor': R_factor,
            'MFI': MFI,
            'P_anual': P_anual,
            'centroide': (LAT, LON)
        }
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        raise
        
    finally:
        # Limpieza de archivos temporales
        if os.path.exists(target):
            os.remove(target)
        if 'grib_path' in locals() and grib_path != target and os.path.exists(grib_path):
            os.remove(grib_path)
        print("Archivos temporales eliminados.")


# ========== EJEMPLO DE USO ==========
'''
import geopandas as gpd

# Cargar tu GeoDataFrame
gdf = gpd.read_file("test.gpkg")

# Calcular erosividad
resultado = calcular_erosividad_desde_gdf(
    gdf=gdf,
    cds_api_key="7314d9c0-2468-4f66-8d21-1bea09c0bccf",
    start_year=2010,
    end_year=2024
)

# Acceder a los resultados
print(resultado['df_climatologia'])
print(f"Factor R: {resultado['R_factor']:.2f}")
print(f"Centroide: {resultado['centroide']}")
'''