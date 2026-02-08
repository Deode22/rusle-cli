import os
import sys

venv_proj_path = r"C:\Users\danie\Documents\repos\rusle\.venv\lib\site-packages\pyproj\proj_dir\share\proj"
os.environ['PROJ_LIB'] = venv_proj_path
os.environ['PROJ_DATA'] = venv_proj_path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import geopandas as gpd
from modules.get_R import factorR_wms

def test_factor_R(capa_path: str):
    print("=" * 60)
    print("TEST: FACTOR R (Erosividad de la lluvia)")
    print("=" * 60)
    
    print(f"\nCargando capa: {capa_path}")
    gdf = gpd.read_file(capa_path)
    
    print(f"CRS: {gdf.crs}")
    print(f"Número de geometrías: {len(gdf)}")
    print(f"Bounds: {gdf.total_bounds}")
    
    print("\nCalculando Factor R...")
    try:
        gdf_result, factor_R = factorR_wms(gdf, debug=False)
        
        print("\n" + "─" * 60)
        print("RESULTADOS")
        print("─" * 60)
        print(f"Factor R: {factor_R:.2f} MJ·mm·ha⁻¹·h⁻¹·año⁻¹")
        print("\nInterpretación:")
        if factor_R < 500:
            print("  - Erosividad BAJA")
        elif factor_R < 1000:
            print("  - Erosividad MODERADA")
        elif factor_R < 2000:
            print("  - Erosividad ALTA")
        else:
            print("  - Erosividad MUY ALTA")
        
        print("\n✓ Test completado exitosamente")
        return factor_R
        
    except Exception as e:
        print(f"\n✗ Error en el cálculo: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python test_factor_R.py <ruta_capa_vectorial>")
        print("Ejemplo: python test_factor_R.py ../data/mi_parcela.gpkg")
        sys.exit(1)
    
    capa = sys.argv[1]
    test_factor_R(capa)
