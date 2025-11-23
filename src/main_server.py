"""
main_server.py

Lanza SOLO el servidor CAR.

- Pide N (total de clientes en TODO el sistema).
- Pide V (tamaño de grupo / vecinos por grupo).
- Arranca el ServerController y se queda escuchando.
"""

import asyncio

from server.controller.server_controller import ServerController


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


async def run_server():
    print("=== SERVIDOR CAR (solo servidor) ===")

    # Número TOTAL de clientes que esperas (sumando todas las máquinas)
    N = _ask_int("Número TOTAL de clientes (N)", 1000)

    # Tamaño de grupo / número de vecinos por grupo
    V = _ask_int("Número de vecinos por grupo (V, divisor de N)", 10)

    if N % V != 0:
        raise ValueError("N debe ser múltiplo de V (cada grupo tiene V clientes).")

    server = ServerController(total_clients=N, group_size=V)
    await server.start()


if __name__ == "__main__":
    asyncio.run(run_server())
