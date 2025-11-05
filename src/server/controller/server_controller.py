"""
Servidor del sistema de estaciones eléctricas.
"""

import asyncio, json
from common.protocol import make_message, MessageType, validate_message
from common.config import SERVER_HOST, SERVER_PORT, NEIGHBOR_MAP


class ServerController:
    def __init__(self, min_clients=3):
        self.clients = {}
        self.response_times = {}
        self.min_clients = min_clients

    async def start(self):
        server = await asyncio.start_server(self.handle_client, SERVER_HOST, SERVER_PORT) # "Metodo" start_server crea corrutina, necesita await.
        print(f"[SERVIDOR] Escuchando en {SERVER_HOST}:{SERVER_PORT}")
        async with server:
            await server.serve_forever()

    async def handle_client(self, reader, writer):
        msg = json.loads((await reader.readline()).decode())
        if not validate_message(msg):
            return

        cid = msg["client_id"]
        self.clients[cid] = writer
        print(f"[+] Cliente conectado: {cid}")

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

    async def start_simulation(self):
        msg = make_message(MessageType.START_SIMULATION, "server")
        for w in self.clients.values():
            w.write((json.dumps(msg) + "\n").encode())
        print(f"[SERVIDOR] Simulación iniciada con {len(self.clients)} clientes")

    async def process_message(self, msg):
        cid, t = msg["client_id"], msg["type"]

        if t == MessageType.STATUS_UPDATE.value:
            data = msg["data"]
            for n in NEIGHBOR_MAP.get(cid, []):
                if n in self.clients:
                    w = self.clients[n]
                    w.write((json.dumps({
                        "type": MessageType.NEIGHBOR_UPDATE.value,
                        "client_id": cid,
                        "data": data
                    }) + "\n").encode())
                    await w.drain()
            print(f"[{cid}] → vecinos")

        elif t == MessageType.ACK_NEIGHBOR.value:
            dest = msg["data"].get("ack_to")
            if dest in self.clients:
                w = self.clients[dest]
                w.write((json.dumps({
                    "type": MessageType.ACK_FORWARD.value,
                    "client_id": "server",
                    "data": {"from": cid}
                }) + "\n").encode())
                await w.drain()

        elif t == MessageType.SIMULATION_END.value:
            avg = msg["data"].get("avg_time", 0)
            self.response_times[cid] = avg
            print(f"[{cid}] fin {avg:.3f}s")

            if len(self.response_times) == len(self.clients):
                m = sum(self.response_times.values()) / len(self.clients)
                print(f"\n📊 Media global: {m:.3f}s\n")

                end_msg = make_message(MessageType.END_SIMULATION, "server", {"avg_total": m})
                for w in self.clients.values():
                    w.write((json.dumps(end_msg) + "\n").encode())
                    await w.drain()

                print("[SERVIDOR] Simulación completada. Señal de fin enviada.")
