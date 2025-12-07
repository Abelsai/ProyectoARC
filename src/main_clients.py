# main_clients.py
import asyncio
import multiprocessing
from client.controller.client_controller import ClientController

def _ask_int(prompt: str, default: int | None = None) -> int:
    if default is not None:
        raw = input(f"{prompt} [{default}]: ").strip()
        return default if raw == "" else int(raw)
    else:
        raw = input(f"{prompt}: ").strip()
        return int(raw)

async def connect_to_server(_client_idx: int, total_clients: int, start_id: int, iterations: int):
    client = ClientController(iterations=iterations)
    await client.connect()

def launch_clients_process(start_id: int, total_clients: int, clients_per_process: int, iterations: int):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    tasks = []
    for idx in range(clients_per_process):
        tasks.append(connect_to_server(idx, total_clients, start_id, iterations))

    loop.run_until_complete(asyncio.gather(*tasks))

def main():
    total_clients = _ask_int("Número total de clientes (N)", 60000)
    iterations = _ask_int("Número de iteraciones por cliente (S)", 100)
    processes = _ask_int("Número de procesos de clientes", 8)

    clients_per_process = total_clients // processes
    processes_list: list[multiprocessing.Process] = []

    for i in range(processes):
        start_id = i * clients_per_process
        p = multiprocessing.Process(
            target=launch_clients_process,
            args=(start_id, total_clients, clients_per_process, iterations),
        )
        p.start()
        processes_list.append(p)

    for p in processes_list:
        p.join()

if __name__ == "__main__":
    main()
