FROM ghcr.io/osgeo/gdal:ubuntu-small-3.8.0

WORKDIR /app

# Instalar Python y dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements e instalar dependencias Python
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copiar código fuente
COPY *.py ./

# Crear directorio para outputs
RUN mkdir -p /data/output

# Punto de entrada
ENTRYPOINT ["python3", "main.py"]
CMD ["--help"]
