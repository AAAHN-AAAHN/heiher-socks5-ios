#!/usr/bin/env python3
"""Additional caller-buffer/IP-cardinality contracts on the actual native collector.

Reuses the existing peer/failure fixture. Generated C only supplies more test inputs;
production and historical assertions are not rewritten or replaced.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

if not __debug__:
    raise SystemExit('Assertions must be enabled.')
ROOT = Path(__file__).resolve().parents[2]
core, output, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
assert mode in ('buffered', 'splice')
task = core / 'third-part/hev-task-system'
fixture = r'''
#define main original_client_contracts
#include "client_probe.c"
#undef main

int
main (void)
{
    enum { added = 2048 };
    void *clients[added];
    size_t base, count, capacities[10], i, j;
    uint64_t received, sent, sum_in = 0, sum_out = 0;
    HevSocks5ClientStats *rows;
    int calls;

    assert (original_client_contracts () == 0);
    base = hev_socks5_server_client_stats (NULL, 0);
    for (i = 0; i < added; i++) {
        clients[i] = hev_socks5_transfer_client (10000 + (int)i);
        assert (clients[i] != NULL);
        /* A different fd with the same normalized peer must reuse its bucket. */
        assert (clients[i] == hev_socks5_transfer_client (75536 + (int)i));
        hev_socks5_transfer_add (i + 1, 3 * i + 7, clients[i]);
    }
    count = hev_socks5_server_client_stats (NULL, 0);
    assert (count == base + added && count > 256);
    rows = calloc (count + 2, sizeof (*rows));
    assert (rows);
    /* Registration between the size query and the copy must not overrun. */
    assert (hev_socks5_transfer_client (60000));
    assert (hev_socks5_server_client_stats (NULL, 0) == count + 1);
    capacities[0] = 0;
    capacities[1] = 1;
    capacities[2] = 2;
    capacities[3] = base - 1;
    capacities[4] = base;
    capacities[5] = base + 1;
    capacities[6] = count - 1;
    capacities[7] = count;
    capacities[8] = count + 1;
    capacities[9] = count + 2;
    for (j = 0; j < 10; j++) {
        size_t capacity = capacities[j];
        size_t written = capacity < count + 1 ? capacity : count + 1;
        memset (rows, 0xa5, (count + 2) * sizeof (*rows));
        assert (hev_socks5_server_client_stats (rows, capacity) == count + 1);
        for (i = 0; i < written; i++) {
            assert (rows[i].id == i);
            assert (memchr (rows[i].address, 0, sizeof (rows[i].address)));
            if (i >= base && i < count) {
                assert (rows[i].received == i - base + 1);
                assert (rows[i].sent == 3 * (i - base) + 7);
            }
        }
        for (i = written * sizeof (*rows); i < (count + 2) * sizeof (*rows); i++)
            assert (((unsigned char *)rows)[i] == 0xa5);
    }
    calls = atomic_load (&peer_calls);
    hev_socks5_transfer_add (SIZE_MAX, SIZE_MAX, clients[0]);
    hev_socks5_transfer_add (1, 1, clients[0]);
    assert (atomic_load (&peer_calls) == calls);
    assert (hev_socks5_server_client_stats (rows, count + 1) == count + 1);
    for (i = 0; i <= count; i++) {
        sum_in += rows[i].received;
        sum_out += rows[i].sent;
    }
    hev_socks5_transfer_get (&received, &sent);
    assert (received == sum_in && sent == sum_out);
    atomic_store (&fail_allocation, 1);
    assert (hev_socks5_transfer_client (10000) == clients[0]);
    assert (!hev_socks5_transfer_client (61000));
    atomic_store (&fail_allocation, 0);
    free (rows);
    puts ("PASS: 2048 additional IPs, hash collisions and same-IP fd aliases; all 10 snapshot capacities/canaries, registration race, atomic wrap conservation and allocation fallback");
    return 0;
}
'''
variants = [('normal', []) , ('asan', ['-O1', '-g', '-fsanitize=address,undefined',
                                    '-fno-sanitize-recover=all', '-fno-omit-frame-pointer'])]
if sys.platform == 'darwin':
    variants.append(('tsan', ['-O1', '-g', '-fsanitize=thread']))
with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    source = folder / 'RegistryContract.c'
    source.write_text(fixture)
    for label, flags in variants:
        executable = folder / 'test'
        command = ['clang', '-std=gnu11', '-O2', '-Wall', '-Werror', '-pthread', *flags,
                   '-I' + str(ROOT / 'Tests/Statistics'), '-I' + str(core / 'src'),
                   '-I' + str(core / 'src/core/src'), '-I' + str(task / 'include'),
                   str(source), str(core / 'bin/libhev-socks5-server.a'),
                   str(core / 'third-part/yaml/bin/libyaml.a'),
                   str(task / 'bin/libhev-task-system.a'), '-o', str(executable)]
        with (output / (mode + '-registry-' + label + '-build.log')).open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=90)
        environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=0',
                           UBSAN_OPTIONS='halt_on_error=1', TSAN_OPTIONS='halt_on_error=1')
        with (output / (mode + '-registry-' + label + '.log')).open('w') as log:
            subprocess.run([str(executable)], stdout=log, stderr=subprocess.STDOUT,
                           env=environment, check=True, timeout=90)
        print('PASS:', mode, label, 'expanded actual-collector contracts', flush=True)
print('Platform peer/allocation substitutes remain test-only; not a physical high-cardinality network test.', flush=True)
