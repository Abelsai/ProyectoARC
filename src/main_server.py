# main_server.py
import asyncio
import multiprocessing
import platform
from server.controller.server_controller import ServerController

def _ask_int(prompt: str, default: int | None = None) -> int:
    if default is not None:
        raw = input(f"{prompt} [{default}]: ").strip()
        return default if raw == "" else int(raw)
    else:
        raw = input(f"{prompt}: ").strip()
        return int(raw)

async def run_server_instance(total_clients: int, group_size: int):
    server = ServerController(total_clients, group_size)
    await server.start()

def start_server_process(total_clients: int, group_size: int):
    asyncio.run(run_server_instance(total_clients, group_size))

def main():
    print("=== SERVIDOR CAR ===")
    N = _ask_int("Número TOTAL de clientes (N)", 60000)
    V = _ask_int("Número de vecinos por grupo (V, divisor de N)", 100)

    if N % V != 0:
        raise ValueError("N debe ser múltiplo de V (cada grupo tiene V clientes).")

    # Si estamos en Windows, lanzar sólo un proceso; en otros sistemas, se puede usar multiproceso
    if platform.system() == "Windows":
        asyncio.run(run_server_instance(N, V))
    else:
        workers = _ask_int("Número de procesos del servidor", 4)
        processes: list[multiprocessing.Process] = []
        for _ in range(workers):
            p = multiprocessing.Process(target=start_server_process, args=(N, V))
            p.start()
            processes.append(p)
        for p in processes:
            p.join()

if __name__ == "__main__":
    main()
