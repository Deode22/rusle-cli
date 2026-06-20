# RUSLE Erosion Analysis (CLI + Docker)

> Cálculo distribuido de pérdida media anual de suelo (RUSLE) integrando teledetección, topografía y datos edáficos abiertos — con salida en GeoTIFF, escenarios e informe PDF automático.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)
![GDAL](https://img.shields.io/badge/GDAL-OSGeo-5CAE58)
![License](https://img.shields.io/badge/License-MIT-green)

Herramienta de línea de comandos para el **cálculo distribuido de la pérdida media anual de suelo** mediante la ecuación **RUSLE**. Integra **teledetección (Sentinel‑2)**, **topografía (MDT/DEM)** y **propiedades del suelo (SoilGrids)** para generar mapas raster (GeoTIFF), escenarios de cobertura y un informe técnico en PDF.

---

## Quickstart

```bash
# 1. Clona y construye
git clone https://github.com/deode22/rusle-cli.git && cd rusle-cli
docker build -t rusle-app .

# 2. Crea tu .env con credenciales Sentinel Hub / CDS (ver sección 2)

# 3. Ejecuta sobre tu área de estudio
docker run --rm --env-file .env \
  -v "$PWD/layers:/app/layers" -v "$PWD/output:/app/output" \
  rusle-app -c /app/layers/area.gpkg -o /app/output
```

---

## Outputs

| Salida | Descripción |
|--------|-------------|
| `rusle_A.tif` | Pérdida de suelo media anual \[t/ha/año] |
| `factor_*.tif` | Rásteres individuales R, K, LS, C, P |
| `escenarios/` | Proyecciones de erosión bajo distintas coberturas (C) |
| `informe.pdf` | Informe técnico automático con mapas y estadísticas |

---

## ¿Qué demuestra este proyecto?
- **Data engineering geoespacial end‑to‑end**: ingesta vía API → procesamiento raster distribuido → salida + reporting.
- Integración de múltiples fuentes abiertas (Sentinel‑2, SoilGrids, DEM, servicios climáticos).
- Análisis hidrológico (`pysheds`), implementación de fórmulas empíricas y empaquetado reproducible con **Docker**.

> **Alcance:** Análisis **preliminar** para identificar niveles de riesgo de erosión a escala de paisaje con datos abiertos y teledetección. Los resultados **no sustituyen** datos *in situ* ni la calibración local; interprétense como aproximación para priorizar zonas de actuación.

---

## 1. Modelo y fundamento teórico

La aplicación automatiza el cálculo de la pérdida media anual de suelo ($A$) según:

$$A = R \cdot K \cdot LS \cdot C \cdot P$$

- **A** — Pérdida de suelo media anual \[t/ha/año].
- **R** — Erosividad de la lluvia (servicios climáticos WMS / CDS API).
- **K** — Erodibilidad del suelo (fórmula EPIC, Williams et al. 1990; textura + carbono orgánico de SoilGrids).
- **LS** — Factor topográfico (longitud y pendiente) derivado de DEM mediante análisis hidrológico.
- **C** — Gestión de cobertura, estimada desde NDVI (Sentinel‑2) por formulación exponencial.
- **P** — Prácticas de conservación (por defecto `1.0`).

## 2. Configuración de credenciales (Sentinel Hub / CDS)

Crea un archivo `.env` en la raíz del proyecto:

```env
CLIENT_ID="sh-##################"
CLIENT_SECRET="##############################"
```

## 3. Metodología implementada

### Factor LS (Topografía)
- **Pre-procesamiento:** acondicionamiento hidrológico del DEM con `pysheds` (relleno de depresiones, dirección de flujo D8, acumulación).
- **Componente L:** algoritmo de **Desmet & Govers (1996)** (área contribuyente unitaria).
- **Componente S:** formulación segmentada de **Renard et al. (1997)** (RUSLE).

### Factor C (Cobertura vegetal)
- **NDVI** como *proxy* de densidad de vegetación (Sentinel‑2 L2A).
- **Filtrado de calidad:** máscara **SCL** (nubes, sombras, nieve).
- **Conversión:** función exponencial de **Van der Knijff et al. (2000)**.

### Factor K (Erodibilidad)
- Fórmula **EPIC completa** (Williams et al., 1990) a partir de SoilGrids.

## 4. Uso de la CLI

Punto de entrada: `main.py`.

### 4.1. Área de estudio (obligatorio elegir una opción)
- `-c, --capa` — ruta a archivo vectorial (GPKG, SHP, GeoJSON).
- `--coordenadas, -coords` — `LAT LON` que definen el centro (requiere `--lado-bbox`).
- `--lado-bbox, --lado` — lado del cuadrado de análisis en metros (con `--coordenadas`).

### 4.2. Salida y escenarios
- `-o, --output` — carpeta de resultados (por defecto, en Descargas).
- `-fc, --factor-c` — genera escenarios de evolución:
  - Sin valores: automáticos (C·0.5 y C·0.1).
  - Dos valores (`0.1 0.02`): C fijos medio/largo plazo.
  - Guion bajo (`_ 0.01`): primer escenario automático, segundo fijo.

### 4.3. Overrides manuales
- `-cr, --cambio-r` · `-ck, --cambio-k` · `-cls, --cambio-ls` · `-cc, --cambio-c` — valor constante para todo el área.
- `-p, --factor-p` — Factor P (por defecto `1.0`).

## 5. Despliegue con Docker

Imagen base: `ghcr.io/osgeo/gdal`.

```bash
# Construcción
docker build -t rusle-app .

# Ejecución
docker run --rm \
  --env-file .env \
  -v "$PWD/layers:/app/layers" \
  -v "$PWD/output:/app/output" \
  rusle-app \
  -c /app/layers/area.gpkg \
  -o /app/output
```

## 6. Referencias

- **Desmet, P. J. J., & Govers, G. (1996).** A GIS procedure for automatically calculating the USLE LS factor… *J. Soil Water Conserv., 51*(5), 427–433.
- **McCool, D. K., et al. (1989).** Revised slope length factor for the USLE. *Trans. ASAE, 32*(5), 1571–1576.
- **Renard, K. G., et al. (1997).** *Predicting soil erosion by water… (RUSLE)* (Agriculture Handbook 703). USDA.
- **Van der Knijff, J. M., Jones, R. J. A., & Montanarella, L. (2000).** *Soil erosion risk assessment in Europe* (EUR 19044 EN).
- **Williams, J. R., Jones, C. A., & Dyke, P. T. (1990).** The EPIC model.

---

## 📄 Licencia
MIT — ver [`LICENSE`](LICENSE).
