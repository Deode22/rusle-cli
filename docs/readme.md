# Build
docker build -t rusle-app .

# Ejecutar (montando datos)
docker run -v /ruta/a/tus/datos:/data rusle-app -c /data/tu_archivo.gpkg -o /data/output

# Ver ayuda
docker run rusle-app --help