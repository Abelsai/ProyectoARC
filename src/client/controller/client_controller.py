"""
Cliente del sistema de estaciones eléctricas.
"""

import asyncio, json, random, time
from common.protocol import make_message, MessageType
from common.config import SERVER_HOST, SERVER_PORT, NEIGHBOR_MAP, NUM_ITERATIONS

class ClientController:
    def __init__(self, cid):
        self.id = cid
        self.reader = None
        self.writer = None
        self.pending_acks = set()
        self.times = []

    async def connect(self):
        self.reader, self.writer = await asyncio.open_connection(SERVER_HOST, SERVER_PORT)
        hello = make_message(MessageType.STATUS_UPDATE, self.id, {"msg": "hello"})
        self.writer.write((json.dumps(hello) + "\n").encode())
        await self.writer.drain()
        print(f"[{self.id}] Conectado al servidor.")
        await self.listen_server()

    async def listen_server(self):
        while data := await self.reader.readline():
            msg = json.loads(data.decode())
            t = msg["type"]

            if t == MessageType.START_SIMULATION.value:
                print(f"[{self.id}] Inicio de simulación.")
                asyncio.create_task(self.run_simulation())

            elif t == MessageType.NEIGHBOR_UPDATE.value:
                sender = msg["client_id"]
                print(f"[{self.id}] Mensaje de {sender}. Enviando ACK.")
                ack = make_message(MessageType.ACK_NEIGHBOR, self.id, {"ack_to": sender})
                self.writer.write((json.dumps(ack) + "\n").encode())
                await self.writer.drain()

            elif t == MessageType.ACK_FORWARD.value:
                frm = msg["data"]["from"]
                if frm in self.pending_acks:
                    self.pending_acks.discard(frm)
                    print(f"[{self.id}] ACK de {frm}. Faltan {len(self.pending_acks)}.")

            elif t == MessageType.END_SIMULATION.value:
                print(f"[{self.id}] Simulación global finalizada.")
                break

    async def run_simulation(self):
        from common.config import NEIGHBOR_MAP
        for i in range(NUM_ITERATIONS):
            neighbors = NEIGHBOR_MAP.get(self.id, [])
            self.pending_acks = set(neighbors)
            start = time.perf_counter()

            msg = make_message(
                MessageType.STATUS_UPDATE,
                self.id,
                {"coords": [random.random(), random.random(), random.random()]}
            )
            self.writer.write((json.dumps(msg) + "\n").encode())
            await self.writer.drain()
            print(f"[{self.id}] Iteración {i+1} enviada ({len(neighbors)} vecinos).")

            # Esperar hasta que todos los ACKs lleguen
            while self.pending_acks:
                await asyncio.sleep(0.05)

            elapsed = time.perf_counter() - start
            self.times.append(elapsed)
            print(f"[{self.id}] Iteración {i+1} completa ({elapsed:.3f}s).")
            await asyncio.sleep(random.uniform(0.3, 0.8))

        avg = sum(self.times) / len(self.times)
        end = make_message(MessageType.SIMULATION_END, self.id, {"avg_time": avg})
        self.writer.write((json.dumps(end) + "\n").encode())
        await self.writer.drain()
        print(f"[{self.id}] Simulación finalizada ({avg:.3f}s).")

