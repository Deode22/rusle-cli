# Scripts de Testing para Factores RUSLE

Esta carpeta contiene scripts individuales para probar el cálculo de cada factor de la ecuación RUSLE.

## Scripts Disponibles

### 1. test_factor_R.py - Factor R (Erosividad de la lluvia)

Calcula la erosividad de la lluvia usando datos del servicio WMS del MAPAMA.

**Uso:**
```bash
python test_factor_R.py <ruta_capa_vectorial>
```

**Ejemplo:**
```bash
python test_factor_R.py ../data/mi_parcela.gpkg
```

**Salida:**
- Valor único de Factor R en MJ·mm·ha⁻¹·h⁻¹·año⁻¹
- Interpretación del nivel de erosividad

---

### 2. test_factor_K.py - Factor K (Erodibilidad del suelo)

Calcula la erodibilidad del suelo usando la ecuación de Williams basada en datos de SoilGrids.

**Uso:**
```bash
python test_factor_K.py <ruta_capa_vectorial> [profundidad] [estadistica]
```

**Parámetros opcionales:**
- `profundidad`: 0-5cm, 5-15cm, 15-30cm, 30-60cm, 60-100cm, 100-200cm (default: 0-5cm)
- `estadistica`: mean, Q0.05, Q0.5, Q0.95, uncertainty (default: mean)

**Ejemplos:**
```bash
python test_factor_K.py ../data/mi_parcela.gpkg
python test_factor_K.py ../data/mi_parcela.gpkg 0-5cm mean
python test_factor_K.py ../data/mi_parcela.gpkg 15-30cm Q0.5
```

**Salida:**
- Array espacial del Factor K
- Estadísticas (media, mediana, min, max, desviación estándar)
- Interpretación del nivel de erodibilidad

---

### 3. test_factor_LS.py - Factor LS (Topografía)

Calcula el factor topográfico combinando longitud y pendiente usando datos del MDT.

**Uso:**
```bash
python test_factor_LS.py <ruta_capa_vectorial> [metodo] [validar]
```

**Parámetros opcionales:**
- `metodo`: desmet_govers, moore_burch (default: desmet_govers)
- `validar`: True, False (default: True)

**Ejemplos:**
```bash
python test_factor_LS.py ../data/mi_parcela.gpkg
python test_factor_LS.py ../data/mi_parcela.gpkg desmet_govers True
python test_factor_LS.py ../data/mi_parcela.gpkg moore_burch False
```

**Salida:**
- Array espacial del Factor LS
- Estadísticas del MDT (elevación min/max)
- Estadísticas del Factor LS
- Diagnóstico del cálculo
- Interpretación del nivel topográfico

---

### 4. test_factor_C.py - Factor C (Cobertura vegetal)

Calcula el factor de cobertura vegetal usando imágenes Sentinel-2 y el índice NDVI.

**Uso:**
```bash
python test_factor_C.py <ruta_capa_vectorial> [dias] [maxcc]
```

**Parámetros opcionales:**
- `dias`: Número de días hacia atrás para buscar imágenes (default: 90)
- `maxcc`: Cobertura de nubes máxima en % (default: 20)

**Ejemplos:**
```bash
python test_factor_C.py ../data/mi_parcela.gpkg
python test_factor_C.py ../data/mi_parcela.gpkg 90 20
python test_factor_C.py ../data/mi_parcela.gpkg 180 30
```

**Salida:**
- Fecha de la imagen utilizada
- Array espacial del Factor C
- Estadísticas del NDVI
- Estadísticas del Factor C
- Metadatos de la imagen
- Interpretación del nivel de cobertura vegetal

---

## Requisitos

Todos los scripts requieren:
- Python 3.x
- Dependencias instaladas (ver requirements.txt en la raíz del proyecto)
- Archivo vectorial de entrada (gpkg, shp, geojson, etc.)

## Notas

- Los scripts están configurados para usar el entorno virtual del proyecto
- Cada script incluye manejo de errores y mensajes informativos
- Los resultados incluyen interpretaciones para facilitar el análisis
- El Factor C puede tardar varios minutos debido a la descarga de imágenes satelitales
