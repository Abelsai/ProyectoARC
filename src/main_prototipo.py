"""
main_prototipo.py

Versión CAR sin GUI:
- Pide N, V y S por consola.
- El servidor y los clientes corren en asyncio en el mismo hilo.
- Los IDs de clientes los asigna el servidor, no el cliente.
"""

import asyncio

from server.controller.server_controller import ServerController
from client.controller.client_controller import ClientController
from common.config import NUM_CLIENTES, MAX_PER_BARRIO, NUM_ITERATIONS


async def run_simulation(server: ServerController, num_clients: int, num_iterations: int):
    """
    Ejecuta la simulación completa: inicia el servidor,
    crea los clientes y espera a que finalicen.
    """

    print(
        f"Iniciando simulación CAR con {num_clients} clientes, "
        f"{num_iterations} iteraciones por cliente..."
    )

    # Iniciar servidor en una tarea independiente
    server_task = asyncio.create_task(server.start())
    await asyncio.sleep(1)  # pequeña pausa para dar tiempo a que arranque

    # Crear clientes (sin IDs → los asigna el servidor en START)
    clients = [
        ClientController(iterations=num_iterations)
        for _ in range(num_clients)
    ]

    # Conectar todos los clientes
    client_tasks = [asyncio.create_task(c.connect()) for c in clients]

    # Esperar a que todos los clientes acaben
    await asyncio.gather(*client_tasks, return_exceptions=True)

    # Cancelar el servidor cuando la simulación termina
    server_task.cancel()
    print("Simulación finalizada.")


def _ask_int(prompt: str, default: int) -> int:
    """Pide un entero por consola con valor por defecto."""
    raw = input(f"{prompt} [{default}]: ").strip()
    return default if raw == "" else int(raw)


def main():
    # Pedir parámetros N, V, S al usuario (como pide el enunciado CAR)
    N = _ask_int("Número de clientes (N)", NUM_CLIENTES)
    V = _ask_int("Número de vecinos por grupo (V, divisor de N)", MAX_PER_BARRIO)
    S = _ask_int("Número de iteraciones por cliente (S)", NUM_ITERATIONS)

    if N % V != 0:
        raise ValueError("N debe ser múltiplo de V (cada grupo tiene V clientes).")

    # Crear servidor con N y V
    server = ServerController(total_clients=N, group_size=V)

    # Correr todo en asyncio
    asyncio.run(run_simulation(server, N, S))


if __name__ == "__main__":
    main()
