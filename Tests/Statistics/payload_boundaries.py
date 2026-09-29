#!/usr/bin/env python3
"""Revalidate full destination payload accounting after the dynamic UDP owner merge.

No production source is edited. Socket-wrapper fixtures inject syscall outcomes;
network cases use the real linked server and actual loopback datagrams. The former 1500-byte boundaries now require complete payloads; protocol and
allocation limits remain separate from successful destination-side accounting.
"""
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from traffic_stats_regression import Host, wait_server, check_delta
from udp_sockaddr_regression import association, encode, exact, handshake, decode_bytes

WRAPPER = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <hev-task.h>
#include <hev-task-io.h>
#include <hev-task-io-socket.h>

static ssize_t fake_sendmsg (int, const struct msghdr *, int);
static ssize_t fake_recvmsg (int, struct msghdr *, int);
#ifdef MSG_WAITFORONE
static int fake_sendmmsg (int, struct mmsghdr *, unsigned int, int);
static int fake_recvmmsg (int, struct mmsghdr *, unsigned int, int,
                         struct timespec *);
#endif
#define sendmsg fake_sendmsg
#define recvmsg fake_recvmsg
#define sendmmsg fake_sendmmsg
#define recvmmsg fake_recvmmsg
#ifdef FORCE_SINGLE_MESSAGE
#undef MSG_WAITFORONE
#endif
#include "lib/io/socket/hev-task-io-socket.c"
#undef sendmsg
#undef recvmsg
#undef sendmmsg
#undef recvmmsg

static int steps[8], position, count, completed, yields, cancel_wait;
static unsigned int lengths[3];

static int
next_result (void)
{
    int r;
    assert (position < count);
    r = steps[position++];
    if (r < 0) {
        errno = -r;
        return -1;
    }
    return r;
}

static ssize_t
fake_sendmsg (int fd, const struct msghdr *msg, int flags)
{
    int r = next_result ();
    assert (fd == 9 && !(flags & MSG_WAITALL));
    if (r < 0)
        return r;
    assert (r == 1 && completed < 3);
    assert (msg->msg_iovlen == 1);
    assert (msg->msg_iov[0].iov_len == lengths[completed]);
    return lengths[completed++];
}

static ssize_t
fake_recvmsg (int fd, struct msghdr *msg, int flags)
{
    return fake_sendmsg (fd, msg, flags);
}

#if defined(__linux__)
static int
fake_sendmmsg (int fd, struct mmsghdr *msg, unsigned int n, int flags)
{
    int r = next_result ();
    assert (fd == 9 && !(flags & MSG_WAITALL));
    if (r < 0)
        return r;
    assert ((unsigned int)r <= n && completed + r <= 3);
    for (int i = 0; i < r; i++) {
        assert (msg[i].msg_hdr.msg_iov[0].iov_len == lengths[completed]);
        msg[i].msg_len = lengths[completed++];
    }
    return r;
}

static int
fake_recvmmsg (int fd, struct mmsghdr *msg, unsigned int n, int flags,
               struct timespec *timeout)
{
    assert (!timeout);
    return fake_sendmmsg (fd, msg, n, flags);
}
#endif

static int
on_wait (HevTaskYieldType type, void *data)
{
    assert (type == HEV_TASK_WAITIO && data == &steps);
    yields++;
    return cancel_wait;
}

static void
check (int receive, int flags, const int *sequence, int size, int cancel,
       int expected, int expected_yields, int empty)
{
    struct mmsghdr messages[3] = { 0 };
    struct iovec vectors[3];
    char bytes[32];
    unsigned int sum = 0, expected_sum = 0;
    int result;

    lengths[0] = empty ? 0 : 3;
    lengths[1] = 7;
    lengths[2] = 11;
    memcpy (steps, sequence, size * sizeof (int));
    position = completed = yields = 0;
    count = size;
    cancel_wait = cancel;
    for (int i = 0; i < 3; i++) {
        vectors[i].iov_base = bytes;
        vectors[i].iov_len = lengths[i];
        messages[i].msg_hdr.msg_iov = &vectors[i];
        messages[i].msg_hdr.msg_iovlen = 1;
        messages[i].msg_len = 0xdeadbeef;
    }
    result = receive ? hev_task_io_socket_recvmmsg (9, messages, 3, flags,
                                                   on_wait, &steps)
                     : hev_task_io_socket_sendmmsg (9, messages, 3, flags,
                                                   on_wait, &steps);
    assert (result == expected && position == count && yields == expected_yields);
    assert (completed == (expected > 0 ? expected : 0));
    for (int i = 0; i < completed; i++) {
        sum += messages[i].msg_len;
        expected_sum += lengths[i];
    }
    assert (sum == expected_sum);
    for (int i = completed; i < 3; i++)
        assert (messages[i].msg_len == 0xdeadbeef);
}

int
main (void)
{
    int cases = 0;
    const int failures[] = { EIO, EPIPE, ECONNRESET, EMSGSIZE, EINTR };
    for (int receive = 0; receive < 2; receive++) {
        for (unsigned int i = 0; i < sizeof (failures) / sizeof (failures[0]); i++) {
            int before[] = { -failures[i] };
            int after[] = { 1, -failures[i] };
            check (receive, MSG_WAITALL, before, 1, 0, -1, 0, 0);
            check (receive, MSG_WAITALL, after, 2, 0, 1, 0, 0);
            cases += 2;
        }
        const int cancel_first[] = { -EAGAIN };
        const int cancel_after[] = { 1, -EAGAIN };
        const int retry[] = { 1, -EAGAIN, 1, 1 };
        const int all[] = { 1, 1, 1 };
        const int once[] = { 1 };
        check (receive, MSG_WAITALL, cancel_first, 1, 1, -2, 1, 0);
        check (receive, MSG_WAITALL, cancel_after, 2, 1, 1, 1, 0);
        check (receive, MSG_WAITALL, retry, 4, 0, 3, 1, 0);
        check (receive, MSG_WAITALL | MSG_DONTWAIT, cancel_after, 2, 0, 1, 0, 0);
        check (receive, MSG_DONTWAIT, once, 1, 0, 1, 0, 0);
        check (receive, MSG_WAITALL, all, 3, 0, 3, 0, 1);
        cases += 6;
#ifdef MSG_WAITFORONE
        const int batch[] = { 2, -EIO };
        check (receive, MSG_WAITALL, batch, 2, 0, 2, 0, 0);
        cases++;
#endif
    }
    printf ("PASS: %d actual socket-wrapper cases; successful prefixes survive "
            "errors/cancellation; stale suffix and zero-byte payload add no bytes\n", cases);
    return 0;
}
'''


def wrappers(core, directory):
    task = core / 'third-part/hev-task-system'
    source = directory / 'wrapper.c'
    source.write_text(WRAPPER)
    common = ['clang', '-std=gnu11', '-Wall', '-Werror', '-Wno-unused-function',
              '-O1', '-g', '-pthread', '-fsanitize=address,undefined',
              '-fno-sanitize-recover=all', '-fno-omit-frame-pointer',
              '-I' + str(task / 'include'), '-I' + str(task / 'src')]
    variants = [('platform', [])]
    if sys.platform == 'linux':
        variants.append(('single-message-fallback-on-linux', ['-DFORCE_SINGLE_MESSAGE']))
    for label, flags in variants:
        binary = directory / label
        subprocess.run([*common, *flags, source, task / 'bin/libhev-task-system.a',
                        '-o', binary], check=True, timeout=45)
        print('WRAPPER:', label, flush=True)
        subprocess.run([binary], check=True, timeout=15,
                       env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0',
                                UBSAN_OPTIONS='halt_on_error=1'))


def network(binary, directory):
    records = []
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as reserve:
        reserve.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        reserve.bind(('::', 0))
        port = reserve.getsockname()[1]
    config = directory / 'server.yml'
    config.write_text(f"""main:
  workers: 4
  port: {port}
  listen-address: '::'
  listen-ipv6-only: false
  udp-port: 0
  bind-address-v4: '0.0.0.0'
  bind-address-v6: '::'
misc:
  log-level: error
""")
    host = Host(str(binary), config)
    try:
        wait_server(port)
        assert host.stats() == (0, 0)

        expected_clients = {'Unattributed': (0, 0)}

        def verify(before, incoming, outgoing):
            check_delta(host, before, incoming, outgoing)
            prior = expected_clients.get(ip, (0, 0))
            expected_clients[ip] = (prior[0] + incoming, prior[1] + outgoing)
            for _ in range(100):
                rows = host.clients()
                if rows == expected_clients:
                    break
                time.sleep(.01)
            assert rows == expected_clients, (rows, expected_clients)
            assert (sum(r[0] for r in rows.values()),
                    sum(r[1] for r in rows.values())) == host.stats()

        def record(**row):
            records.append(row)
            print(json.dumps(row, sort_keys=True), flush=True)

        for ip, domain in [('127.0.0.1', False), ('::1', False), ('127.0.0.1', True)]:
            family = socket.AF_INET6 if ':' in ip else socket.AF_INET
            with socket.socket(family, socket.SOCK_DGRAM) as destination:
                destination.bind((ip, 0))
                destination.settimeout(2)
                destination.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 256 * 1024)
                destination.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 512 * 1024)
                endpoint = destination.getsockname()[:2]
                address = (b'\x03' + bytes([len(ip)]) + ip.encode('ascii') +
                           struct.pack('!H', endpoint[1])) if domain else encode(*endpoint)
                cap = 1500 - 3 - len(address)
                with association((ip, port), 'known') as (_, udp):
                    udp.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 256 * 1024)
                    udp.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 512 * 1024)
                    for size in [0, 1, cap - 1, cap, cap + 1, 1500, 1501, 1999, 2000, 2001,
                                 2048, 4096, 9192, 9216, 30001, 48001, 65000]:
                        before = host.stats()
                        payload = bytes(i % 251 for i in range(size))
                        udp.send(b'\0\0\0' + address + payload)
                        actual, peer = destination.recvfrom(65535)
                        copied = size
                        assert actual == payload[:copied]
                        destination.sendto(actual, peer)
                        response = udp.recv(65535)
                        source, offset = decode_bytes(response[3:])
                        assert response[:3] == b'\0\0\0' and source == endpoint
                        assert response[3 + offset:] == actual
                        verify(before, copied, copied)
                        record(case='outbound', address_type='domain' if domain else ip,
                               original=size, external_sent=copied, counted_out=copied,
                               truncated=False)
                    # Use a small request to test independently oversized destination replies.
                    for size in [0, 1, 1499, 1500, 1501, 2048, 4096, 9216, 30001, 48001, 65000]:
                        before = host.stats()
                        udp.send(b'\0\0\0' + address + b'R')
                        request, peer = destination.recvfrom(65535)
                        assert request == b'R'
                        payload = bytes(i % 251 for i in range(size))
                        destination.sendto(payload, peer)
                        response = udp.recv(65535)
                        source, offset = decode_bytes(response[3:])
                        copied = size
                        assert source == endpoint and response[3 + offset:] == payload[:copied]
                        verify(before, copied, 1)
                        record(case='inbound', address_type='domain' if domain else ip,
                               original=size, external_copied=copied, counted_in=copied,
                               truncated=False)
                # Former UDP-over-TCP capacity boundaries must now relay in full.
                limit = 1500 - len(address)
                for size in [0, limit - 1, limit, limit + 1, 2048, 4096, 30001, 48001, 65000]:
                    before = host.stats()
                    with socket.create_connection((ip, port), timeout=2) as tcp:
                        handshake(tcp, 5, ('::' if family == socket.AF_INET6 else '0.0.0.0', 0))
                        payload = b'T' * size
                        frame = struct.pack('!HB', size, 3 + len(address)) + address + payload
                        tcp.sendall(frame[:2])
                        tcp.sendall(frame[2:5])
                        tcp.sendall(frame[5:])
                        actual, peer = destination.recvfrom(70000)
                        assert actual == payload
                        destination.sendto(actual, peer)
                        length, header = struct.unpack('!HB', exact(tcp, 3))
                        assert length == size
                        exact(tcp, header - 3)
                        assert exact(tcp, length) == payload
                        verify(before, size, size)
                    record(case='udp-over-tcp', address_type='domain' if domain else ip,
                           original=size, former_limit=limit, external_sent=size, rejected=False)
        print('PASS:', len(records), 'real full-payload network cases; former truncation/rejection boundaries pass; exact In/Out and IP sums', flush=True)
    finally:
        host.close()


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled.')
    if len(sys.argv) != 3:
        raise SystemExit('usage: payload_boundaries.py <compiled statistics host> <patched native source>')
    binary, core = map(lambda arg: Path(arg).resolve(), sys.argv[1:])
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        wrappers(core, directory)
        network(binary, directory)


if __name__ == '__main__':
    main()
