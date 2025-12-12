import asyncio
import socket
import contextlib
import winloop

from common.protocol import make_message, MessageType, encode_message, decode_message
from common.config import SERVER_HOST, SERVER_PORT, BUFFER_SIZE
from common.logger import logger
from common.utils import generate_client_id


class _Conn:
    """
    Actor de escritura por conexión con DOS colas:
      - q_prio: ACK/START/END (prioridad)
      - q_bulk: INFO (tráfico masivo)
    Sin drops: hacemos backpressure por conexión (await q.put).
    El writer drena por “cola vacía”, por tamaño (64KB) o por tiempo (~1 ms).
    """
    __slots__ = ("cid", "writer", "q_prio", "q_bulk", "_task",
                 "_pending_bytes", "_loop", "_last_flush")

    def __init__(self, cid: str, writer: asyncio.StreamWriter):
        self.cid = cid
        self.writer = writer
        self.q_prio: asyncio.Queue[bytes] = asyncio.Queue(maxsize=4096)
        self.q_bulk: asyncio.Queue[bytes] = asyncio.Queue(maxsize=4096)
        self._pending_bytes = 0
        self._loop = asyncio.get_event_loop()
        self._last_flush = self._loop.time()
        self._task = asyncio.create_task(self._writer_loop(), name=f"writer[{cid}]")

        # Límite de buffer de escritura del transporte (backpressure fino)
        with contextlib.suppress(Exception):
            self.writer.transport.set_write_buffer_limits(high=256 * 1024, low=64 * 1024)

    async def _writer_loop(self):
        try:
            while True:
                # 1) Siempre drenar prioridad primero
                if not self.q_prio.empty():
                    data = await self.q_prio.get()
                else:
                    data = await self.q_bulk.get()

                self.writer.write(data)
                self._pending_bytes += len(data)

                # Criterios de flush: cola vacía, tamaño o temporización
                now = self._loop.time()
                if (self.q_prio.empty() and self.q_bulk.empty()) or \
                   (self._pending_bytes >= 64 * 1024) or \
                   (now - self._last_flush) >= 0.001:
                    await self.writer.drain()
                    self._pending_bytes = 0
                    self._last_flush = now
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"[writer {self.cid}] error: {e}")
        finally:
            with contextlib.suppress(Exception):
                self.writer.close()
                await self.writer.wait_closed()

    async def send_prio(self, payload: bytes):
        # No drop: si el peer está atascado, solo frena ESTA conexión.
        await self.q_prio.put(payload)

    async def send_bulk(self, payload: bytes):
        await self.q_bulk.put(payload)

    async def close(self):
        self._task.cancel()
        with contextlib.suppress(Exception):
            await self._task


class ServerController:
    """
    Servidor optimizado para Windows:
      - winloop
      - escritor por conexión con DOS colas (ACK/START/END priorizados)
      - arranque por grupo (sin barrera global)
      - logs ligeros
    """
    def __init__(self, total_clients: int, group_size: int):
        self.total_clients = total_clients
        self.group_size = group_size

        self.clients: dict[str, _Conn] = {}          # id -> _Conn
        self.neighbours: dict[str, list[str]] = {}   # id -> vecinos
        self.groups: list[list[str]] = []            # grupos (ids)
        self.client_group: dict[str, int] = {}       # id -> índice grupo

        self.simulation_started_groups: set[int] = set()
        self.client_metrics: dict[str, float] = {}
        self._connected = 0

        logger.info(f"[SERVIDOR] Iniciado (N={total_clients}, V={group_size})")

    async def start(self):
        winloop.install()
        loop = asyncio.get_event_loop()
        logger.info(f"[SERVIDOR] Bucle de eventos: {type(loop)}")

        server = await asyncio.start_server(
            self.handle_client,
            SERVER_HOST,
            SERVER_PORT,
            backlog=max(self.total_clients * 2, 4096)
        )
        logger.info(f"[SERVIDOR] Escuchando en {SERVER_HOST}:{SERVER_PORT}")
        async with server:
            await server.serve_forever()

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        conn: _Conn | None = None
        cid: str | None = None
        try:
            # JOIN
            data = await reader.readline()
            if not data:
                writer.close()
                await writer.wait_closed()
                return

            # Ajustes de socket
            transport = writer.transport
            sock: socket.socket = transport.get_extra_info("socket")
            if sock is not None:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, BUFFER_SIZE)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, BUFFER_SIZE)

            _ = decode_message(data)  # JOIN ignorado
            cid = generate_client_id()

            conn = _Conn(cid, writer)
            self.clients[cid] = conn
            self._assign_to_group(cid)

            self._connected += 1
            if self._connected % 1000 == 0:
                logger.info(f"[+] Conectados {self._connected}/{self.total_clients}")

            # Si el grupo se acaba de llenar -> START de ese grupo
            gidx = self.client_group[cid]
            if len(self.groups[gidx]) == self.group_size and gidx not in self.simulation_started_groups:
                await self._start_group(gidx)

            # Bucle de mensajes
            while True:
                data = await reader.readline()
                if not data:
                    break
                msg = decode_message(data)
                await self.process_message(msg)
        except ConnectionResetError as e:
            logger.warning(f"[WARN] Conexión restablecida con el cliente: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[ERROR] Cliente error inesperado: {e}")
        finally:
            try:
                if cid is not None:
                    with contextlib.suppress(KeyError):
                        del self.clients[cid]
                if conn is not None:
                    await conn.close()
            except Exception:
                pass

    def _assign_to_group(self, cid: str):
        if not self.groups or len(self.groups[-1]) >= self.group_size:
            self.groups.append([cid])
        else:
            self.groups[-1].append(cid)

        gidx = len(self.groups) - 1
        self.client_group[cid] = gidx

        group = self.groups[gidx]
        for c in group:
            self.neighbours[c] = [n for n in group if n != c]

    async def _start_group(self, gidx: int):
        self.simulation_started_groups.add(gidx)
        group = self.groups[gidx]
        for cid in group:
            conn = self.clients.get(cid)
            if not conn:
                continue
            start_msg = make_message(
                MessageType.START, "server",
                {"id": cid, "neighbours": self.neighbours.get(cid, [])}
            )
            # START es prioritario
            asyncio.create_task(conn.send_prio(encode_message(start_msg)))
        logger.info(f"[SERVIDOR] Grupo {gidx} START ({len(group)} clientes)")

    async def process_message(self, msg: dict):
        cid = msg["client_id"]
        mtype = msg["type"]

        if mtype == MessageType.INFO.value:
            # Reutiliza bytes del INFO para todos
            b = encode_message({
                "type": MessageType.INFO.value,
                "client_id": cid,
                "data": msg["data"],
            })
            # INFO -> cola bulk
            for n in self.neighbours.get(cid, []):
                conn = self.clients.get(n)
                if conn:
                    asyncio.create_task(conn.send_bulk(b))

        elif mtype == MessageType.ACK.value:
            dest = msg["data"].get("ack_to")
            conn = self.clients.get(dest)
            if conn:
                # ACK -> prioridad
                b = encode_message({
                    "type": MessageType.ACK.value,
                    "client_id": cid,
                    "data": {"from": cid},
                })
                asyncio.create_task(conn.send_prio(b))

        elif mtype == MessageType.END.value:
            avg_resp = float(msg["data"].get("avg_response_time", 0.0))
            self.client_metrics[cid] = avg_resp
            if len(self.client_metrics) % 1000 == 0:
                logger.info(f"[END] Recibidas {len(self.client_metrics)}/{self.total_clients} métricas")
            if len(self.client_metrics) == self.total_clients:
                await self._finalize_simulation()

    async def _finalize_simulation(self):
        logger.info("[SERVIDOR] Calculando métricas finales...")

        total = len(self.client_metrics)
        global_avg = (sum(self.client_metrics.values()) / total) if total else 0.0

        logger.info("----- MÉTRICAS POR GRUPO -----")
        for idx, group in enumerate(self.groups):
            vals = [self.client_metrics[c] for c in group if c in self.client_metrics]
            g_avg = (sum(vals) / len(vals)) if vals else 0.0
            logger.info(f"Grupo {idx}: media = {g_avg*1000:.2f} ms")
        logger.info("-----------------------------")
        logger.info(f"Media global del sistema: {global_avg*1000:.2f} ms")

        # END -> prioridad
        end_bytes = encode_message(make_message(MessageType.END, "server", {"msg": "Fin"}))
        for conn in list(self.clients.values()):
            asyncio.create_task(conn.send_prio(end_bytes))

        # Deja vaciar colas
        await asyncio.sleep(0.5)
        logger.info("[SERVIDOR] Simulación completada")
