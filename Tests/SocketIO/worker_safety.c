#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <time.h>
#include <unistd.h>
static _Thread_local int pause_writer;
static atomic_int waiting, resume_writer;
static void
fixture_fence (memory_order order)
{
    atomic_thread_fence (order);
    if (order == memory_order_release && pause_writer) {
        pause_writer = 0;
        atomic_store (&waiting, 1);
        while (!atomic_load (&resume_writer)) {
            struct timespec t = { 0, 1000000 };
            nanosleep (&t, 0);
        }
    }
}
#undef atomic_thread_fence
#define atomic_thread_fence fixture_fence
#include "worker_meter.c"
#undef atomic_thread_fence
static WmPeer *
peer (WmWorker *w, unsigned ip)
{
    struct sockaddr_in a = { .sin_family = AF_INET,
                             .sin_addr.s_addr = htonl (ip) };
    return wm_peer (w, (void *)&a, sizeof (a));
}
static void *
add (void *p)
{
    pause_writer = 1;
    wm_add (p, 100, 200);
    return 0;
}
static double
now (clockid_t id)
{
    struct timespec t;
    clock_gettime (id, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}
static size_t
retained (void)
{
    size_t n = 0;
    for (unsigned i = 0; i < 256; i++)
        for (Identity *p = atomic_load (&identities[i]); p; p = p->next)
            n++;
    return n;
}
static void *
reader (void *arg)
{
    atomic_int *done = arg;
    while (!atomic_load (done)) {
        uint64_t a = 0, b = 0;
        size_t n = wm_try_snapshot (0, 0, &a, &b);
        if (n != SIZE_MAX)
            assert (b == 2 * a);
    }
    return 0;
}
static unsigned copied;
static void
copy_row (uint64_t id, const char *address, uint64_t in, uint64_t out,
          void *context)
{
    (void)id;
    (void)address;
    (void)in;
    (void)out;
    (void)context;
    copied++;
}
static atomic_int callback_waiting, callback_release;
static void
hold_row (uint64_t id, const char *address, uint64_t in, uint64_t out,
          void *context)
{
    (void)in;
    (void)out;
    (void)context;
    if (!id)
        return;
    char saved[64];
    strcpy (saved, address);
    atomic_store (&callback_waiting, 1);
    while (!atomic_load (&callback_release))
        sched_yield ();
    assert (!strcmp (saved, address));
}
static void *
held_snapshot (void *context)
{
    (void)context;
    wm_snapshot (hold_row, NULL, NULL, NULL);
    return NULL;
}
int
main (void)
{
    alarm (30);
    WmWorker *w = wm_worker_new ();
    assert (wm_begin_session () == 0);
    WmPeer *p = peer (w, 0x7f000001);
    wm_add (p, 1, 2);
    pthread_t t;
    pthread_create (&t, 0, add, p);
    while (!atomic_load (&waiting))
        sched_yield ();
    double wall = now (CLOCK_MONOTONIC), cpu = now (CLOCK_THREAD_CPUTIME_ID);
    uint64_t a = 123, b = 456;
    for (int i = 0; i < 10000; i++) {
        assert (wm_try_snapshot (0, 0, &a, &b) == SIZE_MAX);
        assert (a == 123 && b == 456);
    }
    printf ("10000 rejected snapshots wall=%f cpu=%f unchanged_outputs=1\n",
            now (CLOCK_MONOTONIC) - wall, now (CLOCK_THREAD_CPUTIME_ID) - cpu);
    atomic_store (&resume_writer, 1);
    pthread_join (t, 0);
    assert (wm_try_snapshot (0, 0, &a, &b) == 2 && a == 101 && b == 202);
    wm_add (wm_unknown (w), 1, 2);
    atomic_store (&waiting, 0);
    atomic_store (&resume_writer, 0);
    assert (pthread_create (&t, NULL, add, p) == 0);
    while (!atomic_load (&waiting))
        sched_yield ();
    a = 123;
    b = 456;
    copied = 0;
    assert (wm_try_snapshot (copy_row, NULL, &a, &b) == SIZE_MAX);
    assert (copied > 0 && a == 123 && b == 456);
    atomic_store (&resume_writer, 1);
    assert (pthread_join (t, NULL) == 0);
    assert (wm_try_snapshot (NULL, NULL, &a, &b) == 2 && a == 202 && b == 404);
    assert (pthread_create (&t, NULL, held_snapshot, NULL) == 0);
    while (!atomic_load (&callback_waiting))
        sched_yield ();
    assert (wm_begin_session () == 0);
    wm_worker_release (w);
    assert (retained () ==
            1); /* Borrowed address remains alive until callback exit. */
    atomic_store (&callback_release, 1);
    assert (pthread_join (t, NULL) == 0);
    assert (wm_begin_session () == 0 && retained () == 0);
    puts (
        "PASS: partial copied rows rejected; held callback protects address lifetime");
    for (unsigned session = 0; session < 100; session++) {
        assert (wm_begin_session () == 0);
        w = wm_worker_new ();
        for (unsigned i = 0; i < 1000; i++)
            wm_add (peer (w, 0x0a000001 + session * 1000 + i), 1, 2);
        assert (wm_try_snapshot (0, 0, &a, &b) == 1001 && a == 1000 &&
                b == 2000);
        assert (retained () == 1000);
        wm_worker_release (w);
    }
    printf ("100 sessions x1000 peers retained=%zu current totals=%llu/%llu\n",
            retained (), (unsigned long long)a, (unsigned long long)b);
    atomic_int done = 0;
    pthread_t r;
    pthread_create (&r, 0, reader, &done);
    for (unsigned session = 0; session < 100; session++) {
        assert (wm_begin_session () == 0);
        w = wm_worker_new ();
        for (unsigned i = 0; i < 1000; i++)
            wm_add (peer (w, 0x0b000001 + session * 1000 + i), 1, 2);
        wm_worker_release (w);
    }
    atomic_store (&done, 1);
    pthread_join (r, 0);
    assert (wm_begin_session () == 0);
    assert (retained () == 0);
    printf ("concurrent reader/registration/collection: final retained=%zu\n",
            retained ());
    return 0;
}
