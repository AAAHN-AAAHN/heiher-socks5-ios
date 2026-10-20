#!/usr/bin/env python3
"""Observe native UDP receive-queue behavior without a proxy or OS changes."""
import json
import socket

rows = []
for host in ('127.0.0.1', '::1'):
    family = socket.AF_INET6 if ':' in host else socket.AF_INET
    for connect_after_first in (False, True):
        with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as receiver, socket.socket(family, socket.SOCK_DGRAM) as sender:
            receiver.bind(('::', 0)); sender.bind((host, 0)); receiver.settimeout(.1)
            for n in range(26): sender.sendto(str(n).encode(), (host, receiver.getsockname()[1]))
            first, address = receiver.recvfrom(2048)
            if connect_after_first: receiver.connect(address)
            packets = [first.decode()]
            while True:
                try: packets.append(receiver.recvfrom(2048)[0].decode())
                except socket.timeout: break
            row = dict(host=host, connectAfterFirst=connect_after_first,
                       receiveBuffer=receiver.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF),
                       sent=26, received=packets)
            rows.append(row)
print(json.dumps(rows, indent=2))
