"""
Servidor del sistema CAR.
Gestiona grupos, reenvía INFO/ACK y recoge métricas.
"""

import asyncio

from common.protocol import (
    make_message,
    MessageType,
    encode_message,
    decode_message,
)
from common.config import SERVER_HOST, SERVER_PORT
from common.logger import logger
from common.utils import generate_client_id


class ServerController:
    def __init__(self, total_clients: int, group_size: int):
        # Parámetros de simulación
        self.total_clients = total_clients
        self.group_size = group_size

        # Estructuras de datos
        self.clients = {}          # id → writer
        self.neighbours = {}       # id → lista de vecinos
        self.groups = []           # lista de grupos (listas de IDs)
        self.client_group = {}     # id → grupo al que pertenece

        self.simulation_started = False
        self.client_metrics = {}   # métricas finales por cliente

        logger.info(f"[SERVIDOR] Iniciado (N={total_clients}, V={group_size})")

    # -------------------------------------------------------------------------
    async def start(self):
        server = await asyncio.start_server(
            self.handle_client, SERVER_HOST, SERVER_PORT, backlog=self.total_clients + 100
        )
        logger.info(f"[SERVIDOR] Escuchando en {SERVER_HOST}:{SERVER_PORT}")
        async with server:
            await server.serve_forever()

    # -------------------------------------------------------------------------
    async def handle_client(self, reader, writer):
        """Primera lectura del cliente: JOIN. El servidor genera el ID real."""
        data = await reader.readline()
        if not data:
            writer.close()
            await writer.wait_closed()
            return

        _ = decode_message(data)       # ignoramos el ID temp
        cid = generate_client_id()     # ID verdadero generado por servidor

        self.clients[cid] = writer
        self._assign_to_group(cid)
        # Este log es por cliente, aceptable
        logger.info(f"[+] Cliente {cid} conectado {len(self.clients)}/{self.total_clients}")
        
        # Cuando ya están todos los clientes, se inicia
        if not self.simulation_started and len(self.clients) == self.total_clients:
            self.simulation_started = True
            await self.start_simulation()

        try:
            while data := await reader.readline():
                msg = decode_message(data)
                await self.process_message(msg)
        except Exception as e:
            logger.info(f"[!] Error con cliente {cid}: {e}")
        finally:
            logger.info(f"[-] Cliente {cid} desconectado")
            self.clients.pop(cid, None)
            writer.close()
            await writer.wait_closed()

    # -------------------------------------------------------------------------
    def _assign_to_group(self, cid: str):
        """Añade al cliente a un grupo de tamaño V."""
        if not self.groups or len(self.groups[-1]) >= self.group_size:
            self.groups.append([cid])
        else:
            self.groups[-1].append(cid)

        group_idx = len(self.groups) - 1
        self.client_group[cid] = group_idx

        # Actualizar vecinos del grupo
        group = self.groups[-1]
        for c in group:
            self.neighbours[c] = [n for n in group if n != c]

    # -------------------------------------------------------------------------
    async def start_simulation(self):
        logger.info("[SERVIDOR] Enviando START a todos los clientes")

        for cid, w in self.clients.items():
            msg = make_message(
                MessageType.START,
                "server",
                {"id": cid, "neighbours": self.neighbours[cid]},
            )
            w.write(encode_message(msg))
            await w.drain()

        logger.info("[SERVIDOR] Simulación iniciada")

    # -------------------------------------------------------------------------
    async def process_message(self, msg: dict):
        """Procesa INFO, ACK y END."""
        cid = msg["client_id"]
        mtype = msg["type"]

        # ------------ INFO -----------------
        if mtype == MessageType.INFO.value:
            # No log por cada INFO para no matar el rendimiento

            # Reenviar a vecinos
            for n in self.neighbours.get(cid, []):
                if n in self.clients:
                    w = self.clients[n]
                    forward = {
                        "type": MessageType.INFO.value,
                        "client_id": cid,
                        "data": msg["data"],
                    }
                    w.write(encode_message(forward))
                    await w.drain()

        # ------------ ACK ------------------
        elif mtype == MessageType.ACK.value:
            dest = msg["data"].get("ack_to")

            if dest in self.clients:
                w = self.clients[dest]
                ack_msg = {
                    "type": MessageType.ACK.value,
                    "client_id": cid,
                    "data": {"from": cid},
                }
                w.write(encode_message(ack_msg))
                await w.drain()

        # ------------ END -------------------
        elif mtype == MessageType.END.value:
            avg_resp = msg["data"].get("avg_response_time", 0.0)

            self.client_metrics[cid] = avg_resp
            # Si quieres rendimiento máximo, este log también se podría quitar:
            logger.info(
                f"[END] Métrica recibida de {cid} ({avg_resp*1000:.2f} ms)"
            )

            if len(self.client_metrics) == self.total_clients:
                await self._finalize_simulation()

    # -------------------------------------------------------------------------
    async def _finalize_simulation(self):
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

        # Enviar END final a todos
        end_msg = make_message(MessageType.END, "server", {"msg": "Fin"})
        for cid, w in self.clients.items():
            w.write(encode_message(end_msg))
            await w.drain()

        await asyncio.sleep(1)
        logger.info("[SERVIDOR] Simulación completada")
