# Factor K - Fórmula EPIC (Williams et al., 1990)

## Implementación Completa

El Factor K de erodibilidad del suelo se calcula usando la fórmula EPIC completa:

```
K = fsand × fsl-cl × fhisand × forgc × 0.1317
```

### Términos de la ecuación:

#### 1. fsand - Factor de arena
```
fsand = 0.2 + 0.3 × exp[-0.0256 × sand × (1 - silt/100)]
```
- Penaliza suelos con alto contenido de arena
- Arena en porcentaje (0-100)

#### 2. fsl-cl - Factor de relación limo/arcilla
```
fsl-cl = [silt / (clay + silt)]^0.3
```
- Suelos con más limo son más erodibles
- Valores más altos indican mayor erodibilidad

#### 3. fhisand - Factor de arcilla
```
fhisand = 1.0 - [0.25 × C / (C + exp(3.72 - 2.95 × C))]
```
donde C = clay/100 (fracción)
- Reduce K en suelos con alto contenido de arcilla
- La arcilla aumenta la cohesión del suelo

#### 4. forgc - Factor de carbono orgánico
```
forgc = 1.0 - [0.25 × SOC / (SOC + exp(3.72 - 2.95 × SOC))]
```
donde SOC = carbono orgánico en porcentaje
- Reduce K en suelos con alta materia orgánica
- La materia orgánica mejora la estructura y estabilidad

#### 5. Factor de conversión: 0.1317
Convierte las unidades al sistema métrico de RUSLE: t·h/(MJ·mm)

## Datos de entrada (SoilGrids)

- **Sand, Silt, Clay**: g/kg (0-1000) → convertir a % dividiendo por 10
- **SOC**: dg/kg (decagramos/kg) → convertir a % dividiendo por 10

## Validaciones implementadas

1. Suma de texturas: sand + silt + clay ≈ 100% (tolerancia ±5%)
2. Valores finitos en todas las propiedades
3. Logging detallado de estadísticas

## Referencias

Williams, J.R., Jones, C.A., Dyke, P.T. (1990). The EPIC model. 
In: EPIC - Erosion/Productivity Impact Calculator.

Sharpley, A.N., Williams, J.R. (1990). EPIC - Erosion/Productivity Impact Calculator: 
1. Model Documentation. USDA Technical Bulletin No. 1768.
