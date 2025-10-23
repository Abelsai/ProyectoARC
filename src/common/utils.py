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

def json_encode(msg: dict) -> bytes:
    """
    Convierte un diccionario Python a JSON codificado en bytes (UTF-8).
    """
    return (json.dumps(msg) + "\n").encode("utf-8")

def json_decode(msg: bytes) -> dict:
    """
    Decodifica bytes JSON en un diccionario Python.
    """
    return json.loads(msg.decode("utf-8").strip())
