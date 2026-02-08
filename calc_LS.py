import numpy as np
from pysheds.sgrid import sGrid
from pysheds.sview import Raster, ViewFinder
from rasterio.warp import calculate_default_transform, reproject, Resampling
import rasterio
import warnings


def calcular_LS(dem_4326, transform_4326, gdf, nodata=None, metodo='desmet_govers', validar=True):
    """
    Calcula el factor LS con máxima precisión usando hidrología real,
    y devuelve el resultado en EPSG:4326.

    Parámetros
    ----------
    dem_4326 : 2D np.ndarray
        DEM en EPSG:4326 (grados).
    transform_4326 : affine.Affine
        Transform del DEM en EPSG:4326.
    gdf : GeoDataFrame
        GeoDataFrame del área de estudio (para determinar UTM).
    nodata : float|int|None
        Valor NoData del DEM.
    metodo : str
        'desmet_govers' (recomendado, 1996) o 'moore_burch' (1986).
    validar : bool
        Si True, valida rangos físicos y emite advertencias.

    Retorna
    -------
    LS_4326 : 2D np.ndarray
        Factor LS en EPSG:4326.
    diagnostico : dict
        Estadísticas y metadatos del cálculo.
    """
    
    print("\n" + "="*60)
    print("CÁLCULO DEL FACTOR LS")
    print("="*60)
    
    # ========== 1) Determinar CRS métrico (UTM) automáticamente ==========
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        gdf_centroid = gdf.to_crs("EPSG:4326").geometry.centroid.iloc[0]
    
    lat_centro = gdf_centroid.y
    
    utm_crs = gdf.to_crs(gdf.estimate_utm_crs()).crs
    print(f"  → CRS métrico: {utm_crs}")
    print(f"  → Latitud centro: {lat_centro:.4f}°")
    
    # ========== 2) Reproyectar DEM a UTM ==========
    print("  → Reproyectando DEM a metros...")
    height_4326, width_4326 = dem_4326.shape
    bounds_4326 = rasterio.transform.array_bounds(height_4326, width_4326, transform_4326)
    
    transform_utm, width_utm, height_utm = calculate_default_transform(
        src_crs="EPSG:4326",
        dst_crs=utm_crs,
        width=width_4326,
        height=height_4326,
        left=bounds_4326[0],
        bottom=bounds_4326[1],
        right=bounds_4326[2],
        top=bounds_4326[3],
        resolution=None
    )
    
    dem_utm = np.empty((height_utm, width_utm), dtype=np.float32)
    
    reproject(
        source=dem_4326.astype(np.float32),
        destination=dem_utm,
        src_transform=transform_4326,
        src_crs="EPSG:4326",
        dst_transform=transform_utm,
        dst_crs=utm_crs,
        resampling=Resampling.bilinear,
        src_nodata=nodata,
        dst_nodata=nodata if nodata is not None else -9999
    )
    
    cell_size_m = abs(transform_utm[0])
    print(f"  → Resolución: {cell_size_m:.2f} m")
    print(f"  → Dimensiones UTM: {height_utm} x {width_utm} px")
    
    # ========== 3) Crear ViewFinder y Raster para pysheds ==========
    # Calcular bbox desde transform
    bbox = rasterio.transform.array_bounds(height_utm, width_utm, transform_utm)
    
    # Crear ViewFinder object
    viewfinder = ViewFinder(
        shape=(height_utm, width_utm),
        mask=np.ones((height_utm, width_utm), dtype=bool),
        nodata=nodata if nodata is not None else -9999,
        affine=transform_utm,
        crs=utm_crs
    )
    
    # Crear Raster object
    dem_raster = Raster(dem_utm, viewfinder)
    
    # ========== 4) Hidrología con pysheds ==========
    print("  → Procesando hidrología (fill, flowdir, accumulation)...")
    
    grid = sGrid.from_raster(dem_raster)
    
    # Rellenar depresiones
    dem_filled = grid.fill_depressions(dem_raster)
    dem_inflated = grid.resolve_flats(dem_filled)
    
    # Dirección de flujo D8
    fdir = grid.flowdir(dem_inflated, routing='d8')
    
    # Acumulación de flujo (número de celdas)
    flow_acc = grid.accumulation(fdir, routing='d8')
    
    # Convertir a numpy array
    flow_acc = np.array(flow_acc).astype(np.float64)
    
    # Área contribuyente específica (m)
    A_s = flow_acc * cell_size_m
    A_s = np.clip(A_s, cell_size_m, None)
    
    print(f"     Acumulación máxima: {np.max(flow_acc):.0f} celdas")
    print(f"     Área contribuyente máxima: {np.max(A_s):.0f} m")
    
    # ========== 5) Pendiente (gradiente corregido) ==========
    dy, dx = np.gradient(dem_utm, cell_size_m, cell_size_m)
    
    slope_rad = np.arctan(np.sqrt(dx**2 + dy**2))
    slope_deg = np.degrees(slope_rad)
    slope_pct = np.tan(slope_rad) * 100
    slope_pct = np.clip(slope_pct, 0.01, 100)
    
    print(f"  → Pendiente media: {np.nanmean(slope_deg):.2f}°")
    print(f"  → Pendiente máxima: {np.nanmax(slope_deg):.2f}°")
    
    # ========== 6) Cálculo de LS según método ==========
    if metodo == 'desmet_govers':
        print("  → Método: Desmet & Govers (1996) - recomendado")
        
        # Exponente m (McCool et al., 1989 / Desmet & Govers, 1996)
        beta = (np.sin(slope_rad) / 0.0896) / (3.0 * np.sin(slope_rad)**0.8 + 0.56)
        m = beta / (1 + beta)
        m = np.clip(m, 0.2, 0.6)
        
        # Factor L (longitud)
        L = ((A_s + cell_size_m**2)**(m + 1) - A_s**(m + 1)) / \
            (cell_size_m**(m + 2) * (22.13**m) * ((m + 1)))
        
        # Factor S (pendiente)
        S = np.where(slope_pct < 9,
                     10.8 * np.sin(slope_rad) + 0.03,
                     16.8 * np.sin(slope_rad) - 0.50)
        
    elif metodo == 'moore_burch':
        print("  → Método: Moore & Burch (1986) - clásico")
        
        # Exponente m simplificado
        m = np.where(slope_pct < 1, 0.2,
             np.where(slope_pct < 3, 0.3,
             np.where(slope_pct < 5, 0.4, 0.5)))
        
        # Factor L
        L = (A_s / 22.13) ** m
        
        # Factor S
        S = np.where(slope_deg < 9,
                     10.8 * np.sin(slope_rad) + 0.03,
                     16.8 * np.sin(slope_rad) - 0.50)
    else:
        raise ValueError(f"Método '{metodo}' no reconocido. Usa 'desmet_govers' o 'moore_burch'")
    
    # ========== 7) LS combinado ==========
    LS_utm = L * S
    
    # Limpieza de valores
    LS_utm = np.where(np.isfinite(LS_utm), LS_utm, 0)
    LS_utm = np.clip(LS_utm, 0, 200)
    
    # Estadísticas en UTM
    ls_mean = np.nanmean(LS_utm)
    ls_median = np.nanmedian(LS_utm)
    ls_p95 = np.nanpercentile(LS_utm, 95)
    ls_max = np.nanmax(LS_utm)
    
    print(f"\n  Estadísticas LS (UTM):")
    print(f"     Media:    {ls_mean:.4f}")
    print(f"     Mediana:  {ls_median:.4f}")
    print(f"     P95:      {ls_p95:.2f}")
    print(f"     Máximo:   {ls_max:.2f}")
    
    # ========== 8) Validación de rangos físicos ==========
    if validar:
        advertencias = []
        
        if ls_mean < 0.1:
            advertencias.append("⚠️  LS medio muy bajo (< 0.1) - terreno extremadamente plano")
        
        if ls_mean > 20:
            advertencias.append("⚠️  LS medio muy alto (> 20) - revisar DEM o área de estudio")
        
        if ls_max > 100:
            advertencias.append(f"⚠️  LS máximo = {ls_max:.1f} (> 100) - posibles artefactos en cauces")
        
        pct_alto = np.sum(LS_utm > 50) / LS_utm.size * 100
        if pct_alto > 5:
            advertencias.append(f"⚠️  {pct_alto:.1f}% de píxeles con LS > 50 (inusual)")
        
        if advertencias:
            print("\n  🔍 Validación:")
            for adv in advertencias:
                print(f"     {adv}")
        else:
            print("\n  ✅ Validación: rangos dentro de lo esperado")
    
    # ========== 9) Reproyectar LS de vuelta a EPSG:4326 ==========
    print("\n  → Reproyectando LS a EPSG:4326...")
    
    LS_4326 = np.empty((height_4326, width_4326), dtype=np.float32)
    
    reproject(
        source=LS_utm.astype(np.float32),
        destination=LS_4326,
        src_transform=transform_utm,
        src_crs=utm_crs,
        dst_transform=transform_4326,
        dst_crs="EPSG:4326",
        resampling=Resampling.bilinear,
        src_nodata=0,
        dst_nodata=0
    )
    
    print(f"  → LS final (EPSG:4326): mean={np.nanmean(LS_4326):.4f}")
    print("="*60 + "\n")
    
    # ========== 10) Diagnóstico ==========
    diagnostico = {
        'metodo': metodo,
        'utm_crs': str(utm_crs),
        'resolucion_m': float(cell_size_m),
        'latitud_centro': float(lat_centro),
        'ls_mean': float(ls_mean),
        'ls_median': float(ls_median),
        'ls_p95': float(ls_p95),
        'ls_max': float(ls_max),
        'slope_mean_deg': float(np.nanmean(slope_deg)),
        'slope_max_deg': float(np.nanmax(slope_deg)),
        'flow_acc_max': float(np.max(flow_acc))
    }
    
    return LS_4326, diagnostico