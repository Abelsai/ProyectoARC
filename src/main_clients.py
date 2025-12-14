import asyncio
import multiprocessing as mp
import os
import random
import time

import winloop
from client.controller.client_controller import ClientController

# Ajusta para remoto (Wi-Fi): menos agresivo
CONNECT_CONCURRENCY = 200   # handshakes concurrentes por proceso
BATCH_SIZE = 200            # cuántos tasks “arrancas” antes de pausar
BATCH_PAUSE = 0.05          # pausa entre oleadas
PROC_STAGGER = 0.6          # cada proceso espera i*PROC_STAGGER antes de empezar

RETRY_BASE = 0.25
RETRY_MAX  = 5.0

def _ask_int(prompt: str, default: int) -> int:
    raw = input(f"{prompt} [{default}]: ").strip()
    return default if raw == "" else int(raw)

async def _run_one_client(iterations: int, gate: asyncio.Semaphore):
    # IMPORTANTE: no permitimos “fallar y salir” antes del START
    backoff = RETRY_BASE
    while True:
        try:
            c = ClientController(iterations=iterations)
            await c.connect(connect_gate=gate)
            return  # terminó simulación
        except Exception as e:
            # reintento con jitter (evita picos sincronizados)
            await asyncio.sleep(backoff + random.uniform(0, backoff))
            backoff = min(RETRY_MAX, backoff * 1.7)

async def _launch_process_clients(count: int, iterations: int, start_delay: float):
    await asyncio.sleep(start_delay)

    gate = asyncio.Semaphore(CONNECT_CONCURRENCY)
    tasks = []

    launched = 0
    while launched < count:
        to_launch = min(BATCH_SIZE, count - launched)
        for _ in range(to_launch):
            tasks.append(asyncio.create_task(_run_one_client(iterations, gate)))
        launched += to_launch
        await asyncio.sleep(BATCH_PAUSE)

    await asyncio.gather(*tasks)

def _process_entry(count: int, iterations: int, start_delay: float):
    # winloop UNA vez por proceso
    winloop.install()
    t0 = time.perf_counter()
    asyncio.run(_launch_process_clients(count, iterations, start_delay))
    print(f"[{mp.current_process().name}] listo en {time.perf_counter()-t0:.2f}s")

def main():
    N = _ask_int("Número total de clientes (N)", 15000)
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
