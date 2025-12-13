import asyncio
from server.controller.server_controller import ServerController

def _ask_int(prompt: str, default: int | None = None) -> int:
    """Solicita un entero por consola con un valor por defecto opcional."""
    raw = input(f"{prompt} [{default}]: ").strip() if default is not None else input(f"{prompt}: ").strip()
    return default if (default is not None and raw == "") else int(raw)


async def run_single_server(total_clients: int, group_size: int) -> None:
    """Crea una instancia del servidor y la arranca."""
    server = ServerController(total_clients, group_size)
    await server.start()


def main() -> None:
    print("=== SERVIDOR CAR (una instancia) ===")
    N = _ask_int("Número TOTAL de clientes (N)", 6000)
    V = _ask_int("Número de vecinos por grupo (V, divisor de N)", 100)

    if N % V != 0:
        raise ValueError("N debe ser múltiplo de V (cada grupo tiene V clientes).")

    # Ejecuta una sola instancia del servidor
    asyncio.run(run_single_server(N, V))


if __name__ == "__main__":
    main()
