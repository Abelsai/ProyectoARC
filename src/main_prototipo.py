"""
main_prototipo.py

Script principal para probar el prototipo del sistema de estaciones eléctricas.
Levanta el servidor y varios clientes (en tareas asíncronas) para simular la red.
"""

import asyncio
from server.controller.server_controller import ServerController
from client.controller.client_controller import ClientController


async def main():
    # 1 Iniciar servidor
    server = ServerController(min_clients=3)
    server_task = asyncio.create_task(server.start())
    await asyncio.sleep(1)  # pequeña pausa para asegurar que el servidor arranca

    # 2 Iniciar varios clientes
    clients = [ClientController(f"station-{i}") for i in range(1, 5)]
    client_tasks = [asyncio.create_task(c.connect()) for c in clients]

    # 3 Esperar a que todos terminen
    await asyncio.gather(*client_tasks, return_exceptions=True)

    # (El servidor sigue corriendo indefinidamente)
    # Si quieres detenerlo al final, puedes cancelar la tarea:
    server_task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSimulación detenida por el usuario.")

