# server/controller/server_controller.py
import asyncio
import socket
import contextlib
import time

from common.protocol import make_message, MessageType, encode_message, decode_message
from common.config import SERVER_HOST, SERVER_PORT
from common.logger import logger
from common.utils import generate_client_id

# psutil es opcional
try:
    import psutil
    _PSUTIL_OK = True
except Exception:
    _PSUTIL_OK = False


class ServerController:
    """
    Servidor optimizado (sin writer-task por conexión):
      - START único a todos cuando estén todos conectados
      - Envío directo por StreamWriter (sin colas por conexión)
      - Backpressure ligero: si el buffer crece, se programa drain() con timeout
      - Monitor de carga
    """
    MONITOR_INTERVAL = 1.0  # s

    # si el buffer del transport supera esto, drenamos (en una tarea corta)
    _DRAIN_HIGH_WATER = 512 * 1024
    _DRAIN_TIMEOUT = 5.0

    def __init__(self, total_clients: int, group_size: int, host: str = SERVER_HOST, port: int = 8888):
        self.total_clients = total_clients
        self.group_size = group_size
        self.host = host
        self.port = port

        # id -> StreamWriter
        self.clients: dict[str, asyncio.StreamWriter] = {}

        self.neighbours: dict[str, list[str]] = {}
        self.groups: list[list[str]] = []
        self.client_group: dict[str, int] = {}

        self.client_metrics: dict[str, float] = {}

        self.acks_expected_sum = 0
        self.acks_received_sum = 0

        # Monitor
        self._msg_counter = 0
        self._peak_msgs_per_sec = 0.0
        self._peak_cpu_total = None
        self._peak_cpu_process = None
        self._peak_ts = None
        self._monitor_task: asyncio.Task | None = None

        # START/finalize
        self._start_sent = False
        self._start_lock = asyncio.Lock()
        self._finalized = False

        # drain tasks por cliente (solo cuando hace falta)
        self._drain_tasks: dict[str, asyncio.Task] = {}

        logger.info(f"[SERVIDOR] Iniciado (N={total_clients}, V={group_size}, host={self.host}, port={self.port})")

    async def start(self):
        loop = asyncio.get_running_loop()
        logger.info(f"[SERVIDOR] Bucle de eventos: {type(loop)}")

        self._monitor_task = asyncio.create_task(self._monitor_load(), name="monitor_load")

        server = await asyncio.start_server(
            self.handle_client,
            self.host,
            self.port,
            backlog=socket.SOMAXCONN,  # el SO lo ajusta; mejor que números enormes
        )
        logger.info(f"[SERVIDOR] Escuchando en {self.host}:{self.port}")
        async with server:
            await server.serve_forever()

    async def _monitor_load(self):
        prev_count = 0
        if _PSUTIL_OK:
            _ = psutil.cpu_percent(interval=None)
            _p = psutil.Process()
            _ = _p.cpu_percent(interval=None)

        while True:
            await asyncio.sleep(self.MONITOR_INTERVAL)
            now = time.perf_counter()
            current = self._msg_counter
            delta = current - prev_count
            prev_count = current
            msgs_per_sec = delta / self.MONITOR_INTERVAL

            cpu_total = None
            cpu_proc = None
            if _PSUTIL_OK:
                try:
                    cpu_total = psutil.cpu_percent(interval=None)
                    cpu_proc = psutil.Process().cpu_percent(interval=None)
                except Exception:
                    pass

            if msgs_per_sec > self._peak_msgs_per_sec:
                self._peak_msgs_per_sec = msgs_per_sec
                self._peak_ts = now
                if cpu_total is not None:
                    self._peak_cpu_total = cpu_total
                if cpu_proc is not None:
                    self._peak_cpu_process = cpu_proc

    def _configure_socket(self, writer: asyncio.StreamWriter):
        transport = writer.transport
        sock: socket.socket = transport.get_extra_info("socket")
        if sock is not None:
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            except Exception:
                pass
        try:
            transport.set_write_buffer_limits(high=256 * 1024, low=64 * 1024)
        except Exception:
            pass

    def _send_bytes(self, cid: str, b: bytes):
        """Envío rápido + backpressure: si el buffer crece, programamos un drain corto."""
        w = self.clients.get(cid)
        if not w:
            return
        try:
            w.write(b)
        except Exception:
            return

        # backpressure: si el buffer está alto, drenamos (sin bloquear hot-path)
        try:
            tr = w.transport
            if tr.get_write_buffer_size() >= self._DRAIN_HIGH_WATER:
                if cid not in self._drain_tasks or self._drain_tasks[cid].done():
                    self._drain_tasks[cid] = asyncio.create_task(self._drain_writer(cid, w))
        except Exception:
            pass

    async def _drain_writer(self, cid: str, w: asyncio.StreamWriter):
        try:
            await asyncio.wait_for(w.drain(), timeout=self._DRAIN_TIMEOUT)
        except Exception:
            # si falla, probablemente el socket murió o está muy saturado
            pass
        finally:
            # limpia si sigue siendo la misma conexión
            t = self._drain_tasks.get(cid)
            if t and t is asyncio.current_task():
                self._drain_tasks.pop(cid, None)

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        cid: str | None = None
        try:
            data = await reader.readline()
            if not data:
                writer.close()
                return

            self._configure_socket(writer)

            _ = decode_message(data)  # JOIN (no lo necesitamos para id)
            cid = generate_client_id()

            self.clients[cid] = writer
            self._assign_to_group(cid)

            asyncio.create_task(self._maybe_send_start())

            while True:
                data = await reader.readline()
                if not data:
                    break
                msg = decode_message(data)
                self._process_message_fast(msg)

        except ConnectionResetError as e:
            logger.warning(f"[WARN] Conexión restablecida con el cliente: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[ERROR] Cliente error inesperado: {e}")
        finally:
            if cid:
                self.clients.pop(cid, None)
                # cancela drain si existía
                t = self._drain_tasks.pop(cid, None)
                if t:
                    t.cancel()

            with contextlib.suppress(Exception):
                writer.close()

    def _assign_to_group(self, cid: str):
        if self._start_sent:
            return

        if not self.groups or len(self.groups[-1]) >= self.group_size:
            self.groups.append([cid])
        else:
            self.groups[-1].append(cid)

        gidx = len(self.groups) - 1
        self.client_group[cid] = gidx

        group = self.groups[gidx]
        for c in group:
            self.neighbours[c] = [n for n in group if n != c]

    async def _maybe_send_start(self):
        if self._start_sent or len(self.clients) < self.total_clients:
            return
        async with self._start_lock:
            if self._start_sent or len(self.clients) < self.total_clients:
                return
            self._start_sent = True
            await self._send_start()

    async def _send_start(self):
        for gidx in range(len(self.groups)):
            group = self.groups[gidx]
            for cid in group:
                start_msg = make_message(
                    MessageType.START, "server",
                    {"id": cid, "neighbours": self.neighbours.get(cid, [])}
                )
                self._send_bytes(cid, encode_message(start_msg))

        logger.info(f"[SERVIDOR] START enviado a {sum(len(g) for g in self.groups)} clientes en {self.port}")

    def _process_message_fast(self, msg: dict):
        cid = msg["client_id"]
        mtype = msg["type"]

        if mtype in (MessageType.INFO.value, MessageType.ACK.value, MessageType.END.value):
            self._msg_counter += 1

        if mtype == MessageType.INFO.value:
            payload = {
                "type": MessageType.INFO.value,
                "client_id": cid,
                "data": msg["data"],
            }
            b = encode_message(payload)
            for n in self.neighbours.get(cid, []):
                self._send_bytes(n, b)

        elif mtype == MessageType.ACK.value:
            dest = msg["data"].get("ack_to")
            if dest:
                ack_msg = {
                    "type": MessageType.ACK.value,
                    "client_id": cid,
                    "data": {"from": cid},
                }
                self._send_bytes(dest, encode_message(ack_msg))

        elif mtype == MessageType.END.value:
            if self._finalized:
                return

            data = msg.get("data", {})
            if cid in self.client_metrics:
                return

            avg_resp = float(data.get("avg_response_time", 0.0))
            self.client_metrics[cid] = avg_resp

            ae = int(data.get("acks_expected", 0))
            ar = int(data.get("acks_received", 0))
            self.acks_expected_sum += ae
            self.acks_received_sum += ar

            if len(self.client_metrics) % 1000 == 0:
                logger.info(f"[END] Recibidas {len(self.client_metrics)}/{self.total_clients} métricas en {self.port}")
            if len(self.client_metrics) == self.total_clients and not self._finalized:
                asyncio.create_task(self._finalize_simulation())

    async def _finalize_simulation(self):
        if self._finalized:
            return
        self._finalized = True

        logger.info("[SERVIDOR] Calculando métricas finales...")
        total = len(self.client_metrics)
        global_avg = (sum(self.client_metrics.values()) / total) if total else 0.0

        logger.info("----- MÉTRICAS POR GRUPO -----")
        for idx, group in enumerate(self.groups):
            vals = [self.client_metrics.get(c, 0.0) for c in group if c in self.client_metrics]
            g_avg = (sum(vals) / len(vals)) if vals else 0.0
            logger.info(f"Grupo {idx}: media = {g_avg*1000:.2f} ms")
        logger.info("-----------------------------")
        logger.info(f"Media global del sistema: {global_avg*1000:.2f} ms")

        if self.acks_expected_sum > 0:
            loss_pct_total = 100.0 * (max(0, self.acks_expected_sum - self.acks_received_sum) / self.acks_expected_sum)
        else:
            loss_pct_total = 0.0

        logger.info("===== RESUMEN ACKs =====")
        logger.info(
            "ACKs totales: %d/%d (pérdida %.2f%%)",
            self.acks_received_sum, self.acks_expected_sum, loss_pct_total
        )

        if self._peak_msgs_per_sec > 0:
            if _PSUTIL_OK and (self._peak_cpu_total is not None or self._peak_cpu_process is not None):
                logger.info(
                    "Pico de tráfico: ~%.0f msgs/s | CPU total=%.1f%% | CPU proceso=%.1f%%",
                    self._peak_msgs_per_sec,
                    (self._peak_cpu_total if self._peak_cpu_total is not None else -1.0),
                    (self._peak_cpu_process if self._peak_cpu_process is not None else -1.0),
                )
            else:
                logger.info("Pico de tráfico: ~%.0f msgs/s | CPU no disponible (instala psutil).", self._peak_msgs_per_sec)
        else:
            logger.info("No se detectó tráfico para calcular picos.")

        # END broadcast
        end_bytes = encode_message(make_message(MessageType.END, "server", {"msg": "Fin"}))
        for cid in list(self.clients.keys()):
            self._send_bytes(cid, end_bytes)

        if self._monitor_task:
            self._monitor_task.cancel()
            with contextlib.suppress(Exception):
                await self._monitor_task

        await asyncio.sleep(0.5)
        logger.info("[SERVIDOR] Simulación completada en puerto %s", self.port)
