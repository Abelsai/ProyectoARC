"""
Cliente del sistema CAR optimizado sin polling (usa asyncio.Event).

En cada ciclo:
- genera coordenadas (x, y, z),
- las envía al servidor (INFO),
- espera los ACK de todos sus vecinos sin bucles de polling,
- mide el tiempo de respuesta del ciclo.

Al final de S ciclos envía al servidor su tiempo medio de respuesta.
"""

import asyncio
import random
import time
import socket

from common.protocol import (
    make_message,
    MessageType,
    encode_message,
    decode_message,
)
from common.config import SERVER_HOST, SERVER_PORT, BUFFER_SIZE


class ClientController:
    def __init__(self, iterations: int):
        self.id: str | None = None   # <- lo asigna el servidor en START
        self.iterations = iterations

        self.reader = None
        self.writer = None

        self.neighbours: list[str] = []
        self.pending_acks: set[str] = set()

        # Evento para esperar a que lleguen todos los ACKs
        self.acks_done = asyncio.Event()

        # Métricas: lista de tiempos de respuesta por ciclo
        self.latencies: list[float] = []

    # ---------------- CONEXIÓN ----------------
    async def connect(self):
        """Establece conexión con el servidor y espera START."""
        self.reader, self.writer = await asyncio.open_connection(
            SERVER_HOST, SERVER_PORT
        )
        
        # Obtener el socket subyacente de la conexión asyncio
        transport = self.writer.transport
        sock = transport.get_extra_info('socket')
        
        # Establecer el tamaño del buffer (en bytes) para el envío y recepción de datos
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, BUFFER_SIZE)  
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, BUFFER_SIZE)  
        
        assert (
            self.reader is not None and self.writer is not None
        ), "Error: conexión no establecida"

        # JOIN con ID temporal (el servidor lo ignora y genera uno nuevo)
        join_msg = make_message(MessageType.JOIN, "TEMP")
        self.writer.write(encode_message(join_msg))
        await self.writer.drain()
        print("[CLIENTE] Conectado al servidor, esperando ID y vecinos...")

        await self.listen_server()

    # ---------------- ESCUCHA ----------------
    async def listen_server(self):
        """Escucha y procesa mensajes del servidor."""
        assert self.reader is not None

        while data := await self.reader.readline():
            msg = decode_message(data)
            msg_type = msg.get("type")

            if msg_type == MessageType.START.value:
                # Recibir ID asignado y vecinos y arrancar simulación
                data_start = msg["data"]
                self.id = data_start.get("id")
                self.neighbours = data_start.get("neighbours", [])
                print(f"[{self.id}] Vecinos asignados: {len(self.neighbours)}")
                asyncio.create_task(self.run_simulation())

            elif msg_type == MessageType.INFO.value:
                sender = msg.get("client_id")
                await self._handle_info(sender)

            elif msg_type == MessageType.ACK.value:
                sender = msg["data"].get("from")
                await self._handle_ack(sender)

            elif msg_type == MessageType.END.value:
                print(f"[{self.id}] Finalización recibida del servidor")
                break

        assert self.writer is not None
        self.writer.close()
        await self.writer.wait_closed()

    # ---------------- PROCESAMIENTO DE MENSAJES ----------------
    async def _handle_info(self, sender: str | None):
        """
        Procesa INFO recibido de un vecino (vía servidor).
        En el modelo CAR, el vecino sólo debe enviar un ACK.
        """
        if sender is None:
            return
        assert self.writer is not None and self.id is not None

        ack_msg = make_message(
            MessageType.ACK, self.id, {"ack_to": sender}
        )
        self.writer.write(encode_message(ack_msg))
        await self.writer.drain()

    async def _handle_ack(self, sender: str | None):
        """Confirma recepción de ACKs esperados."""
        if sender is None:
            return

        if sender in self.pending_acks:
            self.pending_acks.remove(sender)

            # Si ya no quedan ACKs pendientes → liberar el evento
            if not self.pending_acks:
                self.acks_done.set()

    # ---------------- SIMULACIÓN ----------------
    async def run_simulation(self):
        """
        Ciclo principal de simulación CAR.
        Cada iteración:
           - genera (x, y, z),
           - envía INFO,
           - espera ACKs de todos los vecinos sin polling,
           - mide el tiempo de respuesta.
        """
        assert self.writer is not None and self.id is not None

        for _ in range(self.iterations):
            await self._send_coords_and_wait_acks()

            # Pausa ligera para no monopolizar la CPU
            await asyncio.sleep(random.uniform(0.01, 0.05))

        # Envío de métricas finales (tiempo medio de respuesta)
        avg_resp = sum(self.latencies) / len(self.latencies) if self.latencies else 0.0

        msg = make_message(
            MessageType.END,
            self.id,
            {"avg_response_time": avg_resp},
        )
        self.writer.write(encode_message(msg))
        await self.writer.drain()
        print(
            f"[{self.id}] Métricas enviadas "
            f"(tiempo medio de respuesta: {avg_resp * 1000:.2f} ms)"
        )

    # ---------------- ENVÍO Y ESPERA SIN POLLING ----------------
    async def _send_coords_and_wait_acks(self):
        """Envía INFO con coordenadas y espera ACKs usando asyncio.Event (sin polling)."""
        assert self.writer is not None and self.id is not None

        coords = {
            "x": random.uniform(0.0, 100.0),
            "y": random.uniform(0.0, 100.0),
            "z": random.uniform(0.0, 100.0),
        }

        # Preparar espera de ACKs
        self.pending_acks = set(self.neighbours)
        self.acks_done.clear()

        start_time = time.perf_counter()

        # Enviar INFO
        info_msg = make_message(
            MessageType.INFO,
            self.id,
            coords,
        )
        self.writer.write(encode_message(info_msg))
        await self.writer.drain()

        # Esperar a que lleguen todos los ACKs sin polling
        try:
            await asyncio.wait_for(self.acks_done.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            print(
                f"[{self.id}] Timeout: {len(self.pending_acks)} ACK(s) pendientes"
            )

        latency = time.perf_counter() - start_time
        self.latencies.append(latency)
