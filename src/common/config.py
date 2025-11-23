"""
common/config.py

Configuración global del sistema de simulación.

Define constantes compartidas por el servidor y los clientes.
Esto permite modificar valores como IP, puerto o buffer
sin tener que editar varios archivos.

Ejemplo:
    from common.config import SERVER_HOST, SERVER_PORT, BUFFER_SIZE
"""

# Dirección y puerto del servidor
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8888

# Parámetros de red
BUFFER_SIZE = 1024  
ENCODING = "utf-8"

# Configuración de simulación
SIMULATION_INTERVAL = 2.0   

# Número de iteraciones por cliente (simulación)
NUM_ITERATIONS = 150

MAX_PER_BARRIO = 10

NUM_CLIENTES = 300