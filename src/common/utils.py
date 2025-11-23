"""
common/utils.py

Funciones auxiliares comunes para servidor y clientes.
"""
import uuid

def generate_client_id() -> str:
    """
    Genera un identificador único de cliente (UUID corto).
    """
    return str(uuid.uuid4())[:8]


