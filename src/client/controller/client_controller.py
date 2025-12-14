import asyncio
import random
import time
import socket

from common.protocol import make_message, MessageType, encode_message, decode_message
from common.config import SERVER_HOST, SERVER_PORT, BUFFER_SIZE

"""
Cliente del Sistema Realidad Aumentada Colaborativa mediante Sockets TCP

Flujo:
  - Conecta al servidor y envía JOIN
  - Espera START con su id y su lista de vecinos
  - Por iteración:
      1) Envía INFO con coordenadas
      2) Espera ACKs de todos los vecinos (o timeout)
  - Envía END con métricas al servidor
"""

_DRAIN_HIGH_WATER = 256 * 1024
CONNECT_TIMEOUT = 10.0  # evita que open_connection se quede colgado en remoto


class ClientController:
    def __init__(self, iterations: int):
        self.id: str | None = None
        self.iterations = iterations

        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None

        self.neighbours: list[str] = []
        self.pending_acks: set[str] = set()
        self.acks_done = asyncio.Event()

        self.latencies: list[float] = []
        self.acks_expected_total = 0
        self.acks_received_total = 0

        # Cuenta cuántas veces no llegaron todos los ACKs antes del timeout
        self.timeouts = 0

    async def connect(self, connect_gate: asyncio.Semaphore | None = None):
        """
        Conecta con el servidor.
        connect_gate limita solo la fase de handshake (conexión TCP).
        """
        if connect_gate:
            await connect_gate.acquire()
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(SERVER_HOST, SERVER_PORT),
                timeout=CONNECT_TIMEOUT
            )
        finally:
            if connect_gate:
                connect_gate.release()

        assert self.writer is not None
        transport = self.writer.transport
        sock: socket.socket = transport.get_extra_info("socket")

        if sock is not None:
            # Ajustes orientados a latencia y a conexiones largas
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, BUFFER_SIZE)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, BUFFER_SIZE)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

        try:
            transport.set_write_buffer_limits(high=256 * 1024, low=64 * 1024)
        except Exception:
            pass

        join_msg = make_message(MessageType.JOIN, "TEMP")
        self.writer.write(encode_message(join_msg))
        await self._maybe_drain()

        await self.listen_server()

    async def _maybe_drain(self):
        """
        Evita hacer drain() por cada write().
        Solo drenamos si el buffer del transport supera el umbral.
        """
        assert self.writer is not None
        try:
            tr = self.writer.transport
            if tr.get_write_buffer_size() > _DRAIN_HIGH_WATER:
                await self.writer.drain()
        except Exception:
            await self.writer.drain()

    async def listen_server(self):
        """Bucle de lectura: recibe START / INFO / ACK / END."""
        assert self.reader is not None

        while data := await self.reader.readline():
            msg = decode_message(data)
            t = msg.get("type")

            if t == MessageType.START.value:
                data_start = msg["data"]
                self.id = data_start.get("id")
                self.neighbours = data_start.get("neighbours", [])
                asyncio.create_task(self.run_simulation())

            elif t == MessageType.INFO.value:
                sender = msg.get("client_id")
                await self._handle_info(sender)

            elif t == MessageType.ACK.value:
                sender = msg["data"].get("from")
                await self._handle_ack(sender)

            elif t == MessageType.END.value:
                break

        assert self.writer is not None
        self.writer.close()
        await self.writer.wait_closed()

    async def _handle_info(self, sender: str | None):
        """Al recibir INFO de un vecino, contestamos con ACK hacia ese emisor."""
        if sender is None:
            return
        assert self.writer is not None and self.id is not None

        ack_msg = make_message(MessageType.ACK, self.id, {"ack_to": sender})
        self.writer.write(encode_message(ack_msg))
        await self._maybe_drain()

    async def _handle_ack(self, sender: str | None):
        """Marca la llegada de un ACK. Cuando ya no quedan pendientes, liberamos el evento."""
        if sender is None:
            return
        if sender in self.pending_acks:
            self.pending_acks.remove(sender)
            self.acks_received_total += 1
            if not self.pending_acks:
                self.acks_done.set()

    async def run_simulation(self):
        """Ejecuta S iteraciones y reporta métricas al final."""
        assert self.writer is not None and self.id is not None

        for _ in range(self.iterations):
            await self._send_coords_and_wait_acks()
            await asyncio.sleep(random.uniform(0.01, 0.05))

        avg_resp = sum(self.latencies) / len(self.latencies) if self.latencies else 0.0

        msg = make_message(
            MessageType.END,
            self.id,
            {
                "avg_response_time": avg_resp,
                "acks_expected": self.acks_expected_total,
                "acks_received": self.acks_received_total,
                "timeouts": self.timeouts,
            }
        )
        self.writer.write(encode_message(msg))
        await self._maybe_drain()

    async def _send_coords_and_wait_acks(self):
        """
        Envía coordenadas al servidor y espera ACKs de todos los vecinos.
        Si falta alguno, el timeout lo registra como métrica de estabilidad.
        """
        assert self.writer is not None and self.id is not None

        coords = {
            "x": random.uniform(0, 100),
            "y": random.uniform(0, 100),
            "z": random.uniform(0, 100),
        }

        self.acks_expected_total += len(self.neighbours)
        self.pending_acks = set(self.neighbours)
        self.acks_done.clear()

        t0 = time.perf_counter()

        info_msg = make_message(MessageType.INFO, self.id, coords)
        self.writer.write(encode_message(info_msg))
        await self._maybe_drain()

        try:
            await asyncio.wait_for(self.acks_done.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            self.timeouts += 1

        self.latencies.append(time.perf_counter() - t0)
