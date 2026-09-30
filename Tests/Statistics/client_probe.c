/* Exercise the actual registry, replacing only peer lookup/allocation failures. */
#include <assert.h>
#include <arpa/inet.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <sys/socket.h>

static atomic_int fail_allocation;
static atomic_int peer_calls;
static int test_peer (int fd, struct sockaddr *address, socklen_t *length);
static void *test_calloc (size_t count, size_t size);
#define getpeername test_peer
#define calloc test_calloc
#include "hev-socks5-misc.c"
#undef getpeername
#undef calloc
#include "hev-main.h"

static void *
test_calloc (size_t count, size_t size)
{
    return atomic_load (&fail_allocation) ? NULL : calloc (count, size);
}

static int
test_peer (int fd, struct sockaddr *address, socklen_t *length)
{
    struct sockaddr_in6 v6 = { 0 };
    struct sockaddr_in v4 = { 0 };

    atomic_fetch_add (&peer_calls, 1);
    if (fd == -1)
        return -1;
    if (fd == 1 || fd == 7) {
        v4.sin_family = AF_INET;
        v4.sin_port = htons (40000 + fd);
        assert (inet_pton (AF_INET, fd == 1 ? "10.0.0.1" : "10.0.0.2",
                           &v4.sin_addr) == 1);
        assert (*length >= sizeof (v4));
        memcpy (address, &v4, sizeof (v4));
        *length = sizeof (v4);
    } else {
        v6.sin6_family = AF_INET6;
        v6.sin6_port = htons (30000 + fd);
        assert (inet_pton (AF_INET6, fd == 2 ? "::ffff:10.0.0.1" : "::1",
                           &v6.sin6_addr) == 1);
        if (fd == 4 || fd == 5) {
            assert (inet_pton (AF_INET6, "fe80::1", &v6.sin6_addr) == 1);
            v6.sin6_scope_id = fd;
        }
        if (fd >= 100) {
            v6.sin6_addr.s6_addr[0] = 0x20;
            v6.sin6_addr.s6_addr[1] = 1;
            v6.sin6_addr.s6_addr[14] = fd >> 8;
            v6.sin6_addr.s6_addr[15] = fd;
        }
        assert (*length >= sizeof (v6));
        memcpy (address, &v6, sizeof (v6));
        *length = fd == 6 ? 1 : sizeof (v6);
    }
    return 0;
}

static atomic_int finished;
static void *
writer (void *data)
{
    int n = (int)(intptr_t)data;
    void *client = hev_socks5_transfer_client (n & 1 ? 1 : 7);
    for (int i = 0; i < 10000; i++)
        hev_socks5_transfer_add (3, 7, client);
    /* Concurrent registration, including duplicate keys across workers. */
    for (int i = 100; i < 132; i++)
        hev_socks5_transfer_add (1, 2, hev_socks5_transfer_client (i));
    atomic_fetch_add (&finished, 1);
    return NULL;
}

static void
reentrant_reader (uint64_t id, const char *address, uint64_t received,
                  uint64_t sent, void *data)
{
    (void)address;
    (void)received;
    (void)sent;
    (*(size_t *)data)++;
    if (id == 0)
        assert (hev_socks5_transfer_client (999) != NULL);
}

int
main (void)
{
    HevSocks5ClientStats rows[256];
    pthread_t threads[8];
    uint64_t received, sent, sum_in = 0, sum_out = 0;
    size_t count, visits = 0;
    void *a = hev_socks5_transfer_client (1);
    void *b = hev_socks5_transfer_client (2);
    int queries;

    assert (a && a == b);
    assert (hev_socks5_transfer_client (3) != a);
    assert (hev_socks5_transfer_client (4) != hev_socks5_transfer_client (5));
    assert (!hev_socks5_transfer_client (-1));
    assert (!hev_socks5_transfer_client (6));
    atomic_store (&fail_allocation, 1);
    assert (!hev_socks5_transfer_client (700));
    assert (hev_socks5_transfer_client (2) == a);
    atomic_store (&fail_allocation, 0);
    queries = atomic_load (&peer_calls);
    hev_socks5_transfer_add (17, 29, a);
    hev_socks5_transfer_add (11, 13, NULL);
    assert (atomic_load (&peer_calls) == queries);
    count = hev_socks5_server_client_stats (NULL, 999);
    assert (count == 5);
    memset (rows, 0xa5, sizeof (rows));
    assert (hev_socks5_server_client_stats (rows, 0) == count);
    assert (rows[0].id == UINT64_C (0xa5a5a5a5a5a5a5a5));
    assert (hev_socks5_server_client_stats (rows, 2) == count);
    assert (rows[0].id == 0 && rows[0].received == 11 && rows[0].sent == 13);
    assert (!strcmp (rows[1].address, "10.0.0.1") && rows[1].received == 17);
    assert (rows[2].id == UINT64_C (0xa5a5a5a5a5a5a5a5));
    assert (hev_socks5_server_client_stats (rows, 256) == count);
    assert (!strcmp (rows[3].address, "fe80::1%4"));
    assert (!strcmp (rows[4].address, "fe80::1%5"));
    assert (hev_socks5_transfer_clients (reentrant_reader, &visits) == count);
    assert (visits == count &&
            hev_socks5_server_client_stats (NULL, 0) == count + 1);
    puts (
        "PASS: mapped normalization, scope, unknown/failure fallback, no hot-path lookup, bounded snapshot writes and unlocked callback");

    for (intptr_t i = 0; i < 8; i++)
        assert (!pthread_create (&threads[i], NULL, writer, (void *)i));
    while (atomic_load (&finished) < 8) {
        count = hev_socks5_server_client_stats (rows, 256);
        assert (count <= 256);
        for (size_t i = 0; i < count; i++) {
            assert (rows[i].id == i);
            assert (memchr (rows[i].address, 0, sizeof (rows[i].address)));
        }
    }
    for (int i = 0; i < 8; i++)
        assert (!pthread_join (threads[i], NULL));
    count = hev_socks5_server_client_stats (rows, 256);
    assert (count == 39);
    for (size_t i = 0; i < count; i++) {
        sum_in += rows[i].received;
        sum_out += rows[i].sent;
    }
    hev_socks5_transfer_get (&received, &sent);
    assert (received == 28 + 80000 * 3 + 8 * 32);
    assert (sent == 42 + 80000 * 7 + 8 * 64);
    assert (received == sum_in && sent == sum_out);
    assert (rows[1].received == 17 + 40000 * 3);
    assert (rows[1].sent == 29 + 40000 * 7);
    puts (
        "PASS: concurrent registration/snapshot/8 writers, unique IDs, per-IP attribution and quiescent aggregate equality");
    return 0;
}
