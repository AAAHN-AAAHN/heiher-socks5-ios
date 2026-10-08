/* The actual common module, with allocator failures only at controlled points. */
#include <stdlib.h>
#include <assert.h>
static int fail_after = -1;
static void *
test_calloc (size_t n, size_t s)
{
    if (fail_after == 0)
        return NULL;
    if (fail_after > 0)
        --fail_after;
    return calloc (n, s);
}
#define calloc test_calloc
#include "worker_meter.c"
#undef calloc
static unsigned visits;
static void
visit (uint64_t id, const char *s, uint64_t i, uint64_t o, void *ctx)
{
    (void)id;
    (void)s;
    (void)i;
    (void)o;
    (void)ctx;
    ++visits;
    /* Callbacks are outside writer synchronization and may re-enter reads. */
    wm_snapshot (NULL, NULL, NULL, NULL);
}
int
main (void)
{
    fail_after = 0;
    assert (wm_worker_new () == NULL);
    fail_after = -1;
    WmWorker *a = wm_worker_new (), *b = wm_worker_new ();
    assert (a && b && a != b);
    struct sockaddr_in ip = { 0 };
    ip.sin_family = AF_INET;
    assert (inet_pton (AF_INET, "10.12.13.14", &ip.sin_addr) == 1);
    WmPeer *ap = wm_peer (a, (struct sockaddr *)&ip, sizeof ip),
           *bp = wm_peer (b, (struct sockaddr *)&ip, sizeof ip);
    assert (ap != bp && ap->identity == bp->identity);
    wm_add (ap, 1000, 200);
    wm_add (bp, 7, 11);
    struct sockaddr_in6 mapped = { 0 };
    mapped.sin6_family = AF_INET6;
    inet_pton (AF_INET6, "::ffff:10.12.13.14", &mapped.sin6_addr);
    assert (wm_peer (a, (struct sockaddr *)&mapped, sizeof mapped) == ap);
    ip.sin_port = htons (2345);
    assert (wm_peer (a, (struct sockaddr *)&ip, sizeof ip) == ap);
    inet_pton (AF_INET6, "fe80::1234", &mapped.sin6_addr);
    mapped.sin6_scope_id = 1;
    WmPeer *scope1 = wm_peer (a, (struct sockaddr *)&mapped, sizeof mapped);
    mapped.sin6_scope_id = 2;
    assert (wm_peer (a, (struct sockaddr *)&mapped, sizeof mapped) != scope1);
    assert (wm_peer (a, NULL, 0) == wm_unknown (a));
    assert (wm_peer (a, (struct sockaddr *)&ip, 1) == wm_unknown (a));
    inet_pton (AF_INET, "10.12.13.15", &ip.sin_addr);
    fail_after = 0;
    assert (wm_peer (a, (struct sockaddr *)&ip, sizeof ip) == wm_unknown (a));
    wm_add (wm_unknown (a), 17, 19);
    fail_after = 1;
    assert (wm_peer (a, (struct sockaddr *)&ip, sizeof ip) == wm_unknown (a));
    wm_add (wm_unknown (a), 23, 29);
    fail_after = -1;
    WmPeer *p = wm_peer (a, (struct sockaddr *)&ip, sizeof ip);
    p->counter.version = UINT_MAX - 1;
    atomic_store (&p->counter.sequence, UINT_MAX - 1);
    wm_add (p, UINT32_MAX, UINT32_MAX);
    wm_add (p, 17, 19);
    uint64_t i, o;
    counter_read (&p->counter, &i, &o);
    assert (i == (uint64_t)UINT32_MAX + 17 && o == (uint64_t)UINT32_MAX + 19);
    assert (atomic_load (&p->counter.epoch) == 1);
    wm_worker_release (a);
    WmWorker *reuse = wm_worker_new ();
    assert (reuse == a);
    assert (wm_peer (reuse, (struct sockaddr *)&ip, sizeof ip) == p);
    wm_add (p, 3, 5);
    size_t count = wm_snapshot (visit, NULL, &i, &o);
    assert (count == visits);
    assert (i == (uint64_t)UINT32_MAX + 17 + 3 + 1000 + 7 + 17 + 23);
    assert (o == (uint64_t)UINT32_MAX + 19 + 5 + 200 + 11 + 19 + 29);
    /* Finite ID exhaustion does not alias an existing identity. */
    atomic_store (&serial, UINT_MAX);
    inet_pton (AF_INET, "10.12.13.16", &ip.sin_addr);
    assert (wm_peer (b, (struct sockaddr *)&ip, sizeof ip) == wm_unknown (b));
    puts (
        "PASS: worker ownership, normalized IP/scope, allocation fallbacks, coherent low-word/tag rollover, reuse, reentrant snapshot, ID exhaustion");
    printf ("SIZES worker=%zu peer_part=%zu identity=%zu counter=%zu\n",
            sizeof (WmWorker), sizeof (WmPeer), sizeof (Identity),
            sizeof (Counter));
    return 0;
}
