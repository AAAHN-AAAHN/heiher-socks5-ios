/* The real server connect path, with a deterministic connect normalization.
 * A genuine loopback socket confirms its peer; no platform wildcard assumption. */
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <arpa/inet.h>
#include "hev-socks5-meter.h"
int fixture_socket (int type);
int fixture_connect (int fd, const struct sockaddr *address, socklen_t length,
                     HevTaskIOYielder yielder, void *context);
static int peer_lookup_fails;
static void *
fixture_peer (int fd)
{
    return peer_lookup_fails ? NULL : hev_meter_fd (fd);
}
#define hev_socks5_socket fixture_socket
#define hev_task_io_socket_connect fixture_connect
#define hev_meter_fd fixture_peer
#include "hev-socks5-server.c"
#undef hev_meter_fd
#undef hev_task_io_socket_connect
#undef hev_socks5_socket

int
fixture_socket (int type)
{
    return socket (AF_INET6, type, 0);
}

int
fixture_connect (int fd, const struct sockaddr *address, socklen_t length,
                 HevTaskIOYielder yielder, void *context)
{
    (void)yielder;
    (void)context;
    assert (length == sizeof (struct sockaddr_in6));
    struct sockaddr_in6 normalized = *(const struct sockaddr_in6 *)address;
    if (IN6_IS_ADDR_UNSPECIFIED (&normalized.sin6_addr))
        normalized.sin6_addr = in6addr_loopback;
    assert (IN6_IS_ADDR_LOOPBACK (&normalized.sin6_addr));
    int result = connect (fd, (const struct sockaddr *)&normalized, length);
    assert (result == 0);
    errno = EALREADY;
    return result;
}

static int
binder (HevSocks5 *self, int fd, const struct sockaddr *address)
{
    (void)self;
    (void)fd;
    (void)address;
    return 0;
}

static void
check_row (uint64_t id, const char *address, uint64_t in, uint64_t out,
           void *context)
{
    unsigned *found = context;
    if (!strcmp (address, "::1")) {
        assert (id != 0 && in == 46 && out == 34);
        ++*found;
    } else {
        assert (id == 0 && in == 23 && out == 17);
    }
}

int
main (void)
{
    assert (hev_meter_prepare () == 0 && hev_meter_worker_enter () == 0);
    int listener = socket (AF_INET6, SOCK_STREAM, 0);
    assert (listener >= 0);
    struct sockaddr_in6 address = { 0 };
    address.sin6_family = AF_INET6;
    address.sin6_addr = in6addr_loopback;
    assert (bind (listener, (const struct sockaddr *)&address,
                  sizeof address) == 0);
    assert (listen (listener, 1) == 0);
    socklen_t length = sizeof address;
    assert (getsockname (listener, (struct sockaddr *)&address, &length) == 0);
    for (unsigned test = 0; test < 3; test++) {
        /* Real peer available; concrete fallback; unspecified fallback. */
        peer_lookup_fails = test != 0;
        address.sin6_addr = test == 1 ? in6addr_loopback : in6addr_any;
        HevSocks5Server self = { 0 };
        HevSocks5Class klass = { 0 };
        klass.binder = binder;
        HEV_OBJECT (&self)->klass = HEV_OBJECT_CLASS (&klass);
        HEV_SOCKS5 (&self)->timeout = -1;
        assert (hev_socks5_server_connect (&self, &address) == 0);
        assert (errno == EALREADY);
        assert (!!IN6_IS_ADDR_LOOPBACK (&address.sin6_addr) == (test == 1));
        int accepted = accept (listener, NULL, NULL);
        assert (accepted >= 0);
        struct sockaddr_in6 actual;
        length = sizeof actual;
        assert (getpeername (self.fds[0], (struct sockaddr *)&actual,
                             &length) == 0);
        assert (IN6_IS_ADDR_LOOPBACK (&actual.sin6_addr));
        void *expected = test == 2 ? hev_meter_peer (NULL, 0) :
                                     hev_meter_fd (self.fds[0]);
        assert (HEV_SOCKS5 (&self)->io_destination == expected);
        hev_meter_add (HEV_SOCKS5 (&self)->io_destination, 23, 17);
        close (accepted);
        close (self.fds[0]);
    }
    unsigned found = 0;
    hev_meter_rows (check_row, &found);
    assert (found == 1);
    close (listener);
    hev_meter_worker_leave ();
    puts (
        "PASS: actual connected peer, concrete/unspecified lookup fallbacks, unchanged request and errno");
    return 0;
}
