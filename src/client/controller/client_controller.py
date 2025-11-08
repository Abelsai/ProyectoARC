"""
Cliente del sistema de estaciones eléctricas.
Estados posibles: NORMAL, ALERTA, INCIDENCIA.
- Si un nodo entra en INCIDENCIA, avisa al servidor.
- Si recibe la incidencia de un vecino, pasa a ALERTA.
- Si el nodo en incidencia se recupera, sus vecinos en ALERTA vuelven a NORMAL.
"""

import asyncio, json, random, time
from common.protocol import make_message, MessageType
from common.config import SERVER_HOST, SERVER_PORT, NUM_ITERATIONS


class ClientController:
    def __init__(self, cid: str):
        self.id = cid
        self.reader = None
        self.writer = None
        self.state = "NORMAL"
        self.times = []

    async def connect(self):
        """Conecta al servidor y envía el mensaje JOIN."""
        self.reader, self.writer = await asyncio.open_connection(SERVER_HOST, SERVER_PORT)
        join_msg = make_message(MessageType.JOIN, self.id)
        self.writer.write((json.dumps(join_msg) + "\n").encode())
        await self.writer.drain()
        print(f"[{self.id}] Conectado al servidor. Estado inicial: {self.state}")
        await self.listen_server()

    async def listen_server(self):
        """Procesa los mensajes recibidos del servidor."""
        while data := await self.reader.readline():
            msg = json.loads(data.decode())
            t = msg["type"]

            if t == MessageType.START.value:
                print(f"[{self.id}] Inicio de simulación.")
                asyncio.create_task(self.run_simulation())

            elif t == MessageType.INFO.value:
                sender = msg["client_id"]
                neighbor_state = msg["data"].get("state")

                # Si un vecino entra en incidencia → pasa a alerta
                if neighbor_state == "INCIDENCIA" and self.state == "NORMAL":
                    self.state = "ALERTA"
                    print(f"[{self.id}] pasa a ALERTA por {sender}")
                    await self.notify_server()

                # Si el vecino se recupera y estaba en alerta → vuelve a normal
                elif neighbor_state == "NORMAL" and self.state == "ALERTA":
                    self.state = "NORMAL"
                    print(f"[{self.id}] vuelve a NORMAL (vecino {sender} recuperado)")
                    await self.notify_server()

            elif t == MessageType.END.value:
                avg_total = msg["data"].get("avg_total", 0)
                print(f"[{self.id}] Simulación finalizada. Media global: {avg_total:.3f}s")
                break

    async def run_simulation(self):
        """Ejecuta la simulación. 
        Probabilidades:
          - NORMAL → INCIDENCIA: 10%
          - INCIDENCIA → NORMAL: 20%
        """
        for i in range(NUM_ITERATIONS):
            start = time.perf_counter()

            if self.state == "NORMAL" and random.random() < 0.1:
                self.state = "INCIDENCIA"
                print(f"[{self.id}] entra en INCIDENCIA")
                await self.notify_server()

            elif self.state == "INCIDENCIA" and random.random() < 0.2:
                self.state = "NORMAL"
                print(f"[{self.id}] se recupera de la INCIDENCIA")
                await self.notify_server()

            await asyncio.sleep(random.uniform(0.5, 1.2))
            elapsed = time.perf_counter() - start
            self.times.append(elapsed)

        avg = sum(self.times) / len(self.times)
        end_msg = make_message(MessageType.END, self.id, {"avg_time": avg})
        self.writer.write((json.dumps(end_msg) + "\n").encode())
        await self.writer.drain()
        print(f"[{self.id}] Finaliza simulación ({avg:.3f}s).")

    async def notify_server(self):
        """Envía el estado actual al servidor."""
        msg = make_message(MessageType.INFO, self.id, {"state": self.state})
        self.writer.write((json.dumps(msg) + "\n").encode())
        await self.writer.drain()
