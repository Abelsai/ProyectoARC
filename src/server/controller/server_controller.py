import asyncio
import socket
import contextlib
import time

from common.protocol import make_message, MessageType, encode_message, decode_message
from common.config import SERVER_HOST, SERVER_PORT
from common.logger import logger
from common.utils import generate_client_id

# psutil es opcional (solo para medir CPU total del sistema)
try:
    import psutil
    _PSUTIL_OK = True
except Exception:
    _PSUTIL_OK = False


class ServerController:
    """
    Sistema Realidad Aumentada Colaborativa mediante Sockets TCP

    Servidor TCP con asyncio orientado a muchas conexiones simultáneas.
    Idea general:
      1) Se aceptan conexiones hasta llegar a N clientes.
      2) Se asigna a cada cliente un id y sus vecinos dentro de un grupo.
      3) Cuando están todos conectados, se envía un START a todos.
      4) Durante la simulación, el servidor:
         - Reenvía INFO a los vecinos del emisor
         - Reenvía ACK al destinatario del ACK
         - Recoge END con métricas de cada cliente
      5) Cuando llegan todos los END, calcula métricas globales.

    Detalle importante: no hay una tarea de escritura por cliente (evitamos 30k tareas).
    En su lugar, se escribe directamente en el StreamWriter y solo se drena cuando hace falta.
    """
    MONITOR_INTERVAL = 1.0  # ventana de muestreo para msgs/s y CPU

    # Si el buffer de salida crece demasiado, programamos un drain para no acumular memoria.
    _DRAIN_HIGH_WATER = 512 * 1024
    _DRAIN_TIMEOUT = 5.0

    def __init__(self, total_clients: int, group_size: int, host: str = SERVER_HOST, port: int = SERVER_PORT):
        self.total_clients = total_clients
        self.group_size = group_size
        self.host = host
        self.port = port

        # Tabla de conexiones activas: id -> StreamWriter
        self.clients: dict[str, asyncio.StreamWriter] = {}

        # Vecinos por cliente (dentro de su grupo)
        self.neighbours: dict[str, list[str]] = {}

        # Grupos: lista de listas con los ids de los clientes de cada grupo
        self.groups: list[list[str]] = []

        # Métrica por cliente: latencia media (segundos) enviada por el cliente en END
        self.client_metrics: dict[str, float] = {}

        # Fiabilidad global (sumas reportadas por los clientes)
        self.acks_expected_sum = 0
        self.acks_received_sum = 0
        self.timeouts_sum = 0  # timeouts (esperas de ACK) sumados entre todos los clientes

        # Contador de mensajes en hot-path (INFO, ACK, END)
        self._msg_counter = 0

        # Monitor de pico de tráfico
        self._peak_msgs_per_sec = 0.0
        self._peak_cpu_total: float | None = None
        self._monitor_task: asyncio.Task | None = None

        # Medición del run (desde que se envía START hasta que termina)
        self._t_start_sent: float | None = None
        self._t_end: float | None = None
        self._msg_at_start: int = 0

        # Control para enviar START una sola vez y finalizar una sola vez
        self._start_sent = False
        self._start_lock = asyncio.Lock()
        self._finalized = False

        # Tareas de drain por cliente (solo existen si un writer supera el high water)
        self._drain_tasks: dict[str, asyncio.Task] = {}

        logger.info(f"[SERVIDOR] Iniciado (N={total_clients}, V={group_size}, host={self.host}, port={self.port})")

    async def start(self):
        """Arranca el servidor TCP y se queda escuchando."""
        loop = asyncio.get_running_loop()
        logger.info(f"[SERVIDOR] Bucle de eventos: {type(loop)}")

        self._monitor_task = asyncio.create_task(self._monitor_load(), name="monitor_load")

        server = await asyncio.start_server(
            self.handle_client,
            self.host,
            self.port,
            backlog=socket.SOMAXCONN,  # dejamos que el SO ajuste
        )
        logger.info(f"[SERVIDOR] Escuchando en {self.host}:{self.port}")
        async with server:
            await server.serve_forever()

    async def _monitor_load(self):
        """
        Monitoriza el número de mensajes por segundo (msgs/s).
        Si psutil está disponible, también guarda la CPU total del sistema en el instante de mayor tráfico.
        """
        prev_count = 0
        if _PSUTIL_OK:
            # llamada “de calentamiento”
            _ = psutil.cpu_percent(interval=None)

        while True:
            await asyncio.sleep(self.MONITOR_INTERVAL)

            current = self._msg_counter
            delta = current - prev_count
            prev_count = current

            msgs_per_sec = delta / self.MONITOR_INTERVAL

            cpu_total = None
            if _PSUTIL_OK:
                try:
                    cpu_total = psutil.cpu_percent(interval=None)
                except Exception:
                    cpu_total = None

            if msgs_per_sec > self._peak_msgs_per_sec:
                self._peak_msgs_per_sec = msgs_per_sec
                if cpu_total is not None:
                    self._peak_cpu_total = cpu_total

    def _configure_socket(self, writer: asyncio.StreamWriter):
        """Ajustes de socket útiles para latencia y estabilidad."""
        transport = writer.transport
        sock: socket.socket = transport.get_extra_info("socket")
        if sock is not None:
            try:
                # TCP_NODELAY reduce latencia (evita que Nagle agrupe envíos pequeños)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            except Exception:
                pass

        # Controlamos los límites del buffer de escritura del transport
        try:
            transport.set_write_buffer_limits(high=256 * 1024, low=64 * 1024)
        except Exception:
            pass

    def _send_bytes(self, cid: str, payload: bytes):
        """
        Envío rápido: se escribe directo en el writer.
        Si el buffer de salida crece demasiado, se programa un drain corto.
        """
        w = self.clients.get(cid)
        if not w:
            return

        try:
            w.write(payload)
        except Exception:
            return

        # Backpressure: si el buffer está alto, drenamos sin bloquear el flujo principal
        try:
            tr = w.transport
            if tr.get_write_buffer_size() >= self._DRAIN_HIGH_WATER:
                t = self._drain_tasks.get(cid)
                if t is None or t.done():
                    self._drain_tasks[cid] = asyncio.create_task(self._drain_writer(cid, w))
        except Exception:
            pass

    async def _drain_writer(self, cid: str, w: asyncio.StreamWriter):
        """Draina el writer con timeout. Si falla, normalmente es por saturación o desconexión."""
        try:
            await asyncio.wait_for(w.drain(), timeout=self._DRAIN_TIMEOUT)
        except Exception:
            pass
        finally:
            # Nos aseguramos de borrar la task si sigue siendo la vigente
            t = self._drain_tasks.get(cid)
            if t and t is asyncio.current_task():
                self._drain_tasks.pop(cid, None)

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """
        Atiende un cliente:
        - lee JOIN
        - asigna id y grupo
        - espera mensajes INFO/ACK/END
        """
        cid: str | None = None
        try:
            data = await reader.readline()
            if not data:
                writer.close()
                return

            self._configure_socket(writer)

            # JOIN: se valida el formato, pero el contenido no lo usamos
            _ = decode_message(data)

            cid = generate_client_id()
            self.clients[cid] = writer
            self._assign_to_group(cid)

            # Intento de START si ya están todos conectados
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

                t = self._drain_tasks.pop(cid, None)
                if t:
                    t.cancel()

            with contextlib.suppress(Exception):
                writer.close()

    def _assign_to_group(self, cid: str):
        """
        Mete al cliente en el último grupo disponible o crea uno nuevo.
        A la vez, recalcula la lista de vecinos dentro del grupo.
        """
        if self._start_sent:
            # Si ya hemos enviado START, no queremos “reorganizar” vecinos.
            return

        if not self.groups or len(self.groups[-1]) >= self.group_size:
            self.groups.append([cid])
        else:
            self.groups[-1].append(cid)

        group = self.groups[-1]
        for c in group:
            # Vecinos = todos los del grupo menos él mismo
            self.neighbours[c] = [n for n in group if n != c]

    async def _maybe_send_start(self):
        """Envía START una sola vez cuando len(clients) == total_clients."""
        if self._start_sent or len(self.clients) < self.total_clients:
            return

        async with self._start_lock:
            if self._start_sent or len(self.clients) < self.total_clients:
                return

            self._start_sent = True
            await self._send_start()

    async def _send_start(self):
        """Envía START a todos los clientes con su id y su lista de vecinos."""
        for group in self.groups:
            for cid in group:
                start_msg = make_message(
                    MessageType.START,
                    "server",
                    {"id": cid, "neighbours": self.neighbours.get(cid, [])},
                )
                self._send_bytes(cid, encode_message(start_msg))

        # A partir de aquí empieza el “run” de medida de rendimiento
        self._t_start_sent = time.perf_counter()
        self._msg_at_start = self._msg_counter

        logger.info(f"[SERVIDOR] START enviado a {sum(len(g) for g in self.groups)} clientes en {self.port}")

    def _process_message_fast(self, msg: dict):
        """
        Hot-path: procesa INFO/ACK/END sin bloquear.
        INFO y ACK se reenvían; END se acumula para métricas.
        """
        cid = msg["client_id"]
        mtype = msg["type"]

        if mtype in (MessageType.INFO.value, MessageType.ACK.value, MessageType.END.value):
            self._msg_counter += 1

        if mtype == MessageType.INFO.value:
            # Reenvío de coordenadas a vecinos
            payload = {
                "type": MessageType.INFO.value,
                "client_id": cid,
                "data": msg["data"],
            }
            b = encode_message(payload)
            for n in self.neighbours.get(cid, []):
                self._send_bytes(n, b)

        elif mtype == MessageType.ACK.value:
            # Reenvío del ACK al destinatario indicado por el cliente
            dest = msg["data"].get("ack_to")
            if dest:
                ack_msg = {
                    "type": MessageType.ACK.value,
                    "client_id": cid,
                    "data": {"from": cid},
                }
                self._send_bytes(dest, encode_message(ack_msg))

        elif mtype == MessageType.END.value:
            # END = el cliente terminó y reporta sus métricas
            if self._finalized:
                return

            data = msg.get("data", {})
            if cid in self.client_metrics:
                # Evita duplicados si llega más de un END del mismo cliente
                return

            avg_resp = float(data.get("avg_response_time", 0.0))
            self.client_metrics[cid] = avg_resp

            self.acks_expected_sum += int(data.get("acks_expected", 0))
            self.acks_received_sum += int(data.get("acks_received", 0))
            self.timeouts_sum += int(data.get("timeouts", 0))

            if len(self.client_metrics) % 1000 == 0:
                logger.info(f"[END] Recibidas {len(self.client_metrics)}/{self.total_clients} métricas en {self.port}")

            if len(self.client_metrics) == self.total_clients and not self._finalized:
                asyncio.create_task(self._finalize_simulation())

    async def _finalize_simulation(self):
        """Cierra el run: calcula latencia media, throughput y fiabilidad, y envía END global."""
        if self._finalized:
            return
        self._finalized = True

        # Duración del run (START -> fin)
        self._t_end = time.perf_counter()
        t0 = self._t_start_sent if self._t_start_sent is not None else self._t_end
        duration_s = max(1e-6, self._t_end - t0)

        # Mensajes contados solo durante el run
        msg_count = max(0, self._msg_counter - self._msg_at_start)
        avg_msgs_s = msg_count / duration_s
        end_per_s = self.total_clients / duration_s

        total = len(self.client_metrics)
        global_avg = (sum(self.client_metrics.values()) / total) if total else 0.0
        lat_mean_ms = global_avg * 1000.0

        if self.acks_expected_sum > 0:
            ack_loss_pct = 100.0 * (max(0, self.acks_expected_sum - self.acks_received_sum) / self.acks_expected_sum)
        else:
            ack_loss_pct = 0.0

        # Línea final para copiar directamente (una por ejecución)
        logger.info(
            "RESULT N=%d V=%d duration_s=%.3f lat_mean_ms=%.3f end_per_s=%.2f "
            "msg_count=%d avg_msgs_s=%.0f peak_msgs_s=%.0f peak_cpu_total=%.1f "
            "ack_loss_pct=%.4f acks=%d/%d timeouts_sum=%d",
            self.total_clients,
            self.group_size,
            duration_s,
            lat_mean_ms,
            end_per_s,
            msg_count,
            avg_msgs_s,
            self._peak_msgs_per_sec,
            (self._peak_cpu_total if self._peak_cpu_total is not None else -1.0),
            ack_loss_pct,
            self.acks_received_sum,
            self.acks_expected_sum,
            self.timeouts_sum,
        )

        # Aviso de pico (sirve para contextualizar el throughput)
        if self._peak_msgs_per_sec > 0:
            if _PSUTIL_OK and (self._peak_cpu_total is not None):
                logger.info("Pico de tráfico: ~%.0f msgs/s | CPU total=%.1f%%", self._peak_msgs_per_sec, self._peak_cpu_total)
            else:
                logger.info("Pico de tráfico: ~%.0f msgs/s", self._peak_msgs_per_sec)

        # Se notifica fin a todos sin bloquear el hot-path
        end_bytes = encode_message(make_message(MessageType.END, "server", {"msg": "Fin"}))
        for cid in list(self.clients.keys()):
            self._send_bytes(cid, end_bytes)

        # Paramos el monitor
        if self._monitor_task:
            self._monitor_task.cancel()
            with contextlib.suppress(Exception):
                await self._monitor_task

        await asyncio.sleep(0.5)
        logger.info("[SERVIDOR] Simulación completada en puerto %s", self.port)
