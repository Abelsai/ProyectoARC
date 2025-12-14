"""
Configuración común del Sistema Realidad Aumentada Colaborativa mediante Sockets TCP.

Ojo con SERVER_HOST:
- En el servidor, "0.0.0.0" sirve para escuchar en todas las interfaces.
- En los clientes, SERVER_HOST debe ser la IP/hostname real del servidor (no 0.0.0.0).
"""

SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8888

# Tamaño de buffers (SO_RCVBUF / SO_SNDBUF). En redes con mucha carga puede ayudar,
# aunque el rendimiento real depende del SO y del driver.
BUFFER_SIZE = 65536

ENCODING = "utf-8"

# Reservadas para fases futuras del proyecto (ahora mismo no se usan en los ficheros que has pasado).
# SIMULATION_INTERVAL = 2.0
# MAX_PER_BARRIO = 10
