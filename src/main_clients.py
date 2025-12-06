import asyncio
import socket
from common.config import SERVER_HOST, SERVER_PORT, BUFFER_SIZE  # Asegúrate de que estas variables estén definidas en common/config.py
from common.protocol import make_message, MessageType, encode_message, decode_message  # Asegúrate de que estas funciones estén definidas en common/protocol.py


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
async def connect_to_server(client_id, total_clients, start_id):
    reader, writer = await asyncio.open_connection(SERVER_HOST, SERVER_PORT)
    
    transport = writer.transport
    sock = transport.get_extra_info('socket')
    
    # Configura los buffers
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, BUFFER_SIZE)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, BUFFER_SIZE)

    # Enviar mensaje JOIN
    join_msg = make_message(MessageType.JOIN, "TEMP")
    writer.write(encode_message(join_msg))
    await writer.drain()
    print(f"[CLIENTE {client_id + start_id}] Conectado al servidor")

    await writer.drain()
    writer.close()
    await writer.wait_closed()


# Función principal para manejar todos los clientes
async def main():
    total_clients = _ask_int("Número total de clientes (N)", 65000)  # Número total de clientes
    clients_per_process = total_clients  # Lanzamos todos los clientes en un solo proceso

    tasks = []
    for client_id in range(clients_per_process):
        tasks.append(connect_to_server(client_id, total_clients, 0))  # Lanza todos los clientes en un solo proceso

    # Ejecuta todas las tareas de manera concurrente
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
