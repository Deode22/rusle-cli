import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from modules.informe import generar_informe_rusle

if __name__ == "__main__":
    import numpy as np
    
    # Datos de ejemplo
    shape = (100, 100)
    K_array = np.random.uniform(0.01, 0.05, shape)
    LS_array = np.random.uniform(0.5, 15, shape)
    C_array = np.random.uniform(0.001, 0.5, shape)
    
    R_value = 850.5
    P_value = 1.0
    
    A_array = R_value * K_array * LS_array * C_array * P_value
    
    generar_informe_rusle(
        output_pdf="informe_erosion.pdf",
        R_value=R_value,
        K_array=K_array,
        LS_array=LS_array,
        C_array=C_array,
        P_value=P_value,
        A_array=A_array,
        metodo_LS="Desmet & Govers (1996)",
        raster_path=r"C:\Users\danie\Downloads\RUSLE_output_20260208-Feb1835\A_rusle_actual.tif"
    )