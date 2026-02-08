#### 1. Descripción General
Este módulo implementa el cálculo distribuido del factor **LS** (Longitud y Pendiente de Ladera) para su integración en modelos de erosión hídrica como USLE, RUSLE y MUSLE. A diferencia de los métodos manuales tradicionales diseñados para parcelas experimentales, este flujo de trabajo utiliza un enfoque basado en Sistemas de Información Geográfica (SIG) para capturar la complejidad topográfica de paisajes naturales mediante el análisis de Modelos Digitales de Elevación (DEM).

#### 2. Justificación Metodológica y Ecuaciones

El factor LS representa el efecto de la topografía sobre la pérdida de suelo. El componente **L** (longitud) refleja la influencia del área acumulada aguas arriba, mientras que el componente **S** (pendiente) refleja la influencia de la inclinación del terreno en la velocidad y energía del flujo superficial.

##### 2.1. Factor de Longitud de Ladera (L)
Se implementa el algoritmo de **Desmet y Govers (1996)**, el cual extiende la teoría de la USLE a terrenos complejos mediante el uso del área contribuyente unitaria. La ecuación utilizada para una celda $(i, j)$ es:

$$L_{i,j} = \frac{(A_{i,j-in} + D^2)^{m+1} - A_{i,j-in}^{m+1}}{D^{m+2} \cdot (m+1) \cdot (22.13)^m}$$

Donde:
- $A_{i,j-in}$ es el área contribuyente aguas arriba de la celda ($m^2$).
- $D$ es el tamaño de la celda o resolución del raster ($m$).
- $m$ es el exponente de longitud de ladera, calculado según la relación de erosión entre surcos (rill) e inter-surcos (inter-rill).

El exponente $m$ se deriva de la relación $\beta$ propuesta por **McCool et al. (1989)**:

$$\beta = \frac{\sin\theta / 0.0896}{3.0 \cdot (\sin\theta)^{0.8} + 0.56}$$
$$m = \frac{\beta}{1 + \beta}$$

Donde $\theta$ es el ángulo de la pendiente en radianes.

##### 2.2. Factor de Pendiente (S)
Para el cálculo de **S**, se utiliza la formulación segmentada de **Renard et al. (1997)** (RUSLE), que mejora la precisión en pendientes pronunciadas:

$$S = \begin{cases} 
10.8 \cdot \sin\theta + 0.03 & \text{si } \tan\theta < 0.09 \\
16.8 \cdot \sin\theta - 0.50 & \text{si } 0.09 \leq \tan\theta < 0.50 \\
21.91 \cdot \sin\theta - 0.96 & \text{si } \tan\theta \geq 0.50 
\end{cases}$$

#### 3. Flujo de Procesamiento Hidrológico
Para garantizar la coherencia física del factor LS, el script realiza un pre-procesamiento del DEM utilizando la librería `pysheds`:
1.  **Relleno de depresiones (Sink Fill):** Eliminación de errores locales en el DEM para asegurar un drenaje continuo.
2.  **Dirección de flujo (D8):** Determinación de la ruta del agua hacia la celda vecina con mayor pendiente descendente.
3.  **Acumulación de flujo:** Cálculo del área total que drena a través de cada celda, base fundamental para el factor L.

#### 4. Referencias Bibliográficas (APA 7ª Edición)

Desmet, P. J. J., & Govers, G. (1996). A GIS procedure for automatically calculating the USLE LS factor on topographically complex landscape units. *Journal of Soil and Water Conservation, 51*(5), 427–433.

McCool, D. K., Foster, G. R., Mutchler, C. K., & Meyer, L. D. (1989). Revised slope length factor for the Universal Soil Loss Equation. *Transactions of the ASAE, 32*(5), 1571–1576. https://doi.org/10.13031/2013.31192

Moore, I. D., & Burch, G. J. (1986). Physical basis of the length-slope factor in the Universal Soil Loss Equation. *Soil Science Society of America Journal, 50*(5), 1294–1298. https://doi.org/10.2136/sssaj1986.03615995005000050042x

Renard, K. G., Foster, G. R., Weesies, G. A., McCool, D. K., & Yoder, D. C. (1997). *Predicting soil erosion by water: A guide to conservation planning with the Revised Universal Soil Loss Equation (RUSLE)* (Agriculture Handbook No. 703). United States Department of Agriculture.