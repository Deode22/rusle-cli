# RUSLE Erosion Analysis (CLI + Docker)

Herramienta para el **cálculo distribuido de pérdida media anual de suelo** mediante la ecuación **RUSLE**. Integra **teledetección (Sentinel‑2)**, **topografía (MDT/DEM)** y **propiedades del suelo (SoilGrids)** para generar mapas raster (GeoTIFF), escenarios de cobertura y un informe técnico en PDF.

> **Nota sobre el alcance:** El objetivo de esta aplicación es proporcionar un **análisis preliminar** para la identificación de niveles de riesgo de erosión a escala de paisaje mediante el uso de bases de datos abiertas y teledetección. Los resultados obtenidos **no sustituyen** la precisión de los datos tomados *in situ* ni la calibración local de fórmulas empíricas, debiendo interpretarse como una aproximación para la priorización de zonas de actuación.

## 1. Modelo y fundamento teórico

La aplicación automatiza el cálculo de la pérdida media anual de suelo ($A$) según la fórmula:

$$A = R \cdot K \cdot LS \cdot C \cdot P$$

**Componentes:**
- **A**: Pérdida de suelo media anual \[t/ha/año\].
- **R**: Erosividad de la lluvia. Obtenida mediante servicios climáticos (WMS / CDS API).
- **K**: Erodibilidad del suelo. Calculada mediante la fórmula EPIC (Williams et al., 1990) utilizando datos de textura y carbono orgánico de SoilGrids.
- **LS**: Factor topográfico (longitud y pendiente de ladera). Derivado de Modelos Digitales de Elevación (DEM) mediante análisis hidrológico.
- **C**: Gestión de cobertura. Estimada a partir del índice NDVI (Sentinel‑2) mediante formulación exponencial.
- **P**: Prácticas de conservación. Valor por defecto `1.0` (sin prácticas específicas).

## 2. Configuración de credenciales (Sentinel Hub / CDS)

Para la descarga y procesamiento de imágenes satelitales y datos climáticos, la aplicación requiere autenticación mediante un archivo de entorno.

Es necesario crear un archivo llamado `.env` en la raíz del proyecto con el siguiente formato:

```env
CLIENT_ID="sh-##################"
CLIENT_SECRET="##############################"
```

## 3. Metodología implementada

### Factor LS (Topografía)
- **Pre-procesamiento:** Acondicionamiento hidrológico del DEM con `pysheds` (relleno de depresiones, dirección de flujo D8 y acumulación).
- **Componente L:** Algoritmo de **Desmet & Govers (1996)** basado en el área contribuyente unitaria.
- **Componente S:** Formulación segmentada de **Renard et al. (1997)** (RUSLE).

### Factor C (Cobertura vegetal)
- Uso de **NDVI** como *proxy* de la densidad de vegetación (Sentinel‑2 L2A).
- **Filtrado de calidad:** Aplicación de máscara **SCL** para eliminar nubes, sombras y nieve.
- **Conversión:** Aplicación de la función exponencial de **Van der Knijff et al. (2000)**.

### Factor K (Erodibilidad)
- Implementación de la fórmula **EPIC completa** (Williams et al., 1990) a partir de datos de SoilGrids.

## 4. Uso de la Interfaz de Línea de Comandos (CLI)

El punto de entrada principal es el script `main.py`.

### 4.1. Argumentos de entrada y área de estudio
Es obligatorio definir el área de estudio mediante una de estas dos opciones:
- `-c, --capa`: Ruta a un archivo vectorial (GPKG, SHP, GeoJSON).
- `--coordenadas, -coords`: Dos valores numéricos (`LAT` `LON`) que definen el centro del análisis. Requiere el uso de `--lado-bbox`.
- `--lado-bbox, --lado`: Longitud en metros del lado del cuadrado de análisis (requerido con `--coordenadas`).

### 4.2. Argumentos de salida y escenarios
- `-o, --output`: Ruta de la carpeta donde se almacenarán los resultados. Si no se especifica, se crea una carpeta en la ruta de descargas del sistema.
- `-fc, --factor-c`: Genera escenarios de evolución de la erosión. 
    - Sin valores: Calcula escenarios automáticos (C actual * 0.5 y C actual * 0.1).
    - Con dos valores (ej. `0.1 0.02`): Define valores fijos de C para medio y largo plazo.
    - Con guion bajo (ej. `_ 0.01`): Mantiene el cálculo automático para el primer escenario y fija el segundo.

### 4.3. Argumentos de ajuste manual (Overrides)
Permiten omitir el cálculo automático y asignar valores constantes a toda el área de estudio:
- `-cr, --cambio-r`: Asigna un valor manual al Factor R (Erosividad).
- `-ck, --cambio-k`: Asigna un valor manual al Factor K (Erodibilidad).
- `-cls, --cambio-ls`: Asigna un valor manual al Factor LS (Topografía).
- `-cc, --cambio-c`: Asigna un valor manual al Factor C (Cobertura).
- `-p, --factor-p`: Define el valor del Factor P (Prácticas de conservación). Por defecto es `1.0`.

## 5. Despliegue con Docker

El repositorio incluye un `Dockerfile` basado en la imagen `ghcr.io/osgeo/gdal`.

### 5.1. Construcción de la imagen
```bash
docker build -t rusle-app .
```

### 5.2. Ejecución del contenedor
```bash
docker run --rm \
  --env-file .env \
  -v "$PWD/layers:/app/layers" \
  -v "$PWD/output:/app/output" \
  rusle-app \
  -c /app/layers/area.gpkg \
  -o /app/output
```

## 6. Referencias bibliográficas

- **Desmet, P. J. J., & Govers, G. (1996).** A GIS procedure for automatically calculating the USLE LS factor on topographically complex landscape units. *Journal of Soil and Water Conservation, 51*(5), 427–433.
- **McCool, D. K., Foster, G. R., Mutchler, C. K., & Meyer, L. D. (1989).** Revised slope length factor for the Universal Soil Loss Equation. *Transactions of the ASAE, 32*(5), 1571–1576.
- **Renard, K. G., et al. (1997).** *Predicting soil erosion by water: A guide to conservation planning with the Revised Universal Soil Loss Equation (RUSLE)* (Agriculture Handbook No. 703). USDA.
- **Van der Knijff, J. M., Jones, R. J. A., & Montanarella, L. (2000).** *Soil erosion risk assessment in Europe* (EUR 19044 EN). Office for Official Publications of the European Communities.
- **Williams, J. R., Jones, C. A., & Dyke, P. T. (1990).** The EPIC model. In *EPIC — Erosion/Productivity Impact Calculator*.
