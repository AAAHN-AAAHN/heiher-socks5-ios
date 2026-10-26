/* Real ICMP clients share the production worker's existing IP counters. */
#include <arpa/inet.h>
#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include "hev-main.h"
#include "hev-icmp-engine.h"

typedef struct {
    atomic_int sent;
    atomic_int replied;
    size_t length;
    uint16_t identifier;
    uint16_t sequence;
} Reply;

static uint64_t accepted[2], consumed[2];

static void
observe (const struct sockaddr *peer, socklen_t length, size_t bytes,
         int writing, void *context)
{
    int family = peer->sa_family == AF_INET6;
    assert (peer->sa_family == AF_INET || peer->sa_family == AF_INET6);
    assert (bytes > 0);
    (writing ? accepted : consumed)[family] += bytes;
    hev_socks5_server_record_socket_io (peer, length, bytes, writing, context);
}

static void
reply (const HevSocks5IcmpResult *result, void *context)
{
    Reply *value = context;
    assert (result->event != HEV_SOCKS5_ICMP_ERROR);
    assert (result->echo_len == value->length);
    if (result->event == HEV_SOCKS5_ICMP_SENT) {
        atomic_store (&value->sent, 1);
        return;
    }
    assert (result->event == HEV_SOCKS5_ICMP_REPLY);
    assert (((result->echo[4] << 8) | result->echo[5]) == value->identifier);
    assert (((result->echo[6] << 8) | result->echo[7]) == value->sequence);
    atomic_store (&value->replied, 1);
}

static void *
serve (void *unused)
{
    static const unsigned char config[] =
        "main:\n  workers: 2\n  port: 0\n  listen-address: 127.0.0.1\n"
        "misc:\n  log-level: error\n";
    (void)unused;
    assert (hev_socks5_server_main_from_str (config, sizeof (config) - 1) == 0);
    return NULL;
}

static void
check_totals (unsigned int rounds)
{
    HevSocks5EndpointStats rows[8];
    uint64_t received, sent;
    unsigned int seen = 0;
    size_t count = hev_socks5_server_endpoint_rows (rows, 8);
    assert (count == 3);
    for (size_t i = 0; i < count; i++) {
        int family;
        if (rows[i].id == 0) {
            assert (!strcmp (rows[i].address, "Unattributed"));
            assert (rows[i].received == 0 && rows[i].sent == 0);
            seen |= 4;
            continue;
        }
        if (!strcmp (rows[i].address, "127.0.0.1"))
            family = 0;
        else {
            assert (!strcmp (rows[i].address, "::1"));
            family = 1;
        }
        assert (!(seen & (1u << family)));
        seen |= 1u << family;
        assert (rows[i].received == accepted[family]);
        assert (rows[i].sent == consumed[family]);
        assert (rows[i].received == (family ? 8 : 21) * rounds);
        assert (rows[i].sent >= rows[i].received);
        printf ("%s: accepted=%" PRIu64 ", consumed=%" PRIu64 "\n",
                rows[i].address, rows[i].received, rows[i].sent);
    }
    assert (seen == 7);
    hev_socks5_server_endpoint_stats (&received, &sent);
    assert (received == accepted[0] + accepted[1]);
    assert (sent == consumed[0] + consumed[1]);
    assert (received == 29 * rounds);
}

int
main (void)
{
    struct sockaddr_in destination = { .sin_family = AF_INET };
    struct sockaddr_in source = { .sin_family = AF_INET };
    struct sockaddr_in6 destination6 = { .sin6_family = AF_INET6 };
    unsigned char echo[13] = { 8, 0, 0, 0, 0x12, 0x34, 0, 7, 1, 2, 3, 4, 5 };
    uint16_t checksum = hev_icmp_checksum (echo, sizeof (echo));
    echo[2] = checksum >> 8;
    echo[3] = checksum;
    assert (inet_pton (AF_INET, "127.0.0.1", &destination.sin_addr) == 1);
    assert (inet_pton (AF_INET, "192.0.2.15", &source.sin_addr) == 1);
    assert (inet_pton (AF_INET6, "::1", &destination6.sin6_addr) == 1);
    assert (!hev_socks5_server_icmp_set_io_observer (observe, NULL));
    for (unsigned int round = 1; round <= 3; round++) {
        pthread_t thread;
        uint64_t generation = 0;
        Reply replies[3] = {
            { .length = 8, .identifier = 0, .sequence = 1 },
            { .length = sizeof (echo), .identifier = 0x1234, .sequence = 7 },
            { .length = 8, .identifier = 0, .sequence = 3 },
        };
        HevSocks5IcmpClient *clients[3];
        hev_socks5_server_prepare ();
        assert (!pthread_create (&thread, NULL, serve, NULL));
        for (int i = 0; i < 5000 && !generation; i++) {
            generation = hev_socks5_server_icmp_generation ();
            usleep (1000);
        }
        assert (generation);
        for (int i = 0; i < 3; i++) {
            clients[i] = hev_socks5_server_icmp_client_new (generation, reply, &replies[i]);
            assert (clients[i]);
        }
        /* Creating clients and passing return metadata perform no socket I/O.
         * The origin metadata must not become fictitious client network bytes. */
        uint64_t before_in, before_out;
        hev_socks5_server_endpoint_stats (&before_in, &before_out);
        assert (before_in == 29 * (round - 1));
        assert (before_in == accepted[0] + accepted[1]);
        assert (before_out == consumed[0] + consumed[1]);
        assert (!hev_socks5_server_icmp_ping (clients[0], 1, (void *)&destination,
                                             sizeof (destination), 2000));
        assert (!hev_socks5_server_icmp_submit (clients[1], 2, (void *)&source,
                                               sizeof (source), (void *)&destination,
                                               sizeof (destination), echo, sizeof (echo), 2000));
        assert (!hev_socks5_server_icmp_ping (clients[2], 3, (void *)&destination6,
                                             sizeof (destination6), 2000));
        for (int i = 0; i < 3; i++) {
            for (int wait = 0; wait < 5000 && !atomic_load (&replies[i].replied); wait++)
                usleep (1000);
            assert (atomic_load (&replies[i].sent) && atomic_load (&replies[i].replied));
            hev_socks5_server_icmp_client_free (clients[i]);
        }
        hev_socks5_server_quit ();
        assert (!pthread_join (thread, NULL));
        assert (!hev_socks5_server_icmp_generation ());
        check_totals (round);
    }
    puts ("PASS: real internal/full-message clients, uniform IPv4/IPv6 OS bytes, zero API bytes, worker ownership and three retained-count restarts");
    return 0;
}
