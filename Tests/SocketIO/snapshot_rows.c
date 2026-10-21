/* Actual server snapshot API: concurrent same-IP registration and packed rows. */
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <arpa/inet.h>
#include "hev-main.h"
#include "worker_meter.h"
#define WORKERS 8
#define IPS 128
static atomic_uint ready, go;
static void *
writer (void *arg)
{
    (void)arg;
    WmWorker *w = wm_worker_new ();
    assert (w);
    atomic_fetch_add (&ready, 1);
    while (!atomic_load_explicit (&go, memory_order_acquire)) {
    }
    for (unsigned i = 1; i <= IPS; i++) {
        struct sockaddr_in a = { 0 };
        a.sin_family = AF_INET;
        a.sin_addr.s_addr = htonl (0x0a090000u + i);
        WmPeer *p = wm_peer (w, (struct sockaddr *)&a, sizeof a);
        assert (p);
        wm_add (p, i, i * 2);
    }
    wm_worker_release (w);
    return NULL;
}
int
main (void)
{
    pthread_t threads[WORKERS];
    for (unsigned i = 0; i < WORKERS; i++)
        assert (!pthread_create (&threads[i], NULL, writer, NULL));
    while (atomic_load_explicit (&ready, memory_order_acquire) != WORKERS) {
    }
    atomic_store_explicit (&go, 1, memory_order_release);
    for (unsigned i = 0; i < WORKERS; i++)
        assert (!pthread_join (threads[i], NULL));
    size_t n = hev_socks5_server_endpoint_rows (NULL, 0);
    assert (n == IPS + 1);
    uint64_t in, out;
    hev_socks5_server_endpoint_stats (&in, &out);
    assert (in == WORKERS * (uint64_t)IPS * (IPS + 1) / 2 && out == 2 * in);
    uint64_t maxid = 0;
    for (size_t cap = 0; cap <= n + 1; cap++) {
        HevSocks5EndpointStats *rows = malloc ((cap + 1) * sizeof (*rows));
        assert (rows);
        memset (rows, 0xa5, (cap + 1) * sizeof (*rows));
        assert (hev_socks5_server_endpoint_rows (rows, cap) == n);
        size_t used = cap < n ? cap : n;
        for (size_t i = 0; i < used; i++) {
            if (!i)
                assert (rows[i].id == 0 &&
                        !strcmp (rows[i].address, "Unattributed"));
            else {
                unsigned value;
                assert (sscanf (rows[i].address, "10.9.0.%u", &value) == 1);
                assert (value >= 1 && value <= IPS &&
                        rows[i].received == WORKERS * value &&
                        rows[i].sent == 2 * WORKERS * value);
                for (size_t j = 0; j < i; j++)
                    assert (rows[j].id != rows[i].id);
                if (rows[i].id > maxid)
                    maxid = rows[i].id;
            }
        }
        for (size_t byte = used * sizeof (*rows);
             byte < (cap + 1) * sizeof (*rows); byte++)
            assert (((unsigned char *)rows)[byte] == 0xa5);
        free (rows);
    }
    printf (
        "PASS: %d writers, %zu packed rows, capacity 0..%zu, canaries intact; max ID=%llu (ID gaps permitted)\n",
        WORKERS, n, n + 1, (unsigned long long)maxid);
    return 0;
}
