import os
import sys

venv_proj_path = r"C:\Users\danie\Documents\repos\rusle\.venv\lib\site-packages\pyproj\proj_dir\share\proj"
os.environ['PROJ_LIB'] = venv_proj_path
os.environ['PROJ_DATA'] = venv_proj_path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import geopandas as gpd
from modules.get_C import obtener_ndvi_valido

def test_factor_C(capa_path: str, dias: int = 90, maxcc: int = 20):
    print("=" * 60)
    print("TEST: FACTOR C (Cobertura vegetal)")
    print("=" * 60)
    
    print(f"\nCargando capa: {capa_path}")
    gdf = gpd.read_file(capa_path)
    
    print(f"CRS: {gdf.crs}")
    print(f"Número de geometrías: {len(gdf)}")
    print(f"Bounds: {gdf.total_bounds}")
    print(f"Días de búsqueda: {dias}")
    print(f"Cobertura de nubes máxima: {maxcc}%")
    
    print("\nBuscando imágenes Sentinel-2 y calculando Factor C...")
    print("(Esto puede tardar varios minutos...)")
    
    try:
        fecha, ndvi, C_array, metadata, bbox = obtener_ndvi_valido(gdf, dias=dias, maxcc=maxcc)
        
        if C_array is None:
            print("\n✗ No se pudo obtener el Factor C")
            print("Posibles causas:")
            print("  - No hay imágenes disponibles en el período especificado")
            print("  - Todas las imágenes tienen demasiada cobertura de nubes")
            print("  - Error de conexión con el servicio Sentinel Hub")
            return None
        
        C_array = np.clip(C_array, 0, 1)
        
        print("\n" + "─" * 60)
        print("RESULTADOS")
        print("─" * 60)
        print(f"Fecha de la imagen: {fecha}")
        print(f"Shape del array C: {C_array.shape}")
        print(f"BBox: {bbox}")
        
        if metadata:
            print(f"\nMetadatos de la imagen:")
            for key, value in metadata.items():
                print(f"  - {key}: {value}")
        
        print(f"\nEstadísticas del NDVI:")
        print(f"  - Media: {np.nanmean(ndvi):.4f}")
        print(f"  - Mediana: {np.nanmedian(ndvi):.4f}")
        print(f"  - Mínimo: {np.nanmin(ndvi):.4f}")
        print(f"  - Máximo: {np.nanmax(ndvi):.4f}")
        
        print(f"\nEstadísticas del Factor C:")
        print(f"  - Media: {np.nanmean(C_array):.4f}")
        print(f"  - Mediana: {np.nanmedian(C_array):.4f}")
        print(f"  - Mínimo: {np.nanmin(C_array):.4f}")
        print(f"  - Máximo: {np.nanmax(C_array):.4f}")
        print(f"  - Desv. Est.: {np.nanstd(C_array):.4f}")
        
        C_mean = np.nanmean(C_array)
        print("\nInterpretación:")
        if C_mean < 0.1:
            print("  - Cobertura MUY ALTA (bosque denso, vegetación muy densa)")
            print("  - Protección excelente contra la erosión")
        elif C_mean < 0.2:
            print("  - Cobertura ALTA (bosque, pradera densa)")
            print("  - Buena protección contra la erosión")
        elif C_mean < 0.4:
            print("  - Cobertura MODERADA (cultivos, vegetación dispersa)")
            print("  - Protección moderada contra la erosión")
        elif C_mean < 0.6:
            print("  - Cobertura BAJA (cultivos en hilera, vegetación escasa)")
            print("  - Protección limitada contra la erosión")
        else:
            print("  - Cobertura MUY BAJA (suelo desnudo, vegetación muy escasa)")
            print("  - Muy vulnerable a la erosión")
        
        ndvi_mean = np.nanmean(ndvi)
        print(f"\nSalud de la vegetación (NDVI medio: {ndvi_mean:.3f}):")
        if ndvi_mean < 0.2:
            print("  - Suelo desnudo o vegetación muy escasa")
        elif ndvi_mean < 0.4:
            print("  - Vegetación escasa o estresada")
        elif ndvi_mean < 0.6:
            print("  - Vegetación moderada")
        elif ndvi_mean < 0.8:
            print("  - Vegetación saludable")
        else:
            print("  - Vegetación muy densa y saludable")
        
        print("\n✓ Test completado exitosamente")
        return C_array, ndvi, fecha, metadata
        
    except Exception as e:
        print(f"\n✗ Error en el cálculo: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python test_factor_C.py <ruta_capa_vectorial> [dias] [maxcc]")
        print("Ejemplo: python test_factor_C.py ../data/mi_parcela.gpkg 90 20")
        print("\nParámetros:")
        print("  dias: Número de días hacia atrás para buscar imágenes (default: 90)")
        print("  maxcc: Cobertura de nubes máxima en % (default: 20)")
        sys.exit(1)
    
    capa = sys.argv[1]
    dias = int(sys.argv[2]) if len(sys.argv) > 2 else 90
    maxcc = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    
    test_factor_C(capa, dias, maxcc)
