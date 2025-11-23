"""
common/protocol.py
Definición de tipos de mensaje y utilidades comunes.
"""

from enum import Enum
import orjson


class MessageType(Enum):
    JOIN = "join"              # Cliente → Servidor (inicio de sesión)
    START = "start"            # Servidor → Clientes (inicio de simulación)
    INFO = "info"              # Cliente → Servidor → Vecinos (coordenadas)
    ACK = "ack"                # Reconocimientos
    END = "end"                # Cliente/Servidor indican finalización
    ERROR = "error"            # Comunicación de errores


def make_message(msg_type: MessageType, client_id: str, data=None) -> dict:
    """Crea un mensaje estándar."""
    return {
        "type": msg_type.value,
        "client_id": client_id,
        "data": data or {}
    }


def encode_message(msg: dict) -> bytes:
    """Serializa un mensaje a bytes + '\n' (para enviar por socket)."""
    return orjson.dumps(msg) + b"\n"


def decode_message(line: bytes) -> dict:
    """Deserializa una línea de bytes a dict."""
    return orjson.loads(line)


def validate_message(msg: dict) -> bool:
    """Valida formato mínimo."""
    return isinstance(msg, dict) and "type" in msg and "client_id" in msg
