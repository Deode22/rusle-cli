#### 1. Descripción General
Este módulo implementa el cálculo del factor **C** (Gestión de Cubiertas y Manejo) de la ecuación USLE/RUSLE a partir de datos de teledetección (Sentinel-2). El factor C cuantifica la eficacia de la vegetación y las prácticas de manejo en la reducción de la erosión del suelo en comparación con una parcela en barbecho continuo. En este flujo de trabajo, se utiliza el Índice de Vegetación de Diferencia Normalizada (**NDVI**) como *proxy* de la densidad de biomasa y la cobertura del suelo.

#### 2. Justificación Metodológica y Ecuaciones

La relación entre la cobertura vegetal y la pérdida de suelo no es lineal. En ecosistemas forestales, zonas desarboladas y áreas de repoblación, una pequeña cantidad de cobertura inicial (herbácea o arbustiva) proporciona una protección desproporcionadamente alta contra el impacto de las gotas de lluvia (*splash erosion*). A medida que la vegetación se densifica, el efecto protector adicional disminuye hasta estabilizarse.

##### 2.1. Método Exponencial (Van der Knijff et al., 2000)
Se ha implementado como metodología preferente la función exponencial propuesta por **Van der Knijff et al. (2000)**, diseñada específicamente para la evaluación del riesgo de erosión a escala regional en Europa. Esta fórmula captura la sensibilidad de las primeras etapas de colonización vegetal, siendo ideal para monitorizar el éxito de **repoblaciones forestales** y la provisión de **servicios ecosistémicos** de regulación hídrica.

La ecuación aplicada es:

$$C = \exp\left(-\alpha \cdot \frac{\text{NDVI}}{\beta - \text{NDVI}}\right)$$

Donde:
- $\alpha = 2$: Parámetro de forma que determina la curvatura de la relación.
- $\beta = 1$: Parámetro de escala que define el límite superior del NDVI.
- El rango de salida se restringe estrictamente a $[0.001, 1.0]$ para mantener la coherencia física del modelo.

##### 2.2. Método Lineal (Alternativo)
Para comparativas con estudios locales previos, se incluye una formulación lineal empírica:

$$C = 0.431 - 0.805 \cdot \text{NDVI}$$

*Nota: Este método presenta limitaciones en zonas de alta densidad vegetal (NDVI > 0.53), donde puede generar valores negativos si no se aplica un truncamiento de datos.*

#### 3. Procesamiento de Datos Sentinel-2
Para asegurar que el factor C refleje la realidad del terreno, el script integra:
1.  **Máscara de Calidad (SCL):** Filtrado automático de nubes, sombras de nubes y nieve mediante la capa *Scene Classification* de Sentinel-2 L2A.
2.  **Mosaico de Mínima Nubosidad:** Selección del píxel más limpio dentro de una ventana temporal (ej. 90 días) para evitar artefactos atmosféricos.
3.  **Recorte Geométrico:** Uso de máscaras vectoriales para asegurar que las estadísticas del factor C correspondan exclusivamente a la geometría del área de estudio.

#### 4. Referencias Bibliográficas (APA 7ª Edición)

Almagro, A., Thomé, T. C., Colman, C. B., Pereira, R. B., Marcato Junior, J., Rodrigues, D. B. B., & Oliveira, P. T. S. (2019). Improving RS-based restoration monitoring of the Revised Universal Soil Loss Equation (RUSLE) C-factor. *Remote Sensing, 11*(11), 1329. https://doi.org/10.3390/rs11111329

Durigon, V. L., Carvalho, D. F., Antunes, M. A. H., Oliveira, P. T. S., & Fernandes, M. M. (2014). NDVI time series for monitoring RUSLE cover management factor in a tropical watershed. *International Journal of Remote Sensing, 35*(2), 441–453. https://doi.org/10.1080/01431161.2013.871081

Van der Knijff, J. M., Jones, R. J. A., & Montanarella, L. (2000). *Soil erosion risk assessment in Europe* (EUR 19044 EN). Office for Official Publications of the European Communities.