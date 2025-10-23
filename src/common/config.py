"""
common/config.py

Configuración global del sistema de simulación.

Define constantes compartidas por el servidor y los clientes.
Esto permite modificar valores como IP, puerto o buffer
sin tener que editar varios archivos.

Ejemplo:
    from common.config import HOST, PORT, BUFFER_SIZE
"""

# Dirección y puerto del servidor
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 5000

# Parámetros de red
BUFFER_SIZE = 1024  
ENCODING = "utf-8"

# Configuración de simulación
SIMULATION_INTERVAL = 2.0   
MAX_NEIGHBORS = 5           

# Mapa estático de vecinos (cliente -> lista de vecinos)
NEIGHBOR_MAP = {
    "station-1": ["station-2", "station-3"],
    "station-2": ["station-1", "station-3"],
    "station-3": ["station-1", "station-2"],
    "station-4": ["station-2"],  
}

# Número de iteraciones por cliente (simulación)
NUM_ITERATIONS = 3