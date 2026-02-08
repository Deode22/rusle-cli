# modules/generate_report.py
"""
Módulo para generar informes PDF de pérdidas de suelo usando RUSLE
Estilo: científico, minimalista, blanco y negro (excepto mapa)
"""

import os
from datetime import datetime
import numpy as np
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image, KeepTogether, HRFlowable
)
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from PIL import Image as PILImage
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import matplotlib.patches as mpatches
from mpl_toolkits.axes_grid1 import make_axes_locatable
import rasterio
from rasterio.plot import show


class NumberedCanvas(canvas.Canvas):
    """Canvas personalizado para añadir números de página y encabezados"""

    def __init__(self, *args, **kwargs):
        self.area_nombre = kwargs.pop('area_nombre', '')
        self.fecha = kwargs.pop('fecha', '')
        canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_elements(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_elements(self, page_count):
        # Encabezado (solo desde la página 2)
        if self._pageNumber > 1:
            self.setFont("Helvetica", 8)
            self.drawString(
                2*cm,
                A4[1] - 1.5*cm,
                f"Informe de Pérdidas de Suelo – {self.fecha}"
            )

            # Línea horizontal inferior
            self.setLineWidth(0.5)
            self.line(
                2*cm,
                A4[1] - 1.6*cm,
                A4[0] - 2*cm,
                A4[1] - 1.6*cm
            )

        # Pie de página (todas las páginas)
        self.setFont("Helvetica", 9)
        self.drawRightString(
            A4[0] - 2*cm,
            1.5*cm,
            f"{self._pageNumber}"
        )


def calcular_estadisticas(array):
    """Calcula estadísticas descriptivas de un array"""
    array_valido = array[~np.isnan(array)]
    
    if len(array_valido) == 0:
        return {
            'media': 0, 'mediana': 0, 'desv_std': 0,
            'minimo': 0, 'maximo': 0, 'percentil_25': 0,
            'percentil_75': 0, 'percentil_90': 0, 'percentil_95': 0
        }
    
    return {
        'media': float(np.mean(array_valido)),
        'mediana': float(np.median(array_valido)),
        'desv_std': float(np.std(array_valido)),
        'minimo': float(np.min(array_valido)),
        'maximo': float(np.max(array_valido)),
        'percentil_25': float(np.percentile(array_valido, 25)),
        'percentil_75': float(np.percentile(array_valido, 75)),
        'percentil_90': float(np.percentile(array_valido, 90)),
        'percentil_95': float(np.percentile(array_valido, 95))
    }


def interpretar_erosion(A_array):
    """Interpreta los niveles de erosión según valores medios y máximos

    Calcula la media solo de valores entre 0-200 para evitar sesgos por
    afloramientos rocosos o anomalías del terreno.
    """
    A_valido = A_array[~np.isnan(A_array)]

    if len(A_valido) == 0:
        return "No hay datos válidos para interpretar."

    maximo = float(np.max(A_valido))
    A_normal = A_valido[(A_valido >= 0) & (A_valido <= 200)]

    if len(A_normal) == 0:
        return "Todos los valores están fuera del rango normal (0-200 T/ha/año)."

    media = float(np.mean(A_normal))
    porcentaje_extremo = (len(A_valido) - len(A_normal)) / len(A_valido) * 100

    interpretaciones = []

    if media < 5:
        interpretaciones.append("El área presenta niveles de erosión muy bajos en promedio.")
    elif media < 12:
        interpretaciones.append("El área presenta niveles de erosión bajos en promedio.")
    elif media < 25:
        interpretaciones.append("El área presenta niveles de erosión moderados en promedio.")
    elif media < 50:
        interpretaciones.append("El área presenta niveles de erosión altos en promedio.")
    else:
        interpretaciones.append("El área presenta niveles de erosión muy altos en promedio.")

    if maximo > 200:
        if porcentaje_extremo > 1:
            interpretaciones.append(
                f"Se detectan valores superiores a 200 T/ha/año ({porcentaje_extremo:.1f}% del área), "
                "que pueden deberse a afloramientos rocosos, zonas sin vegetación o interrupciones "
                "del medio que estarían sesgando los resultados. La interpretación se basa en la media "
                f"de valores entre 0-200 T/ha/año ({media:.2f} T/ha/año)."
            )
        else:
            interpretaciones.append("Se detectan zonas críticas con pérdidas superiores a 200 T/ha/año que requieren intervención urgente.")
    elif maximo > 100:
        interpretaciones.append("Se detectan zonas con pérdidas severas superiores a 100 T/ha/año.")
    elif maximo > 50:
        interpretaciones.append("Se detectan zonas con pérdidas altas que requieren medidas de conservación.")

    return " ".join(interpretaciones)


def generar_graficas_estadisticas(A_array, output_path):
    """Genera un panel 2x2 con gráficas estadísticas en B/N"""
    
    fig, axes = plt.subplots(2, 2, figsize=(7.5, 7.5))
    fig.patch.set_facecolor('white')
    
    A_valido = A_array[~np.isnan(A_array)]
    
    # 1. Histograma
    ax1 = axes[0, 0]
    ax1.hist(A_valido, bins=50, color='black', alpha=0.7, edgecolor='black', linewidth=0.5)
    ax1.set_xlabel('Pérdida de suelo (T/ha/año)', fontsize=8)
    ax1.set_ylabel('Frecuencia', fontsize=8)
    ax1.set_title('Distribución de frecuencias', fontsize=9, weight='bold')
    ax1.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)
    ax1.tick_params(labelsize=7)
    
    # 2. Box plot
    ax2 = axes[0, 1]
    bp = ax2.boxplot(A_valido, vert=True, patch_artist=True,
                     boxprops=dict(facecolor='lightgray', color='black', linewidth=0.8),
                     whiskerprops=dict(color='black', linewidth=0.8),
                     capprops=dict(color='black', linewidth=0.8),
                     medianprops=dict(color='black', linewidth=1.5),
                     flierprops=dict(marker='o', markerfacecolor='black', markersize=3, alpha=0.5))
    ax2.set_ylabel('Pérdida de suelo (T/ha/año)', fontsize=8)
    ax2.set_title('Diagrama de caja', fontsize=9, weight='bold')
    ax2.grid(True, alpha=0.3, linestyle='--', axis='y', linewidth=0.5)
    ax2.tick_params(labelsize=7)
    ax2.set_xticklabels([''])
    
    # 3. Curva acumulativa
    ax3 = axes[1, 0]
    sorted_data = np.sort(A_valido)
    cumulative = np.arange(1, len(sorted_data) + 1) / len(sorted_data) * 100
    ax3.plot(sorted_data, cumulative, color='black', linewidth=1.2)
    ax3.set_xlabel('Pérdida de suelo (T/ha/año)', fontsize=8)
    ax3.set_ylabel('Porcentaje acumulado (%)', fontsize=8)
    ax3.set_title('Distribución acumulativa', fontsize=9, weight='bold')
    ax3.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)
    ax3.tick_params(labelsize=7)
    
    # 4. Clasificación por niveles
    ax4 = axes[1, 1]
    bins = [0, 5, 12, 25, 50, 100, 200, np.inf]
    labels = ['0-5', '5-12', '12-25', '25-50', '50-100', '100-200', '>200']
    counts, _ = np.histogram(A_valido, bins=bins)
    percentages = counts / len(A_valido) * 100
    
    bars = ax4.barh(labels, percentages, color='black', alpha=0.7, edgecolor='black', linewidth=0.5)
    ax4.set_xlabel('Porcentaje del área (%)', fontsize=8)
    ax4.set_ylabel('Nivel de erosión (T/ha/año)', fontsize=8)
    ax4.set_title('Distribución por clases', fontsize=9, weight='bold')
    ax4.grid(True, alpha=0.3, linestyle='--', axis='x', linewidth=0.5)
    ax4.tick_params(labelsize=7)
    
    # Añadir valores en las barras
    for i, (bar, pct) in enumerate(zip(bars, percentages)):
        if pct > 1:
            ax4.text(pct + 1, i, f'{pct:.1f}%', va='center', fontsize=6)
    
    plt.tight_layout(pad=1.5)
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()


def generar_mapa_erosion(raster_path, output_path, bounds=None):
    """Genera mapa de erosión clasificado con leyenda, escala, norte y grid"""
    
    with rasterio.open(raster_path) as src:
        data = src.read(1)
        transform = src.transform
        crs = src.crs
        
        # Clasificar datos
        import numpy as np
        classified = np.full_like(data, np.nan, dtype=float)
        classified[(data >= 0) & (data < 5)] = 1
        classified[(data >= 5) & (data < 12)] = 2
        classified[(data >= 12) & (data < 25)] = 3
        classified[(data >= 25) & (data < 50)] = 4
        classified[(data >= 50) & (data < 100)] = 5
        classified[(data >= 100) & (data < 200)] = 6
        classified[data >= 200] = 7
        
        # Crear figura
        fig, ax = plt.subplots(figsize=(7.5, 10))
        fig.patch.set_facecolor('white')
        
        # Colores según la imagen proporcionada
        colors_map = ['#4CAF50', '#8BC34A', '#CDDC39', '#FFEB3B', 
                      '#FFC107', '#FF9800', '#F44336']
        cmap = matplotlib.colors.ListedColormap(colors_map)
        bounds_cmap = [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5]
        norm = matplotlib.colors.BoundaryNorm(bounds_cmap, cmap.N)
        
        # Mostrar raster
        im = ax.imshow(classified, cmap=cmap, norm=norm, 
                      extent=[transform[2], transform[2] + transform[0] * data.shape[1],
                             transform[5] + transform[4] * data.shape[0], transform[5]])
        
        # Grid
        ax.grid(True, color='gray', linestyle='--', linewidth=0.5, alpha=0.4)
        ax.set_xlabel('Longitud', fontsize=9)
        ax.set_ylabel('Latitud', fontsize=9)
        ax.tick_params(labelsize=8)
        
        # Leyenda
        labels = ['0-5', '5-12', '12-25', '25-50', '50-100', '100-200', '>200']
        patches = [mpatches.Patch(color=colors_map[i], label=labels[i]) 
                  for i in range(len(labels))]
        legend = ax.legend(handles=patches, title='Niveles de erosión\n(T/ha/año)',
                          loc='upper right', fontsize=7, title_fontsize=8,
                          frameon=True, fancybox=False, shadow=False,
                          edgecolor='black', facecolor='white')
        
        # Flecha del norte
        x_pos = 0.05
        y_pos = 0.95
        ax.annotate('N', xy=(x_pos, y_pos), xytext=(x_pos, y_pos - 0.06),
                   xycoords='axes fraction', fontsize=12, weight='bold',
                   ha='center', va='center',
                   arrowprops=dict(arrowstyle='->', lw=1.5, color='black'))

        # Título
        ax.set_title('Mapa de pérdidas de suelo', fontsize=11, weight='bold', pad=12)
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
        plt.close()


def generar_informe_rusle(
    output_pdf,
    area_nombre,
    R_value,
    K_array,
    LS_array,
    C_array,
    P_value,
    A_array,
    metodo_LS="Desmet & Govers (1996)",
    raster_path=None
):
    """
    Genera el informe completo de pérdidas de suelo
    
    Parámetros:
    -----------
    output_pdf : str
        Ruta del PDF de salida
    area_nombre : str
        Nombre del área de estudio
    R_value : float
        Factor de erosividad de la lluvia (MJ·mm/ha·h·año)
    K_array : np.ndarray
        Array del factor de erodabilidad del suelo
    LS_array : np.ndarray
        Array del factor topográfico
    C_array : np.ndarray
        Array del factor de cobertura vegetal
    P_value : float
        Factor de prácticas de conservación
    A_array : np.ndarray
        Array de pérdidas de suelo (T/ha/año)
    metodo_LS : str
        Método usado para calcular LS
    raster_path : str
        Ruta al raster de salida para generar el mapa
    """
    
    # Crear directorio temporal para gráficas
    temp_dir = "temp_report"
    os.makedirs(temp_dir, exist_ok=True)
    
    # Generar gráficas
    graficas_path = os.path.join(temp_dir, "graficas_estadisticas.png")
    generar_graficas_estadisticas(A_array, graficas_path)
    
    mapa_path = None
    if raster_path and os.path.exists(raster_path):
        mapa_path = os.path.join(temp_dir, "mapa_erosion.png")
        generar_mapa_erosion(raster_path, mapa_path)
    
    # Calcular estadísticas
    stats_K = calcular_estadisticas(K_array)
    stats_LS = calcular_estadisticas(LS_array)
    stats_C = calcular_estadisticas(C_array)
    stats_A = calcular_estadisticas(A_array)
    
    # Configurar documento
    doc = SimpleDocTemplate(
        output_pdf,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )
    
    # Estilos
    styles = getSampleStyleSheet()
    
    style_title = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=14,
        textColor=colors.black,
        spaceAfter=8,
        alignment=TA_LEFT,
        fontName='Helvetica-Bold',
        borderWidth=0,
        borderColor=colors.black,
        borderPadding=0,
        borderRadius=0,
        spaceBefore=0,
        borderBottomWidth=1,
        borderBottomColor=colors.black
    )

    style_date = ParagraphStyle(
        'CustomDate',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.black,
        spaceAfter=12,
        alignment=TA_LEFT,
        fontName='Helvetica'
    )

    style_heading = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=11,
        textColor=colors.black,
        spaceAfter=8,
        spaceBefore=10,
        fontName='Helvetica-Bold',
        borderWidth=0,
        borderBottomWidth=1,
        borderColor=colors.black,
        borderBottomColor=colors.black,
        borderPadding=(0, 0, 3, 0),
        keepWithNext=True
    )

    style_body = ParagraphStyle(
        'CustomBody',
        parent=styles['BodyText'],
        fontSize=10,
        textColor=colors.black,
        alignment=TA_JUSTIFY,
        spaceAfter=10,
        leading=14
    )
    
    style_caption = ParagraphStyle(
        'Caption',
        parent=styles['BodyText'],
        fontSize=9,
        textColor=colors.black,
        alignment=TA_LEFT,
        spaceAfter=10,
        spaceBefore=2,
        fontName='Helvetica-Oblique'
    )
    
    # Contenido del documento
    story = []
    
    # Encabezado
    story.append(Paragraph(f"Informe de Pérdidas de Suelo - {area_nombre}", style_title))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.black, spaceAfter=2))
    story.append(Paragraph(f"{datetime.now().strftime('%d/%m/%Y')}", style_date))
    
    # Introducción
    story.append(Paragraph("Estimación de erosión hídrica mediante RUSLE", style_heading))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.black, spaceAfter=8))

    story.append(Paragraph(
        "La erosión hídrica constituye uno de los principales procesos de degradación del suelo, "
        "con importantes implicaciones para la productividad agrícola, la calidad del agua y la "
        "sostenibilidad de los ecosistemas. El presente informe presenta los resultados de la "
        "estimación de pérdidas de suelo por erosión hídrica mediante el modelo RUSLE (Revised "
        "Universal Soil Loss Equation), aplicado de forma automatizada mediante teledetección y "
        "bases de datos públicas.",
        style_body
    ))

    story.append(Spacer(1, 0.2*cm))

    story.append(Paragraph(
        "El modelo RUSLE es una ecuación empírica ampliamente validada que estima la pérdida "
        "media anual de suelo mediante la siguiente expresión:",
        style_body
    ))

    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(
        "<i>A = R × K × LS × C × P</i>",
        ParagraphStyle('equation', parent=style_body, alignment=TA_CENTER, fontSize=11, fontName='Helvetica-BoldOblique')
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph(
        "donde <i>A</i> representa la pérdida de suelo (T/ha/año), <i>R</i> es el factor de "
        "erosividad de la lluvia (MJ·mm/ha·h·año), <i>K</i> es el factor de erodabilidad del "
        "suelo (t·h/MJ·mm), <i>LS</i> es el factor topográfico (adimensional), <i>C</i> es el "
        "factor de cobertura vegetal (adimensional) y <i>P</i> es el factor de prácticas de "
        "conservación (adimensional).",
        style_body
    ))

    story.append(Spacer(1, 0.2*cm))

    story.append(Paragraph(
        "Este análisis se ha realizado mediante un flujo de trabajo automatizado que integra "
        "múltiples fuentes de datos geoespaciales de acceso abierto: cartografía oficial de "
        "erosividad (MITECO), propiedades edáficas globales (SoilGrids 250m), modelos digitales "
        "de elevación (PNOA-MDT05) e imágenes satelitales multiespectrales (Sentinel-2 L2A). "
        "La metodología implementada permite la evaluación objetiva y reproducible de la erosión "
        "a escala regional, proporcionando información espacialmente explícita para la planificación "
        "de medidas de conservación del suelo.",
        style_body
    ))
    
    # 1. Metodología
    story.append(PageBreak())
    story.append(Paragraph("1. Metodología de cálculo de factores", style_heading))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.black, spaceAfter=6))
    
    # 1.1 Factor R
    story.append(Paragraph("1.1. Factor R - Erosividad de la lluvia",
                          ParagraphStyle('subheading', parent=style_body, fontSize=10,
                                       fontName='Helvetica-Bold', spaceAfter=4, spaceBefore=6)))

    story.append(Paragraph(
        "El factor R cuantifica el efecto erosivo de la energía cinética de la lluvia y su "
        "intensidad sobre el suelo desnudo. Este factor integra la agresividad climática mediante "
        "el producto de la energía cinética total de la tormenta y su intensidad máxima en 30 minutos "
        "(índice EI<sub>30</sub>), acumulado para todas las tormentas del año.",
        style_body
    ))

    story.append(Paragraph(
        "Para este estudio se ha utilizado la cartografía oficial del Ministerio para la Transición "
        "Ecológica y el Reto Demográfico (MITECO), disponible a través del servicio WMS del Sistema "
        "de Información Geográfica de Datos Agrarios. Esta capa proporciona valores de erosividad "
        "calculados a partir de series históricas de precipitación mediante la metodología de "
        "Renard et al. (1997), expresados en MJ·mm/(ha·h·año). Los valores se obtienen mediante "
        "consulta automatizada al servicio web, extrayendo el valor medio para el área de estudio.",
        style_body
    ))
    
    # 1.2 Factor K
    story.append(Paragraph("1.2. Factor K - Erodabilidad del suelo",
                          ParagraphStyle('subheading', parent=style_body, fontSize=10,
                                       fontName='Helvetica-Bold', spaceAfter=4, spaceBefore=6)))

    story.append(Paragraph(
        "El factor K representa la susceptibilidad intrínseca del suelo a la erosión, determinada "
        "por sus propiedades físicas y químicas. Este factor refleja la resistencia del suelo al "
        "desprendimiento de partículas por el impacto de las gotas de lluvia y al transporte por "
        "escorrentía superficial.",
        style_body
    ))

    story.append(Spacer(1, 0.2*cm))

    story.append(Paragraph(
        "El cálculo se realizó mediante la fórmula EPIC (Williams et al., 1990) a partir de "
        "datos de textura (arena, limo, arcilla) y carbono orgánico del suelo obtenidos de "
        "SoilGrids 250m v2.0 (ISRIC). Esta base de datos global proporciona predicciones de "
        "propiedades edáficas a múltiples profundidades mediante técnicas de aprendizaje automático "
        "aplicadas a perfiles de suelo georreferenciados. Para este análisis se utilizó la capa "
        "superficial (0-5 cm), que es la más relevante para procesos erosivos.",
        style_body
    ))

    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(
        "<i>K = f<sub>sand</sub> × f<sub>sl-cl</sub> × f<sub>hisand</sub> × "
        "f<sub>orgc</sub> × 0.1317</i>",
        ParagraphStyle('equation', parent=style_body, alignment=TA_CENTER, fontSize=10)
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph(
        "donde:",
        style_body
    ))

    story.append(Spacer(1, 0.2*cm))

    story.append(Paragraph(
        "<i>f<sub>sand</sub> = 0.2 + 0.3 × exp[-0.0256 × sand × (1 - silt/100)]</i> "
        "penaliza suelos con alto contenido de arena;",
        style_body
    ))

    story.append(Spacer(1, 0.1*cm))

    story.append(Paragraph(
        "<i>f<sub>sl-cl</sub> = [silt / (clay + silt)]<sup>0.3</sup></i> "
        "refleja la relación limo/arcilla;",
        style_body
    ))

    story.append(Spacer(1, 0.1*cm))

    story.append(Paragraph(
        "<i>f<sub>hisand</sub> = 1.0 - [0.25 × C / (C + exp(3.72 - 2.95 × C))]</i> "
        "con C = clay/100 reduce K en suelos arcillosos;",
        style_body
    ))

    story.append(Spacer(1, 0.1*cm))

    story.append(Paragraph(
        "<i>f<sub>orgc</sub> = 1.0 - [0.25 × SOC / (SOC + exp(3.72 - 2.95 × SOC))]</i> "
        "reduce K en suelos con alta materia orgánica.",
        style_body
    ))

    story.append(Spacer(1, 0.2*cm))

    story.append(Paragraph(
        "El factor 0.1317 convierte las unidades al sistema métrico de RUSLE: t·h/(MJ·mm). "
        "La fórmula EPIC captura los efectos no lineales de la textura y la materia orgánica "
        "sobre la cohesión y estabilidad estructural del suelo. Específicamente, <i>f<sub>sand</sub></i> "
        "penaliza suelos arenosos que presentan menor cohesión; <i>f<sub>sl-cl</sub></i> refleja "
        "cómo la proporción de limo respecto a arcilla afecta la resistencia del agregado; "
        "<i>f<sub>hisand</sub></i> reduce la erodabilidad en suelos arcillosos debido a su mayor "
        "adhesión; y <i>f<sub>orgc</sub></i> disminuye K en suelos ricos en materia orgánica que "
        "poseen mejor estructura y estabilidad de agregados. En conjunto, estos subfactores "
        "representan los mecanismos físico-químicos que controlan la resistencia del suelo al "
        "desprendimiento de partículas durante eventos de lluvia erosiva.",
        style_body
    ))
    
    story.append(PageBreak())

    # 1.3 Factor LS
    story.append(Paragraph("1.3. Factor LS - Topografía",
                          ParagraphStyle('subheading', parent=style_body, fontSize=10,
                                       fontName='Helvetica-Bold', spaceAfter=4, spaceBefore=6)))

    story.append(Paragraph(
        "El factor LS representa el efecto combinado de la longitud de ladera (L) y la pendiente (S) "
        "sobre la capacidad de transporte de sedimentos y la energía erosiva del flujo superficial. "
        "Este factor es crítico en RUSLE porque captura cómo la topografía modula la erosión a través "
        "de dos mecanismos complementarios: (1) la longitud de ladera controla la distancia de "
        "acumulación de escorrentía y, por tanto, la cantidad de agua disponible para erosionar; y "
        "(2) la pendiente determina la velocidad del flujo y su capacidad de arrastre. A diferencia de "
        "los métodos tradicionales diseñados para parcelas experimentales, este análisis utiliza un "
        "enfoque basado en Sistemas de Información Geográfica que captura la complejidad topográfica "
        "de paisajes naturales mediante Modelos Digitales de Elevación.",
        style_body
    ))

    story.append(Spacer(1, 0.2*cm))

    story.append(Paragraph(
        "<b>Fuente de datos y procesamiento hidrológico:</b>",
        style_body
    ))

    story.append(Spacer(1, 0.1*cm))

    story.append(Paragraph(
        "Los datos topográficos provienen del Modelo Digital del Terreno del Plan Nacional de "
        "Ortofotografía Aérea (PNOA-MDT05), disponible a través del Centro de Descargas del Centro "
        "Nacional de Información Geográfica (CNIG). Este modelo proporciona elevaciones con resolución "
        "de 5 metros y exactitud vertical de ±1-2 metros en terrenos llanos, derivado de datos LiDAR "
        "(Light Detection and Ranging) del segundo plan nacional de vuelos. La resolución de 5 metros "
        "es particularmente ventajosa para capturar características topográficas relevantes para procesos "
        "erosivos (surcos, vaguadas, cambios de pendiente) que serían invisibles a resoluciones más gruesas, "
        "pero manteniendo eficiencia computacional para análisis a escala regional.",
        style_body
    ))

    story.append(Spacer(1, 0.2*cm))

    story.append(Paragraph(
        "El procesamiento hidrológico del MDT incluye los siguientes pasos automatizados:",
        style_body
    ))

    story.append(Spacer(1, 0.1*cm))

    story.append(Paragraph(
        "1. <b>Relleno de depresiones:</b> Eliminación de celdas aisladas con elevación inferior a "
        "sus vecinos (sinks o depresiones), que representan artefactos del LiDAR o representación "
        "digital inadecuada. Este paso es fundamental para assegurar flujo continuo de agua desde "
        "divisorias hacia drenajes.",
        style_body
    ))

    story.append(Spacer(1, 0.1*cm))

    story.append(Paragraph(
        "2. <b>Cálculo de dirección de flujo:</b> Determinación de la dirección de máxima pendiente "
        "descendente en cada píxel mediante el algoritmo D8 (8 direcciones), que asume que el agua "
        "fluye hacia una de las 8 celdas adyacentes. D8 es más robusto que D4 para capturar flujos "
        "diagonales en terrenos complejos.",
        style_body
    ))

    story.append(Spacer(1, 0.1*cm))

    story.append(Paragraph(
        "3. <b>Acumulación de flujo:</b> Cálculo iterativo del número de celdas contribuyentes aguas "
        "arriba de cada píxel, que se convierte en el área contribuyente (A<sub>i,j-in</sub>) "
        "expresada en m<sup>2</sup>. Este proceso es fundamental para el cálculo del componente L, ya que "
        "simula cómo se concentra el escurrimiento en vaguadas y drenajes. Estos cálculos se implementan "
        "mediante la librería pysheds, que proporciona operaciones eficientes en raster.",
        style_body
    ))

    story.append(Spacer(1, 0.2*cm))

    story.append(Paragraph(
        f"El cálculo del factor LS se realizó mediante el algoritmo de {metodo_LS}, que extiende "
        "la teoría clásica de USLE a terrenos complejos naturales mediante el uso del área contribuyente "
        "unitaria derivada del MDT procesado. Esta aproximación es más realista que métodos simples basados "
        "en pendiente local únicamente, porque reconoce que la erosión es determinada tanto por condiciones "
        "locales como por el flujo acumulado desde aguas arriba.",
        style_body
    ))

    story.append(PageBreak())

    story.append(Paragraph(
        "<b>Componente L (Longitud de ladera):</b>",
        style_body
    ))

    story.append(Spacer(1, 0.1*cm))

    story.append(Paragraph(
        "El componente L cuantifica el efecto de la longitud de la ladera sobre la energía y caudal "
        "del flujo en un píxel dado. El cálculo utiliza la ecuación general de {metodo_LS}:",
        style_body
    ))

    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(
        "<i>L<sub>i,j</sub> = [(A<sub>i,j-in</sub> + D<sup>2</sup>)<sup>m+1</sup> - "
        "A<sub>i,j-in</sub><sup>m+1</sup>] / [D<sup>m+2</sup> × (m+1) × (22.13)<sup>m</sup>]</i>",
        ParagraphStyle('equation', parent=style_body, alignment=TA_CENTER, fontSize=9)
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph(
        "donde:",
        style_body
    ))

    story.append(Spacer(1, 0.1*cm))

    story.append(Paragraph(
        "• <i>A<sub>i,j-in</sub></i> es el área contribuyente aguas arriba (m<sup>2</sup>), acumulada "
        "mediante análisis de flujo hidológico del MDT. Refleja cuánta agua de escorrentía se concentra "
        "en el píxel analizado. Un área mayor implica mayor caudal y, por tanto, mayor capacidad erosiva.",
        style_body
    ))

    story.append(Spacer(1, 0.1*cm))

    story.append(Paragraph(
        "• <i>D</i> es la resolución del raster (5 m en nuestro caso), que normaliza los cálculos para "
        "permitir comparabilidad entre análisis con distintas resoluciones.",
        style_body
    ))

    story.append(Spacer(1, 0.1*cm))

    story.append(Paragraph(
        "• <i>m</i> es el exponente de longitud, un parámetro que varía con la pendiente local y refleja "
        "cómo cambia la relación entre longitud de ladera y erosión según el régimen de flujo. "
        "Se calcula de forma espacialmente variable mediante la ecuación empírica de Desmet & Govers (1996): "
        "<i>β = [sinθ / 0.0896] / [3.0 × (sinθ)<sup>0.8</sup> + 0.56]</i> y luego <i>m = β/(1+β)</i>. "
        "Esta formulación captura que en pendientes suaves domina la erosión laminar (transporte diffuso), "
        "donde el exponente es menor (~0.3-0.4), mientras que en pendientes fuertes domina la erosión "
        "en surcos (flujo concentrado), donde el exponente es mayor (~0.5-0.6).",
        style_body
    ))

    story.append(Spacer(1, 0.1*cm))

    story.append(Paragraph(
        "• El factor (22.13)<sup>m</sup> es una normalización derivada de la parcela estándar de USLE "
        "(22.13 m de largo), que permite comparar resultados con valores de L de parcelas experimentales. "
        "Asegura que un píxel sobre una ladera de 22.13 m y pendiente 9% tenga un valor de L ≈ 1.",
        style_body
    ))

    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph(
        "<b>Componente S (Pendiente):</b>",
        style_body
    ))

    story.append(Spacer(1, 0.1*cm))

    story.append(Paragraph(
        "El componente S cuantifica cómo la inclinación del terreno afecta la erosión. Utiliza una "
        "formulación segmentada según Renard et al. (1997) que mejora significativamente la precisión "
        "en pendientes pronunciadas respecto a la ecuación simple original de USLE. La formulación reconoce "
        "que los mecanismos de erosión cambian según la magnitud de la pendiente:",
        style_body
    ))

    story.append(Spacer(1, 0.2*cm))

    story.append(Paragraph(
        "• <b>Pendientes suaves (tanθ < 0.09, aprox. < 5°):</b> <i>S = 10.8 × sinθ + 0.03</i> — "
        "Domina la erosión laminar (sheet erosion), donde las gotas de lluvia impactan directamente el suelo "
        "y transportan sedimento de forma dispersa. El término 0.03 refleja que incluso en pendientes muy "
        "suaves ocurre erosión. Aquí θ es el ángulo de pendiente derivado de la máxima pendiente local "
        "calculada entre celdas adyacentes del MDT.",
        style_body
    ))

    story.append(Spacer(1, 0.1*cm))

    story.append(Paragraph(
        "• <b>Pendientes intermedias (0.09 ≤ tanθ < 0.50, aprox. 5-27°):</b> <i>S = 16.8 × sinθ - 0.50</i> — "
        "Zona de transición donde comienzan a formarse surcos (rills) iniciales. El flujo de agua se vuelve "
        "concentrado pero aún discontinuo. La tasa de erosión es más sensitiva a cambios de pendiente.",
        style_body
    ))

    story.append(Spacer(1, 0.1*cm))

    story.append(Paragraph(
        "• <b>Pendientes pronunciadas (tanθ ≥ 0.50, aprox. > 27°):</b> <i>S = 21.91 × sinθ - 0.96</i> — "
        "Domina la erosión en surcos profundos (gully erosion), donde flujos concentrados generan erosión "
        "lineal muy severa. A estas pendientes, factores adicionales como desprendimientos pueden ser "
        "importantes, pero RUSLE sigue siendo una aproximación válida para erosión hídrica. El coeficiente "
        "más alto (21.91) refleja la sensibilidad exponencial de la erosión a cambios de pendiente en este "
        "régimen.",
        style_body
    ))

    story.append(Spacer(1, 0.2*cm))

    story.append(Paragraph(
        "El factor LS resultante es el producto L × S en cada píxel, integrando los efectos de la longitud "
        "de ladera acumulada y la pendiente local. Valores típicos oscilan entre 0.1 en áreas planas o "
        "cóncavas hasta >20 en vaguadas pronunciadas. El LS resultante es espacialmente heterogéneo y "
        "refleja fielmente la estructura topográfica del terreno, proporcionando un control fundamental "
        "sobre la distribución espacial predicha de la erosión.",
        style_body
    ))
    
    # 1.4 Factor C
    story.append(Paragraph("1.4. Factor C - Cobertura vegetal", 
                          ParagraphStyle('subheading', parent=style_body, fontSize=10, 
                                       fontName='Helvetica-Bold', spaceAfter=4, spaceBefore=6)))
    
    story.append(Paragraph(
        "El factor C se derivó de imágenes Sentinel-2 mediante el NDVI (Índice de Vegetación "
        "de Diferencia Normalizada) como proxy de la densidad de biomasa. Se aplicó el método "
        "exponencial de Van der Knijff et al. (2000), diseñado para evaluación regional de "
        "erosión en Europa:",
        style_body
    ))
    
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        "<i>C = exp[-α × NDVI / (β - NDVI)]</i>",
        ParagraphStyle('equation', parent=style_body, alignment=TA_CENTER, fontSize=10)
    ))
    story.append(Spacer(1, 0.2*cm))
    
    story.append(Paragraph(
        "con α = 2 (parámetro de forma) y β = 1 (parámetro de escala). Esta formulación captura "
        "la protección desproporcionadamente alta que proporciona la vegetación inicial contra "
        "el impacto de las gotas de lluvia. Se aplicó máscara de calidad (SCL) para filtrar "
        "nubes, sombras y nieve, y se seleccionó el píxel de mínima nubosidad en una ventana "
        "temporal de 90 días. El rango de salida se restringió a [0.001, 1.0].",
        style_body
    ))
    
    # 1.5 Factor P
    story.append(Paragraph("1.5. Factor P - Prácticas de conservación", 
                          ParagraphStyle('subheading', parent=style_body, fontSize=10, 
                                       fontName='Helvetica-Bold', spaceAfter=4, spaceBefore=6)))
    
    story.append(Paragraph(
        "El factor P refleja el efecto de las prácticas de conservación del suelo (terrazas, "
        "cultivo en contorno, etc.) sobre la erosión. En ausencia de información específica "
        "sobre prácticas de manejo, se asignó un valor uniforme introducido manualmente. "
        "P = 1.0 indica ausencia de prácticas de conservación; valores menores indican "
        "reducción de la erosión por dichas prácticas.",
        style_body
    ))
    
    # 2. Resultados
    story.append(PageBreak())
    story.append(Paragraph("2. Resultados", style_heading))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.black, spaceAfter=8))
    
    story.append(Paragraph(
        "La aplicación del modelo RUSLE al área de estudio ha permitido estimar las pérdidas "
        "de suelo por erosión hídrica. A continuación se presentan los valores de los factores "
        "utilizados y las estadísticas descriptivas de los resultados obtenidos.",
        style_body
    ))
    
    # Tabla de factores
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph("Tabla 1. Factores del modelo RUSLE", style_caption))
    
    data_factores = [
        ['Factor', 'Valor/Rango', 'Unidades'],
        ['R', f'{R_value:.2f}', 'MJ·mm/ha·h·año'],
        ['K', f'{stats_K["media"]:.4f} ± {stats_K["desv_std"]:.4f}', 't·h/MJ·mm'],
        ['LS', f'{stats_LS["media"]:.2f} ± {stats_LS["desv_std"]:.2f}', 'adimensional'],
        ['C', f'{stats_C["media"]:.3f} ± {stats_C["desv_std"]:.3f}', 'adimensional'],
        ['P', f'{P_value:.2f}', 'adimensional']
    ]
    
    table_factores = Table(data_factores, colWidths=[3*cm, 6*cm, 4*cm])
    table_factores.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LINEABOVE', (0, 0), (-1, 0), 1, colors.black),
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.black),
        ('LINEBELOW', (0, -1), (-1, -1), 1, colors.black),
    ]))
    
    story.append(table_factores)
    story.append(Spacer(1, 0.5*cm))
    
    # Tabla de estadísticas
    story.append(Paragraph("Tabla 2. Estadísticas descriptivas de pérdidas de suelo (T/ha/año)", 
                          style_caption))
    
    data_stats = [
        ['Estadístico', 'Valor', '', 'Estadístico', 'Valor'],
        ['Media', f'{stats_A["media"]:.2f}', '', 'Mínimo', f'{stats_A["minimo"]:.2f}'],
        ['Mediana', f'{stats_A["mediana"]:.2f}', '', 'Máximo', f'{stats_A["maximo"]:.2f}'],
        ['Desv. estándar', f'{stats_A["desv_std"]:.2f}', '', 'Percentil 90', f'{stats_A["percentil_90"]:.2f}'],
        ['Percentil 25', f'{stats_A["percentil_25"]:.2f}', '', 'Percentil 95', f'{stats_A["percentil_95"]:.2f}'],
    ]
    
    table_stats = Table(data_stats, colWidths=[3.5*cm, 2.5*cm, 0.5*cm, 3.5*cm, 2.5*cm])
    table_stats.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('ALIGN', (3, 0), (3, -1), 'LEFT'),
        ('ALIGN', (4, 0), (4, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LINEABOVE', (0, 0), (1, 0), 1, colors.black),
        ('LINEBELOW', (0, 0), (1, 0), 1, colors.black),
        ('LINEBELOW', (0, -1), (1, -1), 1, colors.black),
        ('LINEABOVE', (3, 0), (4, 0), 1, colors.black),
        ('LINEBELOW', (3, 0), (4, 0), 1, colors.black),
        ('LINEBELOW', (3, -1), (4, -1), 1, colors.black),
    ]))
    
    story.append(table_stats)
    story.append(Spacer(1, 0.5*cm))
    
    # Clasificación por niveles
    A_valido = A_array[~np.isnan(A_array)]
    bins = [0, 5, 12, 25, 50, 100, 200, np.inf]
    labels = ['0-5', '5-12', '12-25', '25-50', '50-100', '100-200', '>200']
    counts, _ = np.histogram(A_valido, bins=bins)
    percentages = counts / len(A_valido) * 100
    
    story.append(Paragraph("Tabla 3. Distribución por niveles de erosión", style_caption))
    
    data_niveles = [
        ['Nivel (T/ha/año)', 'Área (%)', '', 'Nivel (T/ha/año)', 'Área (%)']
    ]
    for i in range(0, len(labels), 2):
        row = [labels[i], f'{percentages[i]:.2f}', '']
        if i + 1 < len(labels):
            row.extend([labels[i+1], f'{percentages[i+1]:.2f}'])
        else:
            row.extend(['', ''])
        data_niveles.append(row)
    
    table_niveles = Table(data_niveles, colWidths=[3.5*cm, 2.5*cm, 0.5*cm, 3.5*cm, 2.5*cm])
    table_niveles.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('ALIGN', (3, 0), (3, -1), 'LEFT'),
        ('ALIGN', (4, 0), (4, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LINEABOVE', (0, 0), (1, 0), 1, colors.black),
        ('LINEBELOW', (0, 0), (1, 0), 1, colors.black),
        ('LINEBELOW', (0, -1), (1, -1), 1, colors.black),
        ('LINEABOVE', (3, 0), (4, 0), 1, colors.black),
        ('LINEBELOW', (3, 0), (4, 0), 1, colors.black),
        ('LINEBELOW', (3, -1), (4, -1), 1, colors.black),
    ]))
    
    story.append(table_niveles)
    story.append(Spacer(1, 0.3*cm))
    
    # Interpretación
    interpretacion = interpretar_erosion(A_array)
    story.append(Paragraph(interpretacion, style_body))
    
    # Página de gráficas
    story.append(PageBreak())
    story.append(Paragraph("3. Análisis gráfico", style_heading))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.black, spaceAfter=8))
    
    if os.path.exists(graficas_path):
        img_graficas = Image(graficas_path, width=15*cm, height=15*cm)
        story.append(img_graficas)
        story.append(Paragraph(
            "Figura 1. Análisis estadístico de las pérdidas de suelo",
            style_caption
        ))
    
    # Página del mapa (sin redimensionar)
    if mapa_path and os.path.exists(mapa_path):
        story.append(PageBreak())
        story.append(Paragraph("4. Cartografía", style_heading))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.black, spaceAfter=8))
        
        # Obtener dimensiones nativas de la imagen
        with PILImage.open(mapa_path) as img:
            width_px, height_px = img.size
            # Calcular dimensiones manteniendo aspect ratio
            # Limitar a ancho de página (17cm máximo)
            max_width = 16*cm
            aspect = height_px / width_px
            if width_px > max_width:
                img_width = max_width
                img_height = max_width * aspect
            else:
                img_width = width_px / 300 * 2.54 * cm  # Convertir de px a cm (300 DPI)
                img_height = height_px / 300 * 2.54 * cm
        
        img_mapa = Image(mapa_path, width=img_width, height=img_height)
        story.append(img_mapa)
        story.append(Paragraph(
            "Figura 2. Mapa de pérdidas de suelo clasificado por niveles de erosión",
            style_caption
        ))
    
    # Generar PDF
    fecha_actual = datetime.now().strftime('%d/%m/%Y')
    doc.build(story, canvasmaker=lambda *args, **kwargs: NumberedCanvas(*args,
              area_nombre=area_nombre,
              fecha=fecha_actual,
              **kwargs))

    print(f"✓ Informe generado: {output_pdf}")
    
    # Limpiar archivos temporales
    try:
        if os.path.exists(graficas_path):
            os.remove(graficas_path)
        if mapa_path and os.path.exists(mapa_path):
            os.remove(mapa_path)
        os.rmdir(temp_dir)
    except:
        pass