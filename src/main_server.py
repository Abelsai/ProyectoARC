import asyncio

"""
Sistema Realidad Aumentada Colaborativa mediante Sockets TCP

Punto de entrada del servidor.
- Pide por consola N (clientes totales) y V (tamaño de grupo).
- Instala winloop antes de crear el loop de asyncio (Windows).
"""

# winloop debe instalarse antes de asyncio.run()
try:
    import winloop
    winloop.install()
except Exception:
    # Si winloop no está disponible, se usa el loop por defecto de asyncio.
    pass

from server.controller.server_controller import ServerController


def _ask_int(prompt: str, default: int | None = None) -> int:
    """Lee un entero por consola con valor por defecto."""
    raw = input(f"{prompt} [{default}]: ").strip() if default is not None else input(f"{prompt}: ").strip()
    return default if (default is not None and raw == "") else int(raw)


async def run_single_server(total_clients: int, group_size: int) -> None:
    """Crea una instancia del servidor y la ejecuta."""
    server = ServerController(total_clients, group_size)
    await server.start()


def main() -> None:
    print("Servidor - Sistema Realidad Aumentada Colaborativa mediante Sockets TCP")
    N = _ask_int("Número TOTAL de clientes (N)", 6000)

    # Nota: aquí V es el tamaño del grupo. Cada cliente tendrá (V-1) vecinos.
    V = _ask_int("Tamaño del grupo (V, divisor de N)", 100)

    if N % V != 0:
        raise ValueError("N debe ser múltiplo de V (cada grupo tiene V clientes).")

    asyncio.run(run_single_server(N, V))


if __name__ == "__main__":
    main()
