# main_clients.py
import asyncio
import multiprocessing as mp
import os
import random
import time

from client.controller.client_controller import ClientController

# Ajusta para remoto (Wi-Fi): menos agresivo suele ir mejor
CONNECT_CONCURRENCY = 150   # handshakes concurrentes por proceso (Wi-Fi: 50–200, cable: 200–500)
BATCH_SIZE = 200            # tareas que creas por oleada
BATCH_PAUSE = 0.05          # pausa entre oleadas
PROC_STAGGER = 0.6          # delay entre procesos: i * PROC_STAGGER

RETRY_BASE = 0.25
RETRY_MAX = 5.0

LOG_EVERY = 2000            # reduce logs

def _ask_int(prompt: str, default: int) -> int:
    raw = input(f"{prompt} [{default}]: ").strip()
    return default if raw == "" else int(raw)

def _install_winloop_once_per_process():
    # Debe ejecutarse ANTES de asyncio.run() (antes de que exista un loop)
    try:
        import winloop
        winloop.install()
    except Exception:
        # si winloop no está, seguimos con el loop por defecto
        pass

async def _run_one_client(iterations: int, gate: asyncio.Semaphore):
    backoff = RETRY_BASE
    while True:
        try:
            c = ClientController(iterations=iterations)
            await c.connect(connect_gate=gate)  # vuelve al final de la simulación
            return
        except Exception:
            await asyncio.sleep(backoff + random.uniform(0, backoff))
            backoff = min(RETRY_MAX, backoff * 1.7)

async def _launch_process_clients(count: int, iterations: int, start_delay: float):
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
            # log muy ligero
            print(f"[{mp.current_process().name}] creados {launched}/{count}")

        await asyncio.sleep(BATCH_PAUSE)

    await asyncio.gather(*tasks)

def _process_entry(count: int, iterations: int, start_delay: float):
    _install_winloop_once_per_process()

    t0 = time.perf_counter()
    asyncio.run(_launch_process_clients(count, iterations, start_delay))
    print(f"[{mp.current_process().name}] listo en {time.perf_counter() - t0:.2f}s")

def main():
    N = _ask_int("Número total de clientes (N)", 30000)
    S = _ask_int("Iteraciones por cliente (S)", 1)
    P = _ask_int("Procesos", max(1, min(4, os.cpu_count() or 2)))

    base = N // P
    extra = N % P

    mp.set_start_method("spawn", force=True)

    procs = []
    for i in range(P):
        c = base + (1 if i < extra else 0)
        delay = i * PROC_STAGGER
        p = mp.Process(target=_process_entry, args=(c, S, delay), name=f"C{i+1}({c})")
        p.start()
        procs.append(p)

    for p in procs:
        p.join()

if __name__ == "__main__":
    main()
