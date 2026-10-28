#include "hev-main.h"
#include <arpa/inet.h>
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/time.h>
#include <unistd.h>

static char configuration[512];
static atomic_int server_result, observing;

static void *
run_server (void *unused)
{
    (void)unused;
    atomic_store (&server_result, hev_socks5_server_main_from_str (
                                      (const unsigned char *)configuration,
                                      (unsigned int)strlen (configuration)));
    return NULL;
}

static void *
observe (void *unused)
{
    (void)unused;
    while (atomic_load (&observing)) {
        HevSocks5ListenerInfo info;
        if (hev_socks5_server_listener_info (&info)) {
            assert (info.port && info.address[0]);
            assert (memchr (info.address, 0, sizeof (info.address)));
            assert (info.ipv6_only == 0 || info.ipv6_only == 1);
        } else {
            assert (!info.port && !info.address[0] && !info.ipv6_only);
        }
    }
    return NULL;
}

static void
connect_and_check_auth (const HevSocks5ListenerInfo *info)
{
    struct sockaddr_storage storage = { 0 };
    struct timeval timeout = { 5, 0 };
    socklen_t length;
    int family, fd;
    unsigned char request[] = { 5, 1, 2 }, reply[2];

    const char *host = !strcmp (info->address, "::ffff:0.0.0.0") ?
                           "::ffff:127.0.0.1" :
                           info->address;
    if (strchr (host, ':')) {
        struct sockaddr_in6 *address = (struct sockaddr_in6 *)&storage;
        family = AF_INET6;
        address->sin6_family = family;
        address->sin6_port = htons (info->port);
        assert (inet_pton (family, !strcmp (host, "::") ? "::1" : host,
                           &address->sin6_addr) == 1);
        length = sizeof (*address);
    } else {
        struct sockaddr_in *address = (struct sockaddr_in *)&storage;
        family = AF_INET;
        address->sin_family = family;
        address->sin_port = htons (info->port);
        assert (inet_pton (family,
                           !strcmp (info->address, "0.0.0.0") ? "127.0.0.1" :
                                                                info->address,
                           &address->sin_addr) == 1);
        length = sizeof (*address);
    }
    fd = socket (family, SOCK_STREAM, 0);
    assert (fd >= 0);
    assert (
        !setsockopt (fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof (timeout)));
    assert (!connect (fd, (struct sockaddr *)&storage, length));
    assert (write (fd, request, sizeof (request)) == (ssize_t)sizeof (request));
    assert (recv (fd, reply, sizeof (reply), MSG_WAITALL) ==
            (ssize_t)sizeof (reply));
    assert (reply[0] == 5 && reply[1] == 2);
    close (fd);
}

static void
check_run (const char *host, int workers, int ipv6_only)
{
    pthread_t server;
    HevSocks5ListenerInfo info;
    int ready = 0;

    assert (!hev_socks5_server_listener_info (&info));
    snprintf (configuration, sizeof (configuration),
              "main:\n  workers: %d\n  port: 0\n  udp-port: 0\n"
              "  listen-address: '%s'\n  listen-ipv6-only: %s\n"
              "auth:\n  username: echo\n  password: client\n",
              workers, host, ipv6_only ? "true" : "false");
    hev_socks5_server_prepare ();
    atomic_store (&server_result, -999);
    assert (!pthread_create (&server, NULL, run_server, NULL));
    for (int i = 0; i < 5000; ++i) {
        ready = hev_socks5_server_listener_info (&info);
        if (ready || atomic_load (&server_result) != -999)
            break;
        usleep (1000);
    }
    const char *actual =
        !strncmp (info.address, "::ffff:", 7) ? info.address + 7 : info.address;
    const char *expected = !strncmp (host, "::ffff:", 7) ? host + 7 : host;
    if (!ready || strcmp (actual, expected))
        fprintf (stderr,
                 "listener host=%s workers=%d ready=%d actual=%s result=%d\n",
                 host, workers, ready, info.address,
                 atomic_load (&server_result));
    assert (ready && !strcmp (actual, expected));
    assert (info.ipv6_only == ipv6_only);
    connect_and_check_auth (&info);
    hev_socks5_server_quit ();
    assert (!hev_socks5_server_listener_info (&info));
    assert (!pthread_join (server, NULL));
    assert (atomic_load (&server_result) == 0);
    assert (!hev_socks5_server_listener_info (&info));
    /* A late idle Stop must be cleared only by the next explicit prepare. */
    hev_socks5_server_quit ();
}

static void
check_cancelled_start (int workers)
{
    HevSocks5ListenerInfo info;
    snprintf (
        configuration, sizeof (configuration),
        "main:\n  workers: %d\n  port: 0\n  listen-address: '127.0.0.1'\n",
        workers);
    for (int i = 0; i < 20; ++i) {
        hev_socks5_server_prepare ();
        hev_socks5_server_quit ();
        assert (hev_socks5_server_main_from_str (
                    (const unsigned char *)configuration,
                    strlen (configuration)) == 0);
        assert (!hev_socks5_server_listener_info (&info));
    }
}

int
main (void)
{
    pthread_t reader;
    int fd = socket (AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        perror ("Listener test requires real TCP sockets");
        return 2;
    }
    close (fd);
    assert (!hev_socks5_server_listener_info (NULL));
    alarm (30);
    check_cancelled_start (1);
    check_cancelled_start (4);
    atomic_store (&observing, 1);
    assert (!pthread_create (&reader, NULL, observe, NULL));
    for (int i = 0; i < 3; ++i) {
        check_run ("127.0.0.1", 1, 0);
        check_run ("0.0.0.0", 2, 0);
        check_run ("::ffff:0.0.0.0", 2, 0);
        check_run ("::1", 1, 1);
        check_run ("::", 2, 0);
    }
    atomic_store (&observing, 0);
    assert (!pthread_join (reader, NULL));
    puts (
        "PASS: real ephemeral listeners, authentication readiness, concurrent "
        "snapshots, 40 cancelled starts and repeated Stop/restart");
    return 0;
}
