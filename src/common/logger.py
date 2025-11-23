import logging
import os
from datetime import datetime

# Crear carpeta de logs si no existe
os.makedirs("logs", exist_ok=True)

# Nombre único para cada sesión
filename = datetime.now().strftime("logs/simulacion_%Y%m%d_%H%M%S.log")

# Configurar el logger global
logging.basicConfig(
    filename=filename,
    filemode="w",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)

logger = logging.getLogger("simulacion")

