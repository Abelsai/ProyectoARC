import asyncio
import multiprocessing as mp
import os
import random
import time

"""
Sistema Realidad Aumentada Colaborativa mediante Sockets TCP

Lanzador de clientes.
- Divide N clientes entre P procesos.
- Cada proceso crea sus conexiones en oleadas para no saturar el servidor ni la red.
- Se usa un semáforo (CONNECT_CONCURRENCY) para limitar handshakes concurrentes.
"""

from client.controller.client_controller import ClientController

# Ajustes típicos para remoto (Wi-Fi): menos agresivo suele ser más estable
CONNECT_CONCURRENCY = 150   # conexiones simultáneas por proceso durante el handshake
BATCH_SIZE = 200            # tareas creadas por oleada
BATCH_PAUSE = 0.05          # pausa entre oleadas (segundos)
PROC_STAGGER = 0.6          # retraso entre procesos para que no arranquen todos a la vez

# Reintentos con backoff para conexiones inestables
RETRY_BASE = 0.25
RETRY_MAX = 5.0

LOG_EVERY = 2000            # logs ligeros (evitamos imprimir demasiado con 30k)


def _ask_int(prompt: str, default: int) -> int:
    raw = input(f"{prompt} [{default}]: ").strip()
    return default if raw == "" else int(raw)


def _install_winloop_once_per_process():
    """
    winloop debe instalarse antes de asyncio.run().
    Se llama una vez al inicio de cada proceso.
    """
    try:
        import winloop
        winloop.install()
    except Exception:
        pass


async def _run_one_client(iterations: int, gate: asyncio.Semaphore):
    """
    Ejecuta un cliente con reintento (solo para la fase de conexión).
    Si la conexión falla por congestión/transitorio, se reintenta con backoff.
    """
    backoff = RETRY_BASE
    while True:
        try:
            c = ClientController(iterations=iterations)
            await c.connect(connect_gate=gate)
            return
        except Exception:
            await asyncio.sleep(backoff + random.uniform(0, backoff))
            backoff = min(RETRY_MAX, backoff * 1.7)


async def _launch_process_clients(count: int, iterations: int, start_delay: float):
    """
    Lanza 'count' clientes dentro de un proceso.
    start_delay sirve para escalonar el arranque entre procesos.
    """
    await asyncio.sleep(start_delay)

    gate = asyncio.Semaphore(CONNECT_CONCURRENCY)
    tasks: list[asyncio.Task] = []

    launched = 0
    while launched < count:
        to_launch = min(BATCH_SIZE, count - launched)

        for _ in range(to_launch):
            tasks.append(asyncio.create_task(_run_one_client(iterations, gate)))

        launched += to_launch

        if launched % LOG_EVERY == 0 or launched == count:
            print(f"[{mp.current_process().name}] creados {launched}/{count}")

        await asyncio.sleep(BATCH_PAUSE)

    await asyncio.gather(*tasks)


def _process_entry(count: int, iterations: int, start_delay: float):
    """Entrada del proceso: instala winloop y ejecuta su parte de clientes."""
    _install_winloop_once_per_process()

    t0 = time.perf_counter()
    asyncio.run(_launch_process_clients(count, iterations, start_delay))
    print(f"[{mp.current_process().name}] terminado en {time.perf_counter() - t0:.2f}s")


def main():
    print("Clientes - Sistema Realidad Aumentada Colaborativa mediante Sockets TCP")

    N = _ask_int("Número total de clientes (N)", 30000)
    S = _ask_int("Iteraciones por cliente (S)", 1)
    P = _ask_int("Procesos", max(1, min(4, os.cpu_count() or 2)))

    base = N // P
    extra = N % P

    mp.set_start_method("spawn", force=True)

    procs = []
    for i in range(P):
        count = base + (1 if i < extra else 0)
        delay = i * PROC_STAGGER
        p = mp.Process(target=_process_entry, args=(count, S, delay), name=f"C{i+1}({count})")
        p.start()
        procs.append(p)

    for p in procs:
        p.join()


if __name__ == "__main__":
    main()
