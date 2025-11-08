"""
common/protocol.py
Definición de tipos de mensaje y utilidades comunes.
"""

from enum import Enum
import json

class MessageType(Enum):
    JOIN = "join"              # Cliente → Servidor (inicio de sesión)
    START = "start"            # Servidor → Clientes (inicio de simulación)
    INFO = "info"              # Cliente → Servidor → Vecinos (coordenadas)
    ACK = "ack"                # Reconocimientos genéricos
    END = "end"                # Cliente/Servidor indican finalización
    ERROR = "error"            # Comunicación de errores


def make_message(msg_type: MessageType, client_id: str, data=None) -> dict:
    """
    Crea un mensaje estándar JSON entre cliente y servidor.
    """
    return {
        "type": msg_type.value,
        "client_id": client_id,
        "data": data or {}
    }

def validate_message(msg: dict) -> bool:
    """
    Valida que el mensaje tenga el formato mínimo correcto.
    """
    return isinstance(msg, dict) and "type" in msg and "client_id" in msg
