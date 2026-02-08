import os
import sys

venv_proj_path = r"C:\Users\danie\Documents\repos\rusle\.venv\lib\site-packages\pyproj\proj_dir\share\proj"
os.environ['PROJ_LIB'] = venv_proj_path
os.environ['PROJ_DATA'] = venv_proj_path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import geopandas as gpd
from modules.get_K import factor_K_williams

def test_factor_K(capa_path: str, depth: str = "0-5cm", stat: str = "mean"):
    print("=" * 60)
    print("TEST: FACTOR K (Erodibilidad del suelo)")
    print("=" * 60)
    
    print(f"\nCargando capa: {capa_path}")
    gdf = gpd.read_file(capa_path)
    
    print(f"CRS: {gdf.crs}")
    print(f"Número de geometrías: {len(gdf)}")
    print(f"Bounds: {gdf.total_bounds}")
    print(f"Profundidad: {depth}")
    print(f"Estadística: {stat}")
    
    print("\nCalculando Factor K...")
    try:
        k_result = factor_K_williams(gdf, depth=depth, stat=stat)
        
        K_array = k_result['K']
        K_profile = k_result['profile']
        
        print("\n" + "─" * 60)
        print("RESULTADOS")
        print("─" * 60)
        print(f"Shape del array K: {K_array.shape}")
        print(f"CRS: {K_profile['crs']}")
        print(f"\nEstadísticas del Factor K:")
        print(f"  - Media: {np.nanmean(K_array):.4f} t·h/(MJ·mm)")
        print(f"  - Mediana: {np.nanmedian(K_array):.4f} t·h/(MJ·mm)")
        print(f"  - Mínimo: {np.nanmin(K_array):.4f} t·h/(MJ·mm)")
        print(f"  - Máximo: {np.nanmax(K_array):.4f} t·h/(MJ·mm)")
        print(f"  - Desv. Est.: {np.nanstd(K_array):.4f} t·h/(MJ·mm)")
        
        K_mean = np.nanmean(K_array)
        print("\nInterpretación:")
        if K_mean < 0.02:
            print("  - Erodibilidad MUY BAJA (suelos muy resistentes)")
        elif K_mean < 0.03:
            print("  - Erodibilidad BAJA")
        elif K_mean < 0.04:
            print("  - Erodibilidad MODERADA")
        elif K_mean < 0.05:
            print("  - Erodibilidad ALTA")
        else:
            print("  - Erodibilidad MUY ALTA (suelos muy susceptibles)")
        
        print("\n✓ Test completado exitosamente")
        return k_result
        
    except Exception as e:
        print(f"\n✗ Error en el cálculo: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python test_factor_K.py <ruta_capa_vectorial> [depth] [stat]")
        print("Ejemplo: python test_factor_K.py ../data/mi_parcela.gpkg 0-5cm mean")
        print("\nProfundidades disponibles: 0-5cm, 5-15cm, 15-30cm, 30-60cm, 60-100cm, 100-200cm")
        print("Estadísticas disponibles: mean, Q0.05, Q0.5, Q0.95, uncertainty")
        sys.exit(1)
    
    capa = sys.argv[1]
    depth = sys.argv[2] if len(sys.argv) > 2 else "0-5cm"
    stat = sys.argv[3] if len(sys.argv) > 3 else "mean"
    
    test_factor_K(capa, depth, stat)
