/* Linux test only: hold construction after real accept until the peer's real
 * RST invalidates getpeername. No read/write result or counter is mocked. */
#define _GNU_SOURCE
#include <assert.h>
#include <arpa/inet.h>
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>
#include "hev-main.h"
#include "hev-socks5-session.h"

static atomic_int reset_seen;
static int reset_errno, server_result;
static char config[256];

HevSocks5Session *__real_hev_socks5_session_new (int fd);
HevSocks5Session *
__wrap_hev_socks5_session_new (int fd)
{
    struct sockaddr_storage peer;
    for (int i = 0; i < 2000; ++i) {
        socklen_t length = sizeof (peer);
        if (getpeername (fd, (struct sockaddr *)&peer, &length) < 0) {
            reset_errno = errno;
            atomic_store (&reset_seen, 1);
            return __real_hev_socks5_session_new (fd);
        }
        usleep (1000);
    }
    fputs ("No real reset observed before construction\n", stderr);
    abort ();
}

static void *
server (void *unused)
{
    (void)unused;
    server_result = hev_socks5_server_main_from_str (
        (unsigned char *)config, (unsigned int)strlen (config));
    return NULL;
}

int
main (int argc, char **argv)
{
    int workers = argc > 1 ? atoi (argv[1]) : 4;
    int family = argc > 2 && !strcmp (argv[2], "6") ? AF_INET6 : AF_INET;
    struct sockaddr_in listen = { .sin_family = AF_INET,
                                  .sin_addr.s_addr = htonl (INADDR_LOOPBACK) };
    struct sockaddr_in6 wildcard = { .sin6_family = AF_INET6 };
    socklen_t length = sizeof (wildcard);
    int reserve = socket (AF_INET6, SOCK_STREAM, 0), zero = 0;
    assert (reserve >= 0);
    assert (
        !setsockopt (reserve, IPPROTO_IPV6, IPV6_V6ONLY, &zero, sizeof (zero)));
    assert (!bind (reserve, (void *)&wildcard, length));
    assert (!getsockname (reserve, (void *)&wildcard, &length));
    int port = ntohs (wildcard.sin6_port);
    listen.sin_port = htons (port);
    close (reserve);
    snprintf (config, sizeof (config),
              "main:\n  workers: %d\n  listen-address: '::'\n  port: %d\n"
              "  bind-address-v4: ''\n  bind-address-v6: ''\n",
              workers, port);
    pthread_t thread;
    assert (!pthread_create (&thread, NULL, server, NULL));
    int client = -1;
    for (int i = 0; i < 2000; ++i) {
        int fd = socket (family, SOCK_STREAM, 0);
        assert (fd >= 0);
        int result;
        if (family == AF_INET) {
            struct sockaddr_in local = { .sin_family = AF_INET };
            assert (inet_pton (AF_INET, "127.0.0.2", &local.sin_addr) == 1);
            assert (!bind (fd, (void *)&local, sizeof (local)));
            result = connect (fd, (void *)&listen, sizeof (listen));
        } else {
            struct sockaddr_in6 local = { .sin6_family = AF_INET6 };
            local.sin6_addr = in6addr_loopback;
            assert (!bind (fd, (void *)&local, sizeof (local)));
            local.sin6_port = htons (port);
            result = connect (fd, (void *)&local, sizeof (local));
        }
        if (!result) {
            client = fd;
            break;
        }
        assert (errno == ECONNREFUSED);
        close (fd);
        usleep (1000);
    }
    assert (client >= 0);
    assert (send (client, "\x05\x01\x00", 3, 0) == 3);
    struct linger linger = { .l_onoff = 1, .l_linger = 0 };
    assert (
        !setsockopt (client, SOL_SOCKET, SO_LINGER, &linger, sizeof (linger)));
    close (client);
    uint64_t in = 0, out = 0;
    for (int i = 0; i < 2000; ++i) {
        hev_socks5_server_endpoint_stats (&in, &out);
        if (atomic_load (&reset_seen) && out == 3)
            break;
        usleep (1000);
    }
    hev_socks5_server_quit ();
    assert (!pthread_join (thread, NULL));
    assert (!server_result && atomic_load (&reset_seen));
    hev_socks5_server_endpoint_stats (&in, &out);
    size_t count = hev_socks5_server_endpoint_rows (NULL, 0);
    HevSocks5EndpointStats *rows = calloc (count, sizeof (*rows));
    assert (rows && hev_socks5_server_endpoint_rows (rows, count) == count);
    uint64_t peer_out = 0, unknown_out = 0;
    const char *ip = family == AF_INET ? "127.0.0.2" : "::1";
    for (size_t i = 0; i < count; ++i) {
        if (!strcmp (rows[i].address, ip))
            peer_out += rows[i].sent;
        if (rows[i].id == 0)
            unknown_out += rows[i].sent;
    }
    free (rows);
    printf ("{\"workers\":%d,\"ip\":\"%s\",\"getpeername_errno\":%d,"
            "\"total_out\":%" PRIu64 ",\"peer_out\":%" PRIu64
            ",\"unattributed_out\":%" PRIu64 "}\n",
            workers, ip, reset_errno, out, peer_out, unknown_out);
    return out == 3 && peer_out == 3 && unknown_out == 0 ? 0 : 1;
}
