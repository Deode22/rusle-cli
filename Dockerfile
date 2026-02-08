FROM ghcr.io/osgeo/gdal:ubuntu-small-3.9.2

WORKDIR /app

# Actualizar sistema e instalar dependencias
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    python3-venv \
    proj-bin \
    libproj-dev \
    && rm -rf /var/lib/apt/lists/

# Copiar requirements e instalar dependencias Python
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copiar código de la aplicación
COPY main.py .
COPY modules/ ./modules/

# Crear directorios de trabajo
RUN mkdir -p /app/data /app/output /app/layers

# Variables de entorno para PROJ y GDAL
ENV PROJ_LIB=/usr/share/proj
ENV GDAL_DATA=/usr/share/gdal

ENTRYPOINT ["python3", "main.py"]
CMD ["--help"]