# server/controller/server_controller.py
import asyncio
import socket
import contextlib
import time

import winloop
from common.protocol import make_message, MessageType, encode_message, decode_message
from common.config import SERVER_HOST, SERVER_PORT, BUFFER_SIZE
from common.logger import logger
from common.utils import generate_client_id

# psutil es opcional; si no está instalado, se desactivan métricas de CPU
try:
    import psutil
    _PSUTIL_OK = True
except Exception:
    _PSUTIL_OK = False


class _Conn:
    """Actor de escritura por conexión: aísla writers lentos y minimiza drains."""
    __slots__ = ("cid", "writer", "q", "_task", "_pending_bytes")

    def __init__(self, cid: str, writer: asyncio.StreamWriter):
        self.cid = cid
        self.writer = writer
        self.q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1000)
        self._pending_bytes = 0
        try:
            self.writer.transport.set_write_buffer_limits(high=256 * 1024, low=64 * 1024)
        except Exception:
            pass
        self._task = asyncio.create_task(self._writer_loop(), name=f"writer[{cid}]")

    async def _writer_loop(self):
        try:
            while True:
                data = await self.q.get()
                self.writer.write(data)
                self._pending_bytes += len(data)
                if self.q.empty() or self._pending_bytes >= 128 * 1024:
                    await self.writer.drain()
                    self._pending_bytes = 0
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"[writer {self.cid}] terminado por error: {e}")
        finally:
            with contextlib.suppress(Exception):
                self.writer.close()
                # En Windows evitamos esperar a wait_closed()

    def send_bytes(self, payload: bytes):
        try:
            self.q.put_nowait(payload)
        except asyncio.QueueFull:
            logger.debug(f"[writer {self.cid}] cola llena, drop 1 mensaje")

    def send_msg(self, msg: dict):
        self.send_bytes(encode_message(msg))

    async def close(self):
        self._task.cancel()
        with contextlib.suppress(Exception):
            await self._task


class ServerController:
    """
    Servidor optimizado:
      - winloop (Windows)
      - escritor por conexión (sin head-of-line blocking)
      - START único y simultáneo para todos (cuando estén todos conectados)
      - logs ligeros
      - monitor de carga: pico de tráfico y CPU en ese instante
    """
    MONITOR_INTERVAL = 1.0  # s

    def __init__(self, total_clients: int, group_size: int, host: str = SERVER_HOST, port: int = SERVER_PORT):
        self.total_clients = total_clients
        self.group_size = group_size
        self.host = host
        self.port = port

        self.clients: dict[str, _Conn] = {}          # id -> _Conn
        self.neighbours: dict[str, list[str]] = {}   # id -> vecinos
        self.groups: list[list[str]] = []            # lista de grupos (ids)
        self.client_group: dict[str, int] = {}       # id -> índice grupo

        self.client_metrics: dict[str, float] = {}

        # Acumuladores de ACKs (globales)
        self.acks_expected_sum = 0
        self.acks_received_sum = 0

        # Monitor de tráfico y CPU
        self._msg_counter = 0                      
        self._peak_msgs_per_sec = 0.0
        self._peak_cpu_total = None               
        self._peak_cpu_process = None             
        self._peak_ts = None                      
        self._monitor_task: asyncio.Task | None = None

       
        self._start_sent = False                 
        self._start_lock = asyncio.Lock()         
        self._finalized = False                   

        logger.info(f"[SERVIDOR] Iniciado (N={total_clients}, V={group_size}, host={self.host}, port={self.port})")

    async def start(self):
        winloop.install()
        loop = asyncio.get_event_loop()
        logger.info(f"[SERVIDOR] Bucle de eventos: {type(loop)}")

        # Arrancamos el monitor de tráfico/CPU
        self._monitor_task = asyncio.create_task(self._monitor_load(), name="monitor_load")

        server = await asyncio.start_server(
            self.handle_client,
            self.host,
            self.port,
            backlog=max(self.total_clients * 2, 4096),
        )
        logger.info(f"[SERVIDOR] Escuchando en {self.host}:{self.port}")
        async with server:
            await server.serve_forever()

    async def _monitor_load(self):
        """
        Cada MONITOR_INTERVAL segundos:
        - calcula msgs/s (delta de _msg_counter)
        - muestrea CPU (sistema y proceso, si psutil está disponible)
        - si es el mayor tráfico hasta ahora, guarda el % de CPU y el pico
        """
        prev_count = 0
        # Inicializaciones de psutil para que las lecturas tengan sentido
        if _PSUTIL_OK:
            _ = psutil.cpu_percent(interval=None)
            _proc = psutil.Process()
            _ = _proc.cpu_percent(interval=None)

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
                    cpu_proc = psutil.Process().cpu_percent(interval=None)  # % del proceso (sobre 100*n núcleos)
                except Exception:
                    pass

            if msgs_per_sec > self._peak_msgs_per_sec:
                self._peak_msgs_per_sec = msgs_per_sec
                self._peak_ts = now
                if cpu_total is not None:
                    self._peak_cpu_total = cpu_total
                if cpu_proc is not None:
                    self._peak_cpu_process = cpu_proc

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        conn: _Conn | None = None
        cid: str | None = None
        try:
            data = await reader.readline()
            if not data:
                writer.close()
                return

            transport = writer.transport
            sock: socket.socket = transport.get_extra_info("socket")
            if sock is not None:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                #sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, BUFFER_SIZE)
                #sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, BUFFER_SIZE)
            try:
                transport.set_write_buffer_limits(high=256 * 1024, low=64 * 1024)
            except Exception:
                pass

            _ = decode_message(data)
            cid = generate_client_id()

            conn = _Conn(cid, writer)
            self.clients[cid] = conn
            self._assign_to_group(cid)

            # Intento de disparar START (atómico y solo una vez)
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
                with contextlib.suppress(KeyError):
                    del self.clients[cid]
            if conn:
                with contextlib.suppress(Exception):
                    await conn.close()
            with contextlib.suppress(Exception):
                writer.close()

    def _assign_to_group(self, cid: str):
        # Tras enviar START no seguimos formando grupos (evita ruido si llegara alguien tarde)
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
        """
        Dispara el START exactamente una vez, cuando len(clients) == total_clients.
        Protegido con lock + fusible (double-checked locking).
        """
        if self._start_sent or len(self.clients) < self.total_clients:
            return
        async with self._start_lock:
            if self._start_sent or len(self.clients) < self.total_clients:
                return
            self._start_sent = True
            await self._send_start()

    async def _send_start(self):
        """Envía el mensaje START a todos los clientes una vez estén todos conectados (un solo burst)."""
        for gidx in range(len(self.groups)):
            group = self.groups[gidx]
            for cid in group:
                conn = self.clients.get(cid)
                if not conn:
                    continue
                start_msg = make_message(
                    MessageType.START, "server",
                    {"id": cid, "neighbours": self.neighbours.get(cid, [])}
                )
                conn.send_msg(start_msg)
        logger.info(f"[SERVIDOR] START enviado a {sum(len(g) for g in self.groups)} clientes en {self.port}")

    def _process_message_fast(self, msg: dict):
        cid = msg["client_id"]
        mtype = msg["type"]

        # Contabilizamos tráfico en hot-path
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
                conn = self.clients.get(n)
                if conn:
                    conn.send_bytes(b)

        elif mtype == MessageType.ACK.value:
            dest = msg["data"].get("ack_to")
            conn = self.clients.get(dest)
            if conn:
                ack_msg = {
                    "type": MessageType.ACK.value,
                    "client_id": cid,
                    "data": {"from": cid},
                }
                conn.send_bytes(encode_message(ack_msg))

        elif mtype == MessageType.END.value:
            if self._finalized:
                return
            data = msg.get("data", {})
            # Evita contar métricas duplicadas del mismo cliente
            if cid in self.client_metrics:
                return

            avg_resp = float(data.get("avg_response_time", 0.0))
            self.client_metrics[cid] = avg_resp

            # Acumular métricas de ACK enviadas por el cliente
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

        # Resumen ACKs + pérdida %
        if self.acks_expected_sum > 0:
            loss_pct_total = 100.0 * (max(0, self.acks_expected_sum - self.acks_received_sum) / self.acks_expected_sum)
        else:
            loss_pct_total = 0.0

        logger.info("===== RESUMEN ACKs =====")
        logger.info(
            "ACKs totales: %d/%d (pérdida %.2f%%)",
            self.acks_received_sum, self.acks_expected_sum, loss_pct_total
        )

        # Pico de tráfico y CPU en ese instante
        if self._peak_msgs_per_sec > 0:
            if _PSUTIL_OK and (self._peak_cpu_total is not None or self._peak_cpu_process is not None):
                logger.info(
                    "Pico de tráfico: ~%.0f msgs/s | CPU total=%.1f%% | CPU proceso=%.1f%%",
                    self._peak_msgs_per_sec,
                    (self._peak_cpu_total if self._peak_cpu_total is not None else -1.0),
                    (self._peak_cpu_process if self._peak_cpu_process is not None else -1.0),
                )
            else:
                logger.info("Pico de tráfico: ~%.0f msgs/s | Métricas de CPU no disponibles (instala psutil).",
                            self._peak_msgs_per_sec)
        else:
            logger.info("No se detectó tráfico para calcular picos.")

        # END broadcast sin bloquear el loop
        end_bytes = encode_message(make_message(MessageType.END, "server", {"msg": "Fin"}))
        for conn in list(self.clients.values()):
            conn.send_bytes(end_bytes)

        # Paramos el monitor
        if self._monitor_task:
            self._monitor_task.cancel()
            with contextlib.suppress(Exception):
                await self._monitor_task

        await asyncio.sleep(0.5)
        logger.info("[SERVIDOR] Simulación completada en puerto %s", self.port)
