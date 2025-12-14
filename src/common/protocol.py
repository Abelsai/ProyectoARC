"""
common/protocol.py

Protocolo de mensajes del Sistema Realidad Aumentada Colaborativa mediante Sockets TCP.

Formato:
- Cada mensaje viaja como un JSON serializado en UTF-8 (bytes).
- Los mensajes se delimitan por salto de línea '\n' para poder usar readline() en asyncio.
- La estructura base es:
    {
        "type": "<tipo>",
        "client_id": "<id_emisor>",
        "data": { ... }
    }

Nota:
- Se utiliza orjson por rendimiento (serialización/deserialización rápida).
"""

from enum import Enum
import orjson


class MessageType(Enum):
    """
    Tipos de mensajes del sistema.

    JOIN:  cliente se registra (el servidor le asignará id real más adelante)
    START: el servidor indica que la simulación comienza y envía vecinos al cliente
    INFO:  coordenadas de un cliente (el servidor reenvía a sus vecinos)
    ACK:   confirmación asociada a INFO (el servidor lo reenvía al destinatario)
    END:   fin (cliente reporta métricas / servidor notifica cierre global)
    ERROR: mensaje de error (reservado para casos excepcionales)
    """
    JOIN = "join"
    START = "start"
    INFO = "info"
    ACK = "ack"
    END = "end"
    ERROR = "error"


def make_message(msg_type: MessageType, client_id: str, data=None) -> dict:
    """
    Construye un mensaje con el formato estándar.

    data se fuerza a dict vacío si viene None para simplificar la lógica aguas abajo
    (así evitamos estar comprobando None en el servidor/cliente).
    """
    return {
        "type": msg_type.value,
        "client_id": client_id,
        "data": data or {}
    }


def encode_message(msg: dict) -> bytes:
    """
    Serializa un mensaje a bytes y añade '\n' como separador.

    Esto permite:
      - enviar mensajes con writer.write(...)
      - recibirlos con reader.readline() sin tener que gestionar longitudes.
    """
    return orjson.dumps(msg) + b"\n"


def decode_message(line: bytes) -> dict:
    """
    Deserializa una línea recibida (bytes) y devuelve un dict.

    Se asume que 'line' incluye el '\n' final (readline lo devuelve con él),
    pero orjson lo tolera sin problemas.
    """
    return orjson.loads(line)


def validate_message(msg: dict) -> bool:
    """
    Validación mínima del formato del mensaje.

    Comprueba únicamente:
      - que msg sea dict
      - que tenga las claves "type" y "client_id"

    No valida:
      - que type sea uno de MessageType
      - que data tenga campos concretos según el tipo
    """
    return isinstance(msg, dict) and "type" in msg and "client_id" in msg
