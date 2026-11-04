/* Exercise the actual registry across server sessions. The fence hook only
 * pauses a real writer after it has captured its generation and made the
 * publication sequence odd; no accounting result or snapshot is substituted. */
#include <assert.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <unistd.h>

static _Thread_local int pause_writer;
static atomic_int writer_waiting, release_writer, reader_started, reader_done;

static void
fixture_fence (memory_order order)
{
    atomic_thread_fence (order);
    if (order == memory_order_release && pause_writer) {
        pause_writer = 0;
        atomic_store (&writer_waiting, 1);
        while (!atomic_load (&release_writer))
            sched_yield ();
    }
}
#undef atomic_thread_fence
#define atomic_thread_fence fixture_fence
#include "worker_meter.c"
#undef atomic_thread_fence

static unsigned visits;
static uint64_t expected_id, rows_in, rows_out;
static void
visit (uint64_t id, const char *address, uint64_t in, uint64_t out, void *data)
{
    (void)address;
    (void)data;
    assert (id == 0 || id == expected_id);
    visits++;
    rows_in += in;
    rows_out += out;
    /* Capacity remains metadata-only, including from a snapshot callback. */
    assert (wm_snapshot (NULL, NULL, NULL, NULL) <= 2);
}

static void
check (size_t count, uint64_t in, uint64_t out)
{
    uint64_t actual_in, actual_out;
    visits = 0;
    rows_in = rows_out = 0;
    assert (wm_snapshot (NULL, NULL, NULL, NULL) == count);
    assert (wm_snapshot (visit, NULL, &actual_in, &actual_out) == count);
    assert (visits == count && rows_in == in && rows_out == out);
    assert (actual_in == in && actual_out == out);
}

static WmPeer *
peer (WmWorker *writer, const char *text)
{
    struct sockaddr_in address = { .sin_family = AF_INET };
    assert (inet_pton (AF_INET, text, &address.sin_addr) == 1);
    return wm_peer (writer, (struct sockaddr *)&address, sizeof (address));
}

static void *
paused_add (void *data)
{
    pause_writer = 1;
    wm_add (data, 1000, 2000);
    return NULL;
}

typedef struct
{
    Counter *counter;
    unsigned generation;
    uint64_t in, out;
} Read;

static void *
stale_read (void *data)
{
    Read *read = data;
    atomic_store (&reader_started, 1);
    counter_read (read->counter, read->generation, &read->in, &read->out);
    atomic_store (&reader_done, 1);
    return NULL;
}

int
main (void)
{
    alarm (10);
    WmWorker *a = wm_worker_new (), *b = wm_worker_new ();
    assert (a && b && wm_generation () == 0 && wm_session_available ());
    WmPeer *ap = peer (a, "10.20.30.40"), *bp = peer (b, "10.20.30.40");
    expected_id = ap->identity->id;
    assert (ap->identity == bp->identity);
    wm_add (ap, 11, 13);
    wm_add (wm_unknown (a), 2, 3);
    check (2, 13, 16);

    assert (wm_begin_session () == 0 && wm_generation () == 1);
    check (1, 0, 0);
    wm_add (ap, 0, 0);
    check (1, 0, 0);
    wm_add (ap, 17, 19);
    check (2, 17, 19);
    /* A registered but inactive peer from the old session must disappear. */
    peer (a, "10.20.30.41");
    check (2, 17, 19);

    unsigned sequence = atomic_load (&ap->counter.sequence);
    atomic_store (&ap->counter.sequence, sequence | 1u);
    assert (wm_snapshot (NULL, NULL, NULL, NULL) == 2);
    assert (wm_begin_session () == 0 && wm_generation () == 2);
    /* Old odd parts do not block a new generation's totals or row snapshot. */
    check (1, 0, 0);
    wm_add (bp, 23, 29);
    check (2, 23, 29);
    atomic_store (&ap->counter.sequence, sequence);

    /* First-record publication from an obsolete session must neither leak
     * bytes nor downgrade another writer's newer active identity generation. */
    assert (wm_begin_session () == 0 && wm_generation () == 3);
    pthread_t writer;
    assert (pthread_create (&writer, NULL, paused_add, ap) == 0);
    while (!atomic_load (&writer_waiting))
        sched_yield ();
    assert (wm_begin_session () == 0 && wm_generation () == 4);
    wm_add (bp, 31, 37);
    check (2, 31, 37);
    atomic_store (&release_writer, 1);
    assert (pthread_join (writer, NULL) == 0);
    assert (atomic_load (&ap->identity->generation) == 4);
    check (2, 31, 37);
    wm_add (ap, 41, 43);
    check (2, 72, 80);

    /* An already-reading old sample is released by a session transition,
     * even while its old writer remains suspended inside publication. */
    atomic_store (&writer_waiting, 0);
    atomic_store (&release_writer, 0);
    assert (pthread_create (&writer, NULL, paused_add, ap) == 0);
    while (!atomic_load (&writer_waiting))
        sched_yield ();
    Read read = { .counter = &ap->counter, .generation = 4 };
    pthread_t reader;
    assert (pthread_create (&reader, NULL, stale_read, &read) == 0);
    while (!atomic_load (&reader_started))
        sched_yield ();
    assert (!atomic_load (&reader_done));
    assert (wm_begin_session () == 0 && wm_generation () == 5);
    assert (pthread_join (reader, NULL) == 0);
    assert (read.in == 0 && read.out == 0 && atomic_load (&reader_done));
    check (1, 0, 0);
    atomic_store (&release_writer, 1);
    assert (pthread_join (writer, NULL) == 0);
    check (1, 0, 0);

    /* Retained and recycled writers lazily select the same new session. */
    wm_add (ap, 47, 53);
    wm_worker_release (b);
    WmWorker *reused = wm_worker_new ();
    assert (reused == b && peer (reused, "10.20.30.40") == bp);
    wm_add (bp, 59, 61);
    check (2, 106, 114);

    /* Finite generation exhaustion cannot alias an old session or clear the
     * final valid session; test setup jumps only the private generation clock. */
    atomic_store (&session_generation, UINT32_MAX - 1);
    assert (wm_session_available () && wm_begin_session () == 0);
    assert (wm_generation () == UINT32_MAX && !wm_session_available ());
    check (1, 0, 0);
    wm_add (ap, 67, 71);
    check (2, 67, 71);
    assert (wm_begin_session () < 0 && wm_generation () == UINT32_MAX);
    check (2, 67, 71);
    wm_worker_release (a);
    wm_worker_release (reused);
    alarm (0);
    puts (
        "PASS: session reset, old-row removal, retained/reused writers, stale publication isolation, nonblocking old odd parts, stale-reader exit, monotonic identity and generation exhaustion");
    return 0;
}
