"""
main_clients.py

Lanza SOLO clientes CAR en ESTA máquina.

- Pide S (número de iteraciones por cliente).
- Pide cuántos clientes lanzar localmente (N_local).
- Cada cliente se conecta al servidor definido en common.config.
"""

import asyncio

from client.controller.client_controller import ClientController


def _ask_int(prompt: str, default: int | None = None) -> int:
    """
    Pide un entero por consola con valor por defecto opcional.
    Si el usuario solo pulsa Enter y hay default, devuelve default.
    """
    if default is not None:
        raw = input(f"{prompt} [{default}]: ").strip()
        return default if raw == "" else int(raw)
    else:
        raw = input(f"{prompt}: ").strip()
        return int(raw)


async def run_clients():
    print("=== CLIENTES CAR (solo clientes) ===")

    # Iteraciones por cliente
    S = _ask_int("Número de iteraciones por cliente (S)", 100)

    # Número de clientes a lanzar en ESTA máquina
    N_local = _ask_int("Número de clientes a lanzar en ESTA máquina", 500)

    clients = [ClientController(iterations=S) for _ in range(N_local)]
    tasks = [asyncio.create_task(c.connect()) for c in clients]

    await asyncio.gather(*tasks, return_exceptions=True)
    print("Todos los clientes de esta máquina han terminado.")


if __name__ == "__main__":
    asyncio.run(run_clients())
