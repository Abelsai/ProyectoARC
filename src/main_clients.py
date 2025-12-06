import asyncio
import multiprocessing
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


# Función para crear y conectar a un grupo de clientes
async def connect_to_server(client_id, total_clients, start_id, iterations):
    client_controller = ClientController(iterations=iterations)
    await client_controller.connect()


# Función para lanzar los clientes en diferentes procesos
def launch_clients_process(start_id, total_clients, clients_per_process, iterations):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    tasks = []
    # Dividir los clientes entre los procesos
    for client_id in range(clients_per_process):
        tasks.append(connect_to_server(client_id, total_clients, start_id, iterations))

    loop.run_until_complete(asyncio.gather(*tasks))


# Función para manejar el lanzamiento de múltiples procesos
def main():
    total_clients = _ask_int("Número total de clientes (N)", 65000)  # Número total de clientes
    iterations = _ask_int("Número de iteraciones por cliente (S)", 100)  # Número de iteraciones por cliente
    processes = _ask_int("Número de procesos (por ejemplo, 8)", 4)  # Número de procesos
    clients_per_process = total_clients // processes  # Número de clientes por proceso

    # Lanzar un proceso por cada grupo de clientes
    processes_list = []
    for i in range(processes):
        start_id = i * clients_per_process
        p = multiprocessing.Process(target=launch_clients_process, args=(start_id, total_clients, clients_per_process, iterations))
        processes_list.append(p)
        p.start()

    # Esperar a que todos los procesos terminen
    for p in processes_list:
        p.join()


if __name__ == "__main__":
    main()
