/* The public observer shares peer identity and worker counters with all I/O. */
#include <arpa/inet.h>
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "hev-main.h"
#include "hev-socks5-meter.h"

static HevSocks5EndpointStats
row (const char *address)
{
    HevSocks5EndpointStats rows[8];
    size_t count = hev_socks5_server_endpoint_rows (rows, 8);

    assert (count <= 8);
    for (size_t i = 0; i < count; i++)
        if (!strcmp (rows[i].address, address))
            return rows[i];
    assert (!"Missing endpoint row");
    return (HevSocks5EndpointStats){ 0 };
}

int
main (void)
{
    struct sockaddr_in peer = { .sin_family = AF_INET };
    struct sockaddr_in6 mapped = { .sin6_family = AF_INET6 };
    struct sockaddr_in6 scoped = { .sin6_family = AF_INET6,
                                   .sin6_scope_id = 3 };
    HevSocks5EndpointStats value;
    uint64_t received, sent;

    assert (!hev_meter_prepare () && !hev_meter_worker_enter ());
    assert (inet_pton (AF_INET, "192.0.2.9", &peer.sin_addr) == 1);
    assert (inet_pton (AF_INET6, "::ffff:192.0.2.9", &mapped.sin6_addr) == 1);
    assert (inet_pton (AF_INET6, "fe80::1", &scoped.sin6_addr) == 1);
    size_t initial = hev_socks5_server_endpoint_rows (NULL, 0);
    errno = EINTR;
    hev_socks5_server_record_socket_io ((void *)&peer, sizeof (peer), 0, 1,
                                        NULL);
    assert (errno == EINTR);
    assert (hev_socks5_server_endpoint_rows (NULL, 0) == initial);

    /* Header/payload parsing is irrelevant: record exactly the supplied OS
     * completion. A caller's later cancellation cannot erase these bytes. */
    hev_socks5_server_record_socket_io ((void *)&peer, sizeof (peer), 40, 1,
                                        NULL);
    hev_socks5_server_record_socket_io ((void *)&mapped, sizeof (mapped), 40, 0,
                                        NULL);
    hev_socks5_server_record_socket_io ((void *)&peer, sizeof (peer), 28, 0,
                                        NULL);
    assert (errno == EINTR);
    value = row ("192.0.2.9");
    assert (value.received == 40 && value.sent == 68);

    hev_socks5_server_record_socket_io ((void *)&scoped, sizeof (scoped), 8, 1,
                                        NULL);
    scoped.sin6_scope_id = 4;
    hev_socks5_server_record_socket_io ((void *)&scoped, sizeof (scoped), 8, 0,
                                        NULL);
    assert (row ("fe80::1%3").received == 8);
    assert (row ("fe80::1%4").sent == 8);
    hev_socks5_server_record_socket_io (NULL, 0, 3, 0, NULL);
    hev_socks5_server_endpoint_stats (&received, &sent);
    assert (received == 48 && sent == 79);
    hev_meter_worker_leave ();
    hev_socks5_server_endpoint_stats (&received, &sent);
    assert (received == 48 && sent == 79);
    puts (
        "PASS: generic socket observer shares identity, direction, exact lengths, scope, unknown and process totals");
    return 0;
}
