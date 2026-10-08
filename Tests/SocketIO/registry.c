#include "worker_meter.c"
#include "worker_meter.h"
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <arpa/inet.h>
#include <time.h>
#define WRITERS 8
#define STEPS 100000
static WmWorker *workers[WRITERS];
static _Atomic unsigned finished;
static void *
writer (void *v)
{
    WmWorker *w = workers[(size_t)v];
    struct sockaddr_in a = { 0 };
    a.sin_family = AF_INET;
    assert (inet_pton (AF_INET, "10.23.4.5", &a.sin_addr) == 1);
    WmPeer *p = wm_peer (w, (const struct sockaddr *)&a, sizeof (a));
    assert (p);
    for (unsigned i = 0; i < STEPS; i++)
        wm_add (p, 3, 6);
    atomic_fetch_add_explicit (&finished, 1, memory_order_release);
    return NULL;
}
static void
row (uint64_t id, const char *address, uint64_t in, uint64_t out, void *v)
{
    (void)id;
    (void)address;
    uint64_t *s = v;
    assert (out == in * 2);
    s[0] += in;
    s[1] += out;
}
int
main (void)
{
    pthread_t threads[WRITERS];
    uint64_t last = 0;
    unsigned reads = 0;
    for (size_t i = 0; i < WRITERS; i++) {
        workers[i] = wm_worker_new ();
        assert (workers[i]);
    }
    for (size_t i = 0; i < WRITERS; i++)
        assert (!pthread_create (&threads[i], NULL, writer, (void *)i));
    while (atomic_load_explicit (&finished, memory_order_acquire) != WRITERS) {
        uint64_t in, out, s[2] = { 0 };
        wm_snapshot (row, s, &in, &out);
        assert (in >= last && out == 2 * in && s[0] == in && s[1] == out);
        last = in;
        reads++;
    }
    for (unsigned i = 0; i < WRITERS; i++)
        assert (!pthread_join (threads[i], NULL));
    uint64_t in, out;
    wm_snapshot (NULL, NULL, &in, &out);
    assert (in == WRITERS * (uint64_t)STEPS * 3 && out == 2 * in);
    struct sockaddr_in a = { 0 };
    a.sin_family = AF_INET;
    inet_pton (AF_INET, "192.168.1.2", &a.sin_addr);
    WmPeer *p = wm_peer (workers[0], (struct sockaddr *)&a, sizeof (a));
    wm_add (p, (size_t)UINT32_MAX, 0);
    wm_add (p, 10, 0);
    wm_snapshot (NULL, NULL, &in, &out);
    assert (in == WRITERS * (uint64_t)STEPS * 3 + (uint64_t)UINT32_MAX + 10);
    printf ("PASS writers=%d updates=%d snapshots=%u rollover=pass\n", WRITERS,
            WRITERS * STEPS, reads);
    return 0;
}
