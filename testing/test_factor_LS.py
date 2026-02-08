import os
import sys

venv_proj_path = r"C:\Users\danie\Documents\repos\rusle\.venv\lib\site-packages\pyproj\proj_dir\share\proj"
os.environ['PROJ_LIB'] = venv_proj_path
os.environ['PROJ_DATA'] = venv_proj_path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import geopandas as gpd
from modules.get_mdt import obtener_mdt
from modules.calc_LS import calcular_LS

def test_factor_LS(capa_path: str, metodo: str = 'desmet_govers', validar: bool = True):
    print("=" * 60)
    print("TEST: FACTOR LS (Topografía - Longitud y Pendiente)")
    print("=" * 60)
    
    print(f"\nCargando capa: {capa_path}")
    gdf = gpd.read_file(capa_path)
    
    print(f"CRS: {gdf.crs}")
    print(f"Número de geometrías: {len(gdf)}")
    print(f"Bounds: {gdf.total_bounds}")
    print(f"Método: {metodo}")
    print(f"Validación: {validar}")
    
    print("\nObteniendo MDT...")
    try:
        mdt_result = obtener_mdt(capa_path)
        elevation = mdt_result['data']
        mdt_transform = mdt_result['transform']
        mdt_crs = mdt_result['crs']
        
        print(f"MDT obtenido - Shape: {elevation.shape}")
        print(f"Elevación - Min: {np.nanmin(elevation):.2f}m, Max: {np.nanmax(elevation):.2f}m")
        
        print("\nCalculando Factor LS...")
        LS_array, diagnostico = calcular_LS(
            elevation,
            mdt_transform,
            gdf,
            nodata=None,
            metodo=metodo,
            validar=validar
        )
        
        print("\n" + "─" * 60)
        print("RESULTADOS")
        print("─" * 60)
        print(f"Shape del array LS: {LS_array.shape}")
        print(f"\nEstadísticas del Factor LS:")
        print(f"  - Media: {np.nanmean(LS_array):.4f}")
        print(f"  - Mediana: {np.nanmedian(LS_array):.4f}")
        print(f"  - Mínimo: {np.nanmin(LS_array):.4f}")
        print(f"  - Máximo: {np.nanmax(LS_array):.4f}")
        print(f"  - Desv. Est.: {np.nanstd(LS_array):.4f}")
        
        if diagnostico:
            print("\nDiagnóstico:")
            for key, value in diagnostico.items():
                if isinstance(value, (int, float)):
                    print(f"  - {key}: {value:.4f}")
                else:
                    print(f"  - {key}: {value}")
        
        LS_mean = np.nanmean(LS_array)
        print("\nInterpretación:")
        if LS_mean < 1:
            print("  - Topografía PLANA (bajo efecto de pendiente)")
        elif LS_mean < 3:
            print("  - Topografía SUAVE")
        elif LS_mean < 6:
            print("  - Topografía MODERADA")
        elif LS_mean < 10:
            print("  - Topografía PRONUNCIADA")
        else:
            print("  - Topografía MUY PRONUNCIADA (alto riesgo de erosión)")
        
        print("\n✓ Test completado exitosamente")
        return LS_array, diagnostico
        
    except Exception as e:
        print(f"\n✗ Error en el cálculo: {e}")
        import traceback
        traceback.print_exc()
        return None, None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python test_factor_LS.py <ruta_capa_vectorial> [metodo] [validar]")
        print("Ejemplo: python test_factor_LS.py ../data/mi_parcela.gpkg desmet_govers True")
        print("\nMétodos disponibles: desmet_govers, moore_burch")
        sys.exit(1)
    
    capa = sys.argv[1]
    metodo = sys.argv[2] if len(sys.argv) > 2 else "desmet_govers"
    validar = sys.argv[3].lower() == 'true' if len(sys.argv) > 3 else True
    
    test_factor_LS(capa, metodo, validar)
