# main_clients.py
import asyncio
import multiprocessing
import time
from client.controller.client_controller import ClientController

# === Parámetros de rampa (ajústalos si hace falta) ===
BATCH_SIZE = 200          # nº de clientes que lanzo de golpe
BATCH_PAUSE = 0.05        # seg de pausa entre oleadas
LOG_EVERY = 1000          # log cada X clientes arrancados

def _ask_int(prompt: str, default: int | None = None) -> int:
    if default is not None:
        raw = input(f"{prompt} [{default}]: ").strip()
        return default if raw == "" else int(raw)
    else:
        raw = input(f"{prompt}: ").strip()
        return int(raw)

async def _safe_connect(iterations: int) -> bool:
    """Arranca 1 cliente y traga excepciones para no tumbar el gather."""
    try:
        c = ClientController(iterations=iterations)
        await c.connect()      # OJO: no vuelve hasta fin de simulación
        return True
    except Exception as e:
        # No paramos el mundo por un fallo puntual de conexión.
        print(f"[WARN] cliente no pudo conectarse: {e}")
        return False

async def _launch_clients_async(count: int, iterations: int):
    """Lanza 'count' clientes en oleadas (pacing) y espera a que todos terminen."""
    tasks = []
    launched = 0
    while launched < count:
        # lanzamos una oleada de hasta BATCH_SIZE clientes
        to_launch = min(BATCH_SIZE, count - launched)
        for _ in range(to_launch):
            tasks.append(asyncio.create_task(_safe_connect(iterations)))
        launched += to_launch

        if launched % LOG_EVERY == 0 or launched == count:
            print(f"[PROCESO {multiprocessing.current_process().name}] lanzados {launched}/{count}")

        # pequeña pausa para no saturar la cola de accept del servidor
        await asyncio.sleep(BATCH_PAUSE)

    # Esperamos a que terminen TODOS (sin propagar excepciones)
    results = await asyncio.gather(*tasks, return_exceptions=True)
    ok = sum(1 for r in results if r is True)
    fail = count - ok
    print(f"[PROCESO {multiprocessing.current_process().name}] OK={ok}  FAIL={fail}")

def _launch_clients_process(count: int, iterations: int):
    """Target del proceso: crea su propio loop y lanza su tanda."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    t0 = time.perf_counter()
    loop.run_until_complete(_launch_clients_async(count, iterations))
    t1 = time.perf_counter()
    print(f"[PROCESO {multiprocessing.current_process().name}] terminado en {t1 - t0:.2f}s")

def main():
    total_clients = _ask_int("Número total de clientes (N)", 6000)
    iterations = _ask_int("Número de iteraciones por cliente (S)", 1)
    processes = _ask_int("Número de procesos de clientes", 2)

    clients_per_process = total_clients // processes
    extra = total_clients % processes

    procs: list[multiprocessing.Process] = []
    for i in range(processes):
        count = clients_per_process + (1 if i < extra else 0)
        p = multiprocessing.Process(
            target=_launch_clients_process,
            args=(count, iterations),
            name=f"C{i+1}"
        )
        p.start()
        procs.append(p)

    for p in procs:
        p.join()

if __name__ == "__main__":
    main()
