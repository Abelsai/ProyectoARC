"""
common/protocol.py
Definición de tipos de mensaje y utilidades comunes.
"""

from enum import Enum
import json

class MessageType(Enum):
    STATUS_UPDATE = "status_update"
    SIMULATION_END = "simulation_end"
    START_SIMULATION = "start_simulation"
    SERVER_ACK = "server_ack"
    NEIGHBOR_UPDATE = "neighbor_update"
    ACK_NEIGHBOR = "ack_neighbor"
    ACK_FORWARD = "ack_forward"
    END_SIMULATION = "end_simulation"  
    ERROR = "error"


def make_message(msg_type: MessageType, client_id: str, data=None) -> dict:
    return {
        "type": msg_type.value,
        "client_id": client_id,
        "data": data or {}
    }


def validate_message(msg: dict) -> bool:
    return isinstance(msg, dict) and "type" in msg and "client_id" in msg
