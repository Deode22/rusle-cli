import numpy as np
from pysheds.sgrid import sGrid
from pysheds.sview import Raster, ViewFinder
from rasterio.warp import calculate_default_transform, reproject, Resampling
import rasterio
import warnings
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)


def calcular_LS(dem_4326, transform_4326, gdf, nodata=None, metodo='desmet_govers', validar=True):
    """
    Calcula el factor LS (longitud y pendiente de ladera) para la ecuación RUSLE/USLE.
    
    El cálculo se realiza en coordenadas métricas (UTM) para garantizar precisión en
    el análisis hidrológico y topográfico, y luego se reproyecta a EPSG:4326.
    
    Parámetros
    ----------
    dem_4326 : np.ndarray (2D)
        Modelo digital de elevación en EPSG:4326 (grados decimales).
    transform_4326 : affine.Affine
        Transformación afín del DEM en EPSG:4326.
    gdf : gpd.GeoDataFrame
        GeoDataFrame del área de estudio. Se utiliza para determinar automáticamente
        la zona UTM apropiada.
    nodata : float, int, None, optional
        Valor NoData del DEM. Si es None, se asume -9999.
    metodo : str, optional
        Método de cálculo del factor L:
        - 'desmet_govers': Desmet & Govers (1996) - recomendado para análisis distribuido
        - 'moore_burch': Moore & Burch (1986) - método clásico simplificado
    validar : bool, optional
        Si True, realiza validación de rangos físicos y emite advertencias.
    
    Retorna
    -------
    LS_4326 : np.ndarray (2D)
        Factor LS en EPSG:4326, con la misma forma que dem_4326.
    diagnostico : dict
        Diccionario con estadísticas y metadatos del cálculo:
        - metodo: método utilizado
        - utm_crs: sistema de coordenadas UTM empleado
        - resolucion_m: resolución espacial en metros
        - latitud_centro: latitud del centroide del área de estudio
        - ls_mean, ls_median, ls_p95, ls_max: estadísticas del factor LS
        - slope_mean_deg, slope_max_deg: estadísticas de pendiente
        - flow_acc_max: acumulación de flujo máxima
    
    Referencias
    -----------
    Desmet, P.J.J., Govers, G. (1996). A GIS procedure for automatically calculating
    the USLE LS factor on topographically complex landscape units.
    Journal of Soil and Water Conservation, 51(5), 427-433.
    
    Moore, I.D., Burch, G.J. (1986). Physical basis of the length-slope factor in the
    Universal Soil Loss Equation. Soil Science Society of America Journal, 50(5), 1294-1298.
    
    Renard, K.G., Foster, G.R., Weesies, G.A., McCool, D.K., Yoder, D.C. (1997).
    Predicting soil erosion by water: a guide to conservation planning with the
    Revised Universal Soil Loss Equation (RUSLE). USDA Agriculture Handbook No. 703.
    """
    
    logger.info("="*60)
    logger.info("Iniciando cálculo del factor LS")
    logger.info("="*60)
    logger.info(f"Método seleccionado: {metodo}")
    logger.info(f"Validación de rangos: {'activada' if validar else 'desactivada'}")
    
    # Determinar CRS métrico (UTM) automáticamente
    logger.info("Determinando sistema de coordenadas UTM apropiado")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        gdf_centroid = gdf.to_crs("EPSG:4326").geometry.centroid.iloc[0]
    
    lat_centro = gdf_centroid.y
    lon_centro = gdf_centroid.x
    
    utm_crs = gdf.to_crs(gdf.estimate_utm_crs()).crs
    logger.info(f"CRS métrico seleccionado: {utm_crs}")
    logger.info(f"Centroide del área de estudio: lat={lat_centro:.4f}, lon={lon_centro:.4f}")
    
    # Reproyectar DEM a UTM
    logger.info("Reproyectando DEM de EPSG:4326 a coordenadas métricas")
    height_4326, width_4326 = dem_4326.shape
    bounds_4326 = rasterio.transform.array_bounds(height_4326, width_4326, transform_4326)
    
    logger.debug(f"Dimensiones DEM original: {height_4326} x {width_4326} píxeles")
    logger.debug(f"Límites geográficos: {bounds_4326}")
    
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
    logger.info(f"Reproyección completada: {height_utm} x {width_utm} píxeles")
    logger.info(f"Resolución espacial: {cell_size_m:.2f} m")
    
    # Crear objetos ViewFinder y Raster para pysheds
    logger.debug("Creando objetos ViewFinder y Raster para análisis hidrológico")
    viewfinder = ViewFinder(
        shape=(height_utm, width_utm),
        mask=np.ones((height_utm, width_utm), dtype=bool),
        nodata=nodata if nodata is not None else -9999,
        affine=transform_utm,
        crs=utm_crs
    )
    
    dem_raster = Raster(dem_utm, viewfinder)
    
    # Procesamiento hidrológico con pysheds
    logger.info("Iniciando análisis hidrológico")
    logger.debug("Paso 1/3: Rellenando depresiones (fill_depressions)")
    
    grid = sGrid.from_raster(dem_raster)
    
    # Rellenar depresiones para garantizar drenaje continuo
    dem_filled = grid.fill_depressions(dem_raster)
    
    logger.debug("Paso 2/3: Resolviendo áreas planas (resolve_flats)")
    dem_inflated = grid.resolve_flats(dem_filled)
    
    # Calcular dirección de flujo usando algoritmo D8
    logger.debug("Paso 3/3: Calculando dirección de flujo (D8)")
    fdir = grid.flowdir(dem_inflated, routing='d8')
    
    # Calcular acumulación de flujo (número de celdas que drenan a cada celda)
    logger.info("Calculando acumulación de flujo")
    flow_acc = grid.accumulation(fdir, routing='d8')
    flow_acc = np.array(flow_acc).astype(np.float64)
    
    # Convertir acumulación de flujo a área contribuyente en m²
    # Nota: A_upslope representa el área contribuyente aguas arriba por unidad de ancho,
    # conceptualmente equivalente a la longitud de ladera (Desmet & Govers, 1996)
    A_upslope = flow_acc * cell_size_m**2
    A_upslope = np.clip(A_upslope, cell_size_m**2, None)
    
    logger.info(f"Acumulación de flujo máxima: {np.max(flow_acc):.0f} celdas")
    logger.info(f"Área contribuyente máxima: {np.max(A_upslope):.0f} m²")
    
    # Calcular pendiente usando gradiente numérico
    logger.info("Calculando pendiente del terreno")
    dy, dx = np.gradient(dem_utm, cell_size_m, cell_size_m)
    
    # Pendiente en radianes, grados y porcentaje
    slope_rad = np.arctan(np.sqrt(dx**2 + dy**2))
    slope_deg = np.degrees(slope_rad)
    slope_pct = np.tan(slope_rad) * 100
    
    # Limitar pendiente mínima para evitar divisiones por cero
    slope_pct = np.clip(slope_pct, 0.01, 100)
    
    logger.info(f"Pendiente media: {np.nanmean(slope_deg):.2f} grados ({np.nanmean(slope_pct):.2f}%)")
    logger.info(f"Pendiente máxima: {np.nanmax(slope_deg):.2f} grados ({np.nanmax(slope_pct):.2f}%)")
    
    # Cálculo del factor LS según el método seleccionado
    logger.info(f"Calculando factor LS con método: {metodo}")
    
    if metodo == 'desmet_govers':
        logger.debug("Aplicando formulación de Desmet & Govers (1996)")
        
        # Calcular exponente m según McCool et al. (1989)
        # m varía con la pendiente para reflejar el cambio de erosión laminar a en surcos
        beta = (np.sin(slope_rad) / 0.0896) / (3.0 * np.sin(slope_rad)**0.8 + 0.56)
        m = beta / (1 + beta)
        
        # Aplicar límites físicos razonables al exponente m
        m = np.clip(m, 0.2, 0.6)
        
        logger.debug(f"Exponente m: media={np.nanmean(m):.3f}, rango=[{np.nanmin(m):.3f}, {np.nanmax(m):.3f}]")
        
        # Factor L según ecuación 4 de Desmet & Govers (1996)
        # Representa el efecto de la longitud de ladera en la erosión
        L = ((A_upslope + cell_size_m**2)**(m + 1) - A_upslope**(m + 1)) / \
            (cell_size_m**(m + 2) * (m + 1) * (22.13**m))
        
        # Factor S según RUSLE (Renard et al., 1997)
        # Representa el efecto de la pendiente en la erosión
        # Se utilizan tres rangos de pendiente con ecuaciones específicas
        S = np.where(slope_pct < 9,
                     10.8 * np.sin(slope_rad) + 0.03,
                     np.where(slope_pct < 50,
                              16.8 * np.sin(slope_rad) - 0.50,
                              21.91 * np.sin(slope_rad) - 0.96))
        
    elif metodo == 'moore_burch':
        logger.debug("Aplicando formulación de Moore & Burch (1986)")
        
        # Exponente m simplificado basado en rangos de pendiente
        m = np.where(slope_pct < 1, 0.2,
             np.where(slope_pct < 3, 0.3,
             np.where(slope_pct < 5, 0.4, 0.5)))
        
        logger.debug(f"Exponente m: media={np.nanmean(m):.3f}")
        
        # Área contribuyente específica (m²/m = m lineales)
        A_s = A_upslope / cell_size_m
        
        # Factor L según Moore & Burch (1986)
        L = (A_s / 22.13) ** m
        
        # Factor S según McCool et al. (1987)
        S = np.where(slope_pct < 9,
                     10.8 * np.sin(slope_rad) + 0.03,
                     16.8 * np.sin(slope_rad) - 0.50)
    else:
        logger.error(f"Método '{metodo}' no reconocido")
        raise ValueError(f"Método '{metodo}' no reconocido. Opciones válidas: 'desmet_govers', 'moore_burch'")
    
    # Combinar factores L y S
    logger.debug("Combinando factores L y S")
    LS_utm = L * S
    
    # Limpieza de valores no finitos
    LS_utm = np.where(np.isfinite(LS_utm), LS_utm, 0)
    
    # Filtrar outliers extremos usando percentil 99.9
    # Esto evita que valores anómalos (ej. artefactos en cauces) distorsionen el análisis
    p999 = np.nanpercentile(LS_utm, 99.9)
    valores_filtrados = np.sum(LS_utm > p999)
    if valores_filtrados > 0:
        logger.debug(f"Filtrando {valores_filtrados} píxeles con LS > P99.9 ({p999:.2f})")
    LS_utm = np.clip(LS_utm, 0, p999)
    
    # Calcular estadísticas del factor LS en coordenadas UTM
    ls_mean = np.nanmean(LS_utm)
    ls_median = np.nanmedian(LS_utm)
    ls_p95 = np.nanpercentile(LS_utm, 95)
    ls_max = np.nanmax(LS_utm)
    
    logger.info("Estadísticas del factor LS (coordenadas UTM):")
    logger.info(f"  Media:    {ls_mean:.4f}")
    logger.info(f"  Mediana:  {ls_median:.4f}")
    logger.info(f"  P95:      {ls_p95:.2f}")
    logger.info(f"  Máximo:   {ls_max:.2f}")
    
    # Validación de rangos físicos
    if validar:
        logger.info("Ejecutando validación de rangos físicos")
        advertencias = []
        
        if ls_mean < 0.1:
            advertencias.append("LS medio muy bajo (< 0.1) - terreno extremadamente plano")
        
        if ls_mean > 20:
            advertencias.append("LS medio muy alto (> 20) - revisar calidad del DEM o extensión del área")
        
        if ls_max > 100:
            advertencias.append(f"LS máximo = {ls_max:.1f} (> 100) - posibles artefactos en cauces o áreas de concentración")
        
        pct_alto = np.sum(LS_utm > 50) / LS_utm.size * 100
        if pct_alto > 5:
            advertencias.append(f"{pct_alto:.1f}% de píxeles con LS > 50 (inusualmente alto)")
        
        if advertencias:
            logger.warning("Se detectaron las siguientes anomalías:")
            for adv in advertencias:
                logger.warning(f"  - {adv}")
        else:
            logger.info("Validación completada: rangos dentro de lo esperado")
    
    # Reproyectar LS de vuelta a EPSG:4326
    logger.info("Reproyectando factor LS a EPSG:4326")
    
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
    
    logger.info(f"Reproyección completada: media LS (EPSG:4326) = {np.nanmean(LS_4326):.4f}")
    
    # Preparar diccionario de diagnóstico
    diagnostico = {
        'metodo': metodo,
        'utm_crs': str(utm_crs),
        'resolucion_m': float(cell_size_m),
        'latitud_centro': float(lat_centro),
        'longitud_centro': float(lon_centro),
        'ls_mean': float(ls_mean),
        'ls_median': float(ls_median),
        'ls_p95': float(ls_p95),
        'ls_max': float(ls_max),
        'slope_mean_deg': float(np.nanmean(slope_deg)),
        'slope_max_deg': float(np.nanmax(slope_deg)),
        'flow_acc_max': float(np.max(flow_acc)),
        'pixeles_totales': int(LS_utm.size),
        'pixeles_validos': int(np.sum(LS_utm > 0))
    }
    
    logger.info("="*60)
    logger.info("Cálculo del factor LS completado")
    logger.info("="*60)
    
    return LS_4326, diagnostico