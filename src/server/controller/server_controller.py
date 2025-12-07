# server/controller/server_controller.py
import asyncio
import socket
import platform
import winloop  # alternativa a uvloop para Windows

from common.protocol import make_message, MessageType, encode_message, decode_message
from common.config import SERVER_HOST, SERVER_PORT, BUFFER_SIZE
from common.logger import logger
from common.utils import generate_client_id

class ServerController:
    """
    Servidor optimizado para manejar decenas de miles de conexiones en Windows.
    Utiliza winloop para mayor rendimiento y desactiva Nagle. Ajusta el semáforo
    de concurrencia en función del número de clientes.
    """
    def __init__(self, total_clients: int, group_size: int):
        self.total_clients = total_clients
        self.group_size = group_size

        self.clients: dict[str, asyncio.StreamWriter] = {}
        self.neighbours: dict[str, list[str]] = {}
        self.groups: list[list[str]] = []
        self.client_group: dict[str, int] = {}

        self.simulation_started = False
        self.client_metrics: dict[str, float] = {}

        # Semáforo dinámico: en Windows permitimos hasta total_clients/20 o 2000 conexiones simultáneas
        max_concurrent = max(500, min(2000, self.total_clients // 20))
        self.semaphore = asyncio.Semaphore(max_concurrent)

        logger.info(f"[SERVIDOR] Iniciado (N={total_clients}, V={group_size})")

    async def start(self):
        """
        Inicia el servidor. En Windows instalamos winloop para obtener un bucle de eventos
        más rápido. No se usa reuse_port porque no está soportado en Windows:contentReference[oaicite:6]{index=6}.
        """
        # Instalar winloop como bucle de eventos
        winloop.install()

        # Crear el servidor TCP
        server = await asyncio.start_server(
            self.handle_client,
            SERVER_HOST,
            SERVER_PORT,
            backlog=self.total_clients * 2  # cola de conexiones grande
        )
        logger.info(f"[SERVIDOR] Escuchando en {SERVER_HOST}:{SERVER_PORT}")

        async with server:
            await server.serve_forever()

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """
        Maneja la conexión de un cliente: asigna un ID, lo agrega al grupo y procesa sus mensajes.
        Ajusta el socket para baja latencia (desactiva Nagle y aumenta buffers).
        """
        try:
            data = await reader.readline()
            if not data:
                writer.close()
                await writer.wait_closed()
                return

            # Configurar el socket del cliente
            transport = writer.transport
            sock: socket.socket = transport.get_extra_info("socket")
            if sock is not None:
                # Desactivar Nagle (TCP_NODELAY):contentReference[oaicite:7]{index=7}
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, BUFFER_SIZE)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, BUFFER_SIZE)

            # Ignoramos el ID temporal enviado en el JOIN y generamos uno nuevo
            _ = decode_message(data)
            cid = generate_client_id()

            self.clients[cid] = writer
            self._assign_to_group(cid)

            logger.info(f"[+] Cliente {cid} conectado {len(self.clients)}/{self.total_clients}")

            # Iniciar simulación cuando estén todos los clientes
            if not self.simulation_started and len(self.clients) == self.total_clients:
                self.simulation_started = True
                await self.start_simulation()

            # Procesar mensajes recibidos
            while data := await reader.readline():
                msg = decode_message(data)
                await self.process_message(msg)

        except ConnectionResetError as e:
            logger.warning(f"[ERROR] Conexión restablecida con el cliente: {e}")
        except asyncio.CancelledError:
            logger.warning(f"[ERROR] Conexión cancelada para el cliente.")
        except Exception as e:
            logger.error(f"[ERROR] Error inesperado con el cliente: {e}")
        finally:
            writer.close()
            await writer.wait_closed()

    def _assign_to_group(self, cid: str):
        """
        Asigna un cliente a un grupo de tamaño V y actualiza la lista de vecinos.
        """
        if not self.groups or len(self.groups[-1]) >= self.group_size:
            self.groups.append([cid])
        else:
            self.groups[-1].append(cid)

        group_idx = len(self.groups) - 1
        self.client_group[cid] = group_idx

        group = self.groups[-1]
        for c in group:
            self.neighbours[c] = [n for n in group if n != c]

    async def start_simulation(self):
        """
        Envía un mensaje START a todos los clientes para iniciar la simulación.
        """
        logger.info("[SERVIDOR] Enviando START a todos los clientes")
        tasks = []
        for cid, w in self.clients.items():
            msg = make_message(
                MessageType.START,
                "server",
                {"id": cid, "neighbours": self.neighbours[cid]},
            )
            tasks.append(self._send_message(w, msg))
        await asyncio.gather(*tasks)
        logger.info("[SERVIDOR] Simulación iniciada")

    async def _send_message(self, writer: asyncio.StreamWriter, message: dict):
        """
        Envía un mensaje al cliente respetando el semáforo de concurrencia.
        """
        async with self.semaphore:
            writer.write(encode_message(message))
            await writer.drain()

    async def process_message(self, msg: dict):
        """
        Procesa los mensajes INFO, ACK y END de los clientes.
        """
        cid = msg["client_id"]
        mtype = msg["type"]

        if mtype == MessageType.INFO.value:
            forward = {
                "type": MessageType.INFO.value,
                "client_id": cid,
                "data": msg["data"],
            }
            tasks = []
            for n in self.neighbours.get(cid, []):
                if n in self.clients:
                    tasks.append(self._send_message(self.clients[n], forward))
            await asyncio.gather(*tasks)

        elif mtype == MessageType.ACK.value:
            dest = msg["data"].get("ack_to")
            if dest in self.clients:
                ack_msg = {
                    "type": MessageType.ACK.value,
                    "client_id": cid,
                    "data": {"from": cid},
                }
                await self._send_message(self.clients[dest], ack_msg)

        elif mtype == MessageType.END.value:
            avg_resp = msg["data"].get("avg_response_time", 0.0)
            self.client_metrics[cid] = avg_resp
            logger.info(f"[END] Métrica recibida de {cid} ({avg_resp*1000:.2f} ms)")

            if len(self.client_metrics) == self.total_clients:
                await self._finalize_simulation()

    async def _finalize_simulation(self):
        """
        Calcula las métricas finales por grupo y envía END a todos los clientes.
        """
        logger.info("[SERVIDOR] Calculando métricas finales...")

        total = len(self.client_metrics)
        global_avg = sum(self.client_metrics.values()) / total if total > 0 else 0.0

        logger.info("----- MÉTRICAS POR GRUPO -----")
        for idx, group in enumerate(self.groups):
            vals = [self.client_metrics[c] for c in group if c in self.client_metrics]
            g_avg = sum(vals) / len(vals) if vals else 0.0
            logger.info(f"Grupo {idx}: media = {g_avg*1000:.2f} ms")

        logger.info("-----------------------------")
        logger.info(f"Media global del sistema: {global_avg*1000:.2f} ms")

        # Notificar finalización a todos los clientes
        end_msg = make_message(MessageType.END, "server", {"msg": "Fin"})
        for cid, w in self.clients.items():
            await self._send_message(w, end_msg)

        await asyncio.sleep(1)
        logger.info("[SERVIDOR] Simulación completada")
