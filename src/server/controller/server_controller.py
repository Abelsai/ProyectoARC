"""
Servidor del sistema de estaciones eléctricas.
"""

import asyncio, json
from common.protocol import make_message, MessageType, validate_message
from common.config import SERVER_HOST, SERVER_PORT, MAX_PER_BARRIO


class ServerController:
    def __init__(self, min_clients=3):
        self.clients = {}
        self.neighbours = {}
        self.barrios = []
        self.response_times = {}
        self.min_clients = min_clients

    async def start(self):
        server = await asyncio.start_server(self.handle_client, SERVER_HOST, SERVER_PORT) # "Metodo" start_server crea corrutina, necesita await.
        print(f"[SERVIDOR] Escuchando en {SERVER_HOST}:{SERVER_PORT}")
        async with server: # Maneja el contexto del server, abre y cierra el recurso
            await server.serve_forever() # Mantiene la corrutina del server activa en el event loop

    async def handle_client(self, reader, writer):
        msg = json.loads((await reader.readline()).decode()) # await porque puede ser bloqueante (tiempo de espera hasta que llegan los datos)
        if not validate_message(msg): 
            return
        # Arriba llega el primer mensaje del cliente, que es un join.
        cid = msg["client_id"]
        self.clients[cid] = writer
        print(f"[+] Cliente conectado: {cid}")

        self._assign_to_barrio(cid)

        if len(self.clients) >= self.min_clients:
            await self.start_simulation()

        try:
            while data := await reader.readline():
                msg = json.loads(data.decode())
                if not validate_message(msg):
                    continue
                await self.process_message(msg)
        except Exception as e:
            print(f"[ERROR] {cid}: {e}")
        finally:
            print(f"[-] Cliente desconectado: {cid}")
            self.clients.pop(cid, None)
            writer.close()
            await writer.wait_closed()

    def _assign_to_barrio(self, cid: str) -> None:
        """Añade el cliente a la última fila (barrio) o crea una nueva si está llena."""
        if not self.barrios or len(self.barrios[-1]) >= MAX_PER_BARRIO:
            self.barrios.append([cid])
        else:
            self.barrios[-1].append(cid)
        # actualizar el mapa de vecinos SOLO para este barrio
        self._update_neighbors_for_barrio(self.barrios[-1])

    def _update_neighbors_for_barrio(self, barrio: list[str]) -> None:
        """Para cada cliente del barrio, sus vecinos son los demás de la misma fila."""
        for c in barrio:
            self.neighbours[c] = [n for n in barrio if n != c]

    async def start_simulation(self):
        msg = make_message(MessageType.START, "server")
        for w in self.clients.values():
            w.write((json.dumps(msg) + "\n").encode())
        print(f"[SERVIDOR] Simulación iniciada con {len(self.clients)} clientes")

    async def process_message(self, msg):
        cid, t = msg["client_id"], msg["type"]

        if t == MessageType.INFO.value:
            data = msg["data"]
            for n in self.neighbours.get(cid, []):
                if n in self.clients:
                    w = self.clients[n]
                    w.write((json.dumps({
                        "type": MessageType.INFO.value,
                        "client_id": cid,
                        "data": data
                    }) + "\n").encode())
                    await w.drain()
            print(f"[{cid}] → vecinos")

        elif t == MessageType.ACK.value:
            dest = msg["data"].get("ack_to")
            if dest in self.clients:
                w = self.clients[dest]
                w.write((json.dumps({
                    "type": MessageType.ACK.value,
                    "client_id": "server",
                    "data": {"from": cid}
                }) + "\n").encode())
                await w.drain()

        elif t == MessageType.END.value:
            avg = msg["data"].get("avg_time", 0)
            self.response_times[cid] = avg
            print(f"[{cid}] fin {avg:.3f}s")

            if len(self.response_times) == len(self.clients):
                m = sum(self.response_times.values()) / len(self.clients)
                print(f"\n📊 Media global: {m:.3f}s\n")

                end_msg = make_message(MessageType.END, "server", {"avg_total": m})
                for w in self.clients.values():
                    w.write((json.dumps(end_msg) + "\n").encode())
                    await w.drain()

                print("[SERVIDOR] Simulación completada. Señal de fin enviada.")
