# testing/test_proj_config.py
import os

venv_proj_path = r"C:\Users\danie\Documents\repos\rusle\.venv\lib\site-packages\pyproj\proj_dir\share\proj"

# Forzamos a GDAL y PROJ a usar esa ruta
os.environ['PROJ_LIB'] = venv_proj_path
os.environ['PROJ_DATA'] = venv_proj_path # Para versiones más nuevas de PROJ

import sys

print("=" * 60)
print("TEST 1: Configuración de PROJ/GDAL")
print("=" * 60)

# Verificar variables de entorno ANTES de importar nada
print("\n--- Variables de entorno actuales ---")
print(f"PROJ_LIB: {os.environ.get('PROJ_LIB', 'NO DEFINIDA')}")
print(f"PROJ_DATA: {os.environ.get('PROJ_DATA', 'NO DEFINIDA')}")
print(f"GDAL_DATA: {os.environ.get('GDAL_DATA', 'NO DEFINIDA')}")

# Verificar PATH
print("\n--- Rutas en PATH que contienen 'postgres' ---")
path_entries = os.environ.get('PATH', '').split(os.pathsep)
postgres_paths = [p for p in path_entries if 'postgres' in p.lower()]
if postgres_paths:
    for p in postgres_paths:
        print(f"  ⚠️  {p}")
else:
    print("  ✓ No se encontraron rutas de PostgreSQL en PATH")

# Ahora importar pyproj
print("\n--- Importando pyproj ---")
import pyproj
print(f"✓ pyproj version: {pyproj.__version__}")
print(f"✓ Ruta de datos de PROJ (pyproj): {pyproj.datadir.get_data_dir()}")

# Verificar que existe proj.db
proj_db_path = os.path.join(pyproj.datadir.get_data_dir(), 'proj.db')
if os.path.exists(proj_db_path):
    print(f"✓ proj.db encontrado en: {proj_db_path}")
else:
    print(f"✗ proj.db NO encontrado en: {proj_db_path}")

print("\n" + "=" * 60)