"""
common/utils.py

Funciones auxiliares comunes para servidor y clientes.
------------------------------------------------------
Incluye utilidades para serialización JSON, generación de IDs,
y medición de tiempo de ejecución.
"""

import json
import time
import uuid

def generate_client_id() -> str:
    """
    Genera un identificador único de cliente (UUID corto).
    """
    return str(uuid.uuid4())[:8]

def current_timestamp() -> float:
    """
    Devuelve el timestamp actual (en segundos).
    """
    return time.time()


