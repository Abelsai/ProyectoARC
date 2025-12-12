# client/controller/client_controller.py
import asyncio
import random
import time
import socket
import winloop  # alternativa a uvloop en Windows

from common.protocol import make_message, MessageType, encode_message, decode_message
from common.config import SERVER_HOST, SERVER_PORT, BUFFER_SIZE

class ClientController:
    """
    Cliente optimizado para Windows: instala winloop, desactiva Nagle y espera ACKs sin polling.
    """
    def __init__(self, iterations: int):
        self.id: str | None = None
        self.iterations = iterations

        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None

        self.neighbours: list[str] = []
        self.pending_acks: set[str] = set()
        self.acks_done = asyncio.Event()
        self.latencies: list[float] = []

    async def connect(self):
        """
        Conecta con el servidor y espera el mensaje START. Instala winloop para acelerar el bucle.
        """
        winloop.install()
        self.reader, self.writer = await asyncio.open_connection(SERVER_HOST, SERVER_PORT)

        # Ajustar el socket del cliente
        transport = self.writer.transport
        sock: socket.socket = transport.get_extra_info("socket")
        if sock is not None:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, BUFFER_SIZE)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, BUFFER_SIZE)

        assert self.reader is not None and self.writer is not None, "Error de conexión"

        # Enviar JOIN
        join_msg = make_message(MessageType.JOIN, "TEMP")
        self.writer.write(encode_message(join_msg))
        await self.writer.drain()
        print("[CLIENTE] Conectado al servidor, esperando ID y vecinos...")

        await self.listen_server()

    async def listen_server(self):
        """
        Escucha los mensajes del servidor y actúa según su tipo.
        """
        assert self.reader is not None

        while data := await self.reader.readline():
            msg = decode_message(data)
            msg_type = msg.get("type")

            if msg_type == MessageType.START.value:
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

    async def _handle_info(self, sender: str | None):
        """
        Envía un ACK al recibir coordenadas de un vecino.
        """
        if sender is None:
            return
        assert self.writer is not None and self.id is not None

        ack_msg = make_message(MessageType.ACK, self.id, {"ack_to": sender})
        self.writer.write(encode_message(ack_msg))
        await self.writer.drain()

    async def _handle_ack(self, sender: str | None):
        """
        Marca la llegada de un ACK. Cuando todos han llegado se activa el evento.
        """
        if sender is None:
            return

        if sender in self.pending_acks:
            self.pending_acks.remove(sender)
            if not self.pending_acks:
                self.acks_done.set()

    async def run_simulation(self):
        """
        Bucle principal de simulación: envía coordenadas y espera ACKs sin polling.
        """
        assert self.writer is not None and self.id is not None

        for _ in range(self.iterations):
            await self._send_coords_and_wait_acks()
            await asyncio.sleep(random.uniform(0.01, 0.05))

        # Enviar la latencia media
        avg_resp = sum(self.latencies) / len(self.latencies) if self.latencies else 0.0
        msg = make_message(MessageType.END, self.id, {"avg_response_time": avg_resp})
        self.writer.write(encode_message(msg))
        await self.writer.drain()
        print(f"[{self.id}] Métricas enviadas (tiempo medio: {avg_resp * 1000:.2f} ms)")

    async def _send_coords_and_wait_acks(self):
        """
        Envía un mensaje INFO con coordenadas y espera la recepción de todos los ACKs.
        """
        assert self.writer is not None and self.id is not None

        coords = {
            "x": random.uniform(0.0, 100.0),
            "y": random.uniform(0.0, 100.0),
            "z": random.uniform(0.0, 100.0),
        }
        
        await asyncio.sleep(random.uniform(0.01, 0.05))  

        self.pending_acks = set(self.neighbours)
        self.acks_done.clear()

        start_time = time.perf_counter()

        info_msg = make_message(MessageType.INFO, self.id, coords)
        self.writer.write(encode_message(info_msg))
        await self.writer.drain()

        try:
            await asyncio.wait_for(self.acks_done.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            print(f"[{self.id}] Timeout: {len(self.pending_acks)} ACK(s) pendientes")

        latency = time.perf_counter() - start_time
        self.latencies.append(latency)
