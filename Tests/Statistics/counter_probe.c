/* Test-only: linked to the exact production counter and public getter. */
#include <assert.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include "hev-main.h"

void hev_socks5_transfer_add (size_t, size_t, void *);
static atomic_int done;
static const uint64_t amount = (UINT64_C (1) << 32) + 17;
enum
{
    THREADS = 8,
    REPEATS = 100000
};

static void *
writer (void *arg)
{
    size_t n = (size_t)arg;
    for (int i = 0; i < REPEATS; i++)
        hev_socks5_transfer_add ((size_t)amount + n, (size_t)amount + 2 * n,
                                 NULL);
    atomic_fetch_add (&done, 1);
    return NULL;
}

int
main (void)
{
    pthread_t threads[THREADS];
    uint64_t in, out, prev_in = 0, prev_out = 0;
    for (size_t i = 0; i < THREADS; i++)
        assert (pthread_create (&threads[i], NULL, writer, (void *)i) == 0);
    do {
        hev_socks5_server_stats (&in, &out);
        assert (in >= prev_in && out >= prev_out);
        prev_in = in;
        prev_out = out;
    } while (atomic_load (&done) < THREADS);
    for (int i = 0; i < THREADS; i++)
        assert (pthread_join (threads[i], NULL) == 0);
    hev_socks5_server_stats (&in, &out);
    uint64_t indices = THREADS * (THREADS - 1) / 2;
    assert (in == (THREADS * amount + indices) * REPEATS);
    assert (out == (THREADS * amount + 2 * indices) * REPEATS);
    printf (
        "PASS: 8 writers, 800000 updates, concurrent monotonic reads; totals=%" PRIu64
        "/%" PRIu64 "\n",
        in, out);
    return 0;
}
