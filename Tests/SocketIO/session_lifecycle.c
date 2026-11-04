/* The real proxy/main lifecycle, native sockets/tasks and public writer ABI.
 * Observe worker start only to stop an otherwise real server deterministically.
 * Direct generation setup is confined to the finite-exhaustion boundary. */
#include <assert.h>
#include <arpa/inet.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include "hev-main.h"
#include "hev-socks5-worker.h"
#include "core/src/worker_meter.c"

static pthread_t controller;
static void *writer;
static uint32_t expected_generation;
static int starts;
static void fixture_worker_start (HevSocks5Worker *);

#define hev_socks5_worker_start fixture_worker_start
#include "hev-socks5-proxy.c"
#undef hev_socks5_worker_start

static void
record (const char *text, size_t in, size_t out)
{
    struct sockaddr_in address = { .sin_family = AF_INET };
    assert (inet_pton (AF_INET, text, &address.sin_addr) == 1);
    hev_socks5_server_io_writer_record (
        writer, (struct sockaddr *)&address, sizeof (address), in, out);
}

static void
check (uint32_t generation, uint64_t in, uint64_t out, const char *peer)
{
    uint64_t actual_in, actual_out;
    HevSocks5EndpointStats rows[4];
    assert (hev_socks5_server_endpoint_generation () == generation);
    hev_socks5_server_endpoint_stats (&actual_in, &actual_out);
    assert (actual_in == in && actual_out == out);
    size_t count = hev_socks5_server_endpoint_rows (rows, 4);
    assert (count == (peer ? 2u : 1u));
    for (size_t i = 0; i < count; ++i) {
        if (rows[i].id == 0) {
            assert (!strcmp (rows[i].address, "Unattributed"));
            assert (rows[i].received == 0 && rows[i].sent == 0);
        } else {
            assert (peer && !strcmp (rows[i].address, peer));
            assert (rows[i].received == in && rows[i].sent == out);
        }
    }
}

static void
fixture_worker_start (HevSocks5Worker *worker)
{
    int main_worker = pthread_equal (pthread_self (), controller);
    if (main_worker) {
        starts++;
        check (expected_generation, 0, 0, NULL);
        /* The same explicit writer survives every restart; previous peer rows
         * are absent, and its first new record cannot inherit old volumes. */
        record ("192.0.2.11", 17, 19);
    }
    hev_socks5_worker_start (worker);
    if (main_worker)
        hev_socks5_server_quit ();
}

static int
run (int workers, unsigned port, int should_start)
{
    unsigned char configuration[256];
    int length = snprintf ((char *)configuration, sizeof (configuration),
                           "main:\n  workers: %d\n  port: %u\n"
                           "  listen-address: '127.0.0.1'\n  udp-port: 0\n"
                           "misc:\n  log-file: null\n",
                           workers, port);
    assert (length > 0 && (size_t)length < sizeof (configuration));
    expected_generation = hev_socks5_server_endpoint_generation ();
    if (should_start)
        expected_generation++;
    starts = 0;
    alarm (5);
    int result = hev_socks5_server_main_from_str (configuration, length);
    alarm (0);
    assert (starts == should_start && worker_list == NULL);
    assert (!(atomic_load (&tsync) & (SYNC_SEND | SYNC_WAIT | SYNC_STOP)));
    return result;
}

int
main (void)
{
    controller = pthread_self ();
    writer = hev_socks5_server_io_writer_new ();
    assert (writer);
    record ("192.0.2.10", 11, 13);
    check (0, 11, 13, "192.0.2.10");
    hev_socks5_server_prepare ();
    check (0, 11, 13, "192.0.2.10");

    /* Occupy a real TCP listener so init fails at bind, after meter prepare. */
    int occupied = socket (AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in address = { .sin_family = AF_INET };
    address.sin_addr.s_addr = htonl (INADDR_LOOPBACK);
    socklen_t length = sizeof (address);
    assert (occupied >= 0 && bind (occupied, (struct sockaddr *)&address,
                                   sizeof (address)) == 0);
    assert (listen (occupied, 1) == 0);
    assert (getsockname (occupied, (struct sockaddr *)&address, &length) == 0);
    assert (run (4, ntohs (address.sin_port), 0) < 0);
    check (0, 11, 13, "192.0.2.10");

    hev_socks5_server_quit ();
    assert (run (4, 0, 0) == 0);
    check (0, 11, 13, "192.0.2.10");
    for (int workers = 1; workers <= 4; workers *= 4) {
        uint32_t before = hev_socks5_server_endpoint_generation ();
        assert (run (workers, 0, 1) == 0);
        check (before + 1, 17, 19, "192.0.2.11");
        hev_socks5_server_prepare ();
        check (before + 1, 17, 19, "192.0.2.11");
        hev_socks5_server_quit ();
        assert (run (workers, 0, 0) == 0);
        check (before + 1, 17, 19, "192.0.2.11");
        assert (run (workers, ntohs (address.sin_port), 0) < 0);
        check (before + 1, 17, 19, "192.0.2.11");
    }
    close (occupied);

    atomic_store (&session_generation, UINT32_MAX - 1);
    assert (run (4, 0, 1) == 0);
    check (UINT32_MAX, 17, 19, "192.0.2.11");
    assert (run (4, 0, 0) < 0);
    check (UINT32_MAX, 17, 19, "192.0.2.11");
    /* Even an internal caller that bypassed init cannot wrap the run clock or
     * release workers through SYNC_CONT when no new generation is available. */
    atomic_store (&tsync, 0);
    hev_socks5_proxy_run ();
    assert (atomic_load (&tsync) == SYNC_ABRT);
    check (UINT32_MAX, 17, 19, "192.0.2.11");
    hev_socks5_server_io_writer_free (writer);
    puts (
        "PASS: real native starts reset exactly once; prepare/bind failure/pre-start Stop retain; live explicit writer and old-row reset; generation exhaustion fails init and aborts run without wrap");
    return 0;
}
