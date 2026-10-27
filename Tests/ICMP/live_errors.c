/* Real loopback ICMP errors delivered to the unprivileged production engine.
 * The fixture consumes the automatic Echo Reply before a separate privileged
 * injector sends a related error. Only sendto is wrapped; all engine reads,
 * socket setup, matching and completion use actual OS operations. */
#define _GNU_SOURCE
#ifdef __APPLE__
#define __APPLE_USE_RFC_3542
#endif
#include <arpa/inet.h>
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <poll.h>
#include <spawn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
#include "hev-task.h"
#include "hev-task-system.h"
#include "hev-icmp-engine.h"

extern char **environ;
static char program[PATH_MAX];

typedef struct
{
    int fd[2];
    int done, error, origin, type, code, parameter_code, local_family;
    uint32_t info;
    size_t written, received, fixture_drained;
} Live;
static Live *current;

static void
put16 (unsigned char *p, unsigned int n)
{
    p[0] = n >> 8;
    p[1] = n;
}

static uint16_t
checksum (const unsigned char *p, size_t len, int v6)
{
    /* Both IPv6 addresses are ::1. The pseudo-header contributes two ones,
     * the upper-layer length and the ICMPv6 next-header number. */
    uint32_t sum = v6 ? 2 + len + IPPROTO_ICMPV6 : 0;
    for (size_t i = 0; i < len; i++)
        sum += (uint32_t)p[i] << ((i & 1) ? 0 : 8);
    while (sum >> 16)
        sum = (sum & 65535) + (sum >> 16);
    return ~sum;
}

static socklen_t
loopback (struct sockaddr_storage *address, int v6, uint16_t identifier)
{
    memset (address, 0, sizeof (*address));
    if (v6) {
        struct sockaddr_in6 *a = (void *)address;
        a->sin6_family = AF_INET6;
        a->sin6_addr = in6addr_loopback;
#ifdef __APPLE__
        a->sin6_len = sizeof (*a);
#else
        a->sin6_port = htons (identifier);
#endif
        return sizeof (*a);
    }
    struct sockaddr_in *a = (void *)address;
    a->sin_family = AF_INET;
    a->sin_addr.s_addr = htonl (INADDR_LOOPBACK);
#ifdef __APPLE__
    a->sin_len = sizeof (*a);
    (void)identifier;
#else
    a->sin_port = htons (identifier);
#endif
    return sizeof (*a);
}

static int
raw_socket (int v6)
{
    struct sockaddr_storage address;
    socklen_t len = loopback (&address, v6, 0);
    int fd = socket (v6 ? AF_INET6 : AF_INET, SOCK_RAW,
                     v6 ? IPPROTO_ICMPV6 : IPPROTO_ICMP);
    if (fd < 0 || bind (fd, (void *)&address, len)) {
        perror ("raw injector socket/bind");
        if (fd >= 0)
            close (fd);
        return -1;
    }
    return fd;
}

static int
inject (int v6, int parameter_code)
{
    unsigned char echo[237], packet[264] = { 0 };
    struct sockaddr_storage destination;
    size_t echo_len = parameter_code >= 0 ? 236 : 24;
    size_t count = 0, len = 8 + (v6 ? 40 : 20) + echo_len;
    ssize_t n;
    int fd;
    for (;;) {
        n = read (STDIN_FILENO, echo + count, sizeof (echo) - count);
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0)
            break;
        count += n;
        if (count == sizeof (echo))
            break;
    }
    if (n < 0 || count != echo_len || echo[0] != (v6 ? 128 : 8) || echo[1])
        return 2;
    fd = raw_socket (v6);
    if (fd < 0)
        return 3;
    unsigned char *ip = packet + 8;
    /* These errors do not modify the loopback path-MTU cache. */
    packet[0] = parameter_code >= 0 ? 12 : v6 ? 3 : 11;
    packet[1] = parameter_code >= 0 ? parameter_code : 0;
    if (v6) {
        ip[0] = 0x60;
        put16 (ip + 4, echo_len);
        ip[6] = IPPROTO_ICMPV6;
        ip[7] = 64;
        ip[23] = ip[39] = 1;
        echo[2] = echo[3] = 0;
        put16 (echo + 2, checksum (echo, echo_len, 1));
        memcpy (ip + 40, echo, echo_len);
    } else {
        ip[0] = 0x45;
        put16 (ip + 2, 20 + echo_len);
        ip[8] = 64;
        ip[9] = IPPROTO_ICMP;
        ip[12] = ip[16] = 127;
        ip[15] = ip[19] = 1;
        put16 (ip + 10, checksum (ip, 20, 0));
        memcpy (ip + 20, echo, echo_len);
    }
    put16 (packet + 2, checksum (packet, len, v6));
    socklen_t destination_len = loopback (&destination, v6, 0);
    do {
        n = sendto (fd, packet, len, 0, (void *)&destination, destination_len);
    } while (n < 0 && errno == EINTR);
    int saved = errno;
    close (fd);
    if (n != (ssize_t)len) {
        errno = saved;
        perror ("raw injector sendto");
        return 4;
    }
    printf (
        "{\"role\":\"raw_injector\",\"family\":%d,\"euid\":%lu,\"os_accepted_bytes\":%zu}\n",
        v6 ? 6 : 4, (unsigned long)geteuid (), len);
    return 0;
}

static void
run_injector (int v6, int parameter_code, const void *echo, size_t len)
{
    int channel[2], status;
    pid_t child;
    posix_spawn_file_actions_t actions;
    char code[] = { '0' + parameter_code, 0 };
    char *args[] = { "sudo",
                     "-n",
                     "--",
                     program,
                     "--inject",
                     v6 ? "6" : "4",
                     parameter_code >= 0 ? code : "time",
                     NULL };
    assert (len == (parameter_code >= 0 ? 236U : 24U) && !pipe (channel));
    assert (!posix_spawn_file_actions_init (&actions));
    assert (
        !posix_spawn_file_actions_adddup2 (&actions, channel[0], STDIN_FILENO));
    assert (!posix_spawn_file_actions_addclose (&actions, channel[0]));
    assert (!posix_spawn_file_actions_addclose (&actions, channel[1]));
    assert (!posix_spawnp (&child, "sudo", &actions, NULL, args, environ));
    assert (!posix_spawn_file_actions_destroy (&actions));
    assert (!close (channel[0]));
    size_t written = 0;
    while (written < len) {
        ssize_t n = write (channel[1], (const unsigned char *)echo + written,
                           len - written);
        if (n < 0 && errno == EINTR)
            continue;
        assert (n > 0);
        written += n;
    }
    assert (!close (channel[1]));
    while (waitpid (child, &status, 0) < 0)
        assert (errno == EINTR);
    assert (WIFEXITED (status) && !WEXITSTATUS (status));
}

static ssize_t
fixture_sendto (int fd, const void *echo, size_t len, int flags,
                const struct sockaddr *target, socklen_t target_len)
{
    unsigned char reply[256];
    int v6 = target->sa_family == AF_INET6, matched = 0;
    ssize_t accepted = sendto (fd, echo, len, flags, target, target_len);
    if (accepted < 0)
        return accepted;
    assert (accepted == (ssize_t)len &&
            len == (current->parameter_code >= 0 ? 236U : 24U) &&
            fd == current->fd[v6]);
    uint64_t deadline = hev_icmp_now () + 3000;
    while (!matched && hev_icmp_now () < deadline) {
        ssize_t n =
            recvfrom (fd, reply, sizeof (reply), MSG_DONTWAIT, NULL, NULL);
        if (n < 0) {
            assert (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR);
            struct pollfd pfd = { .fd = fd, .events = POLLIN };
            assert (poll (&pfd, 1, 10) >= 0 || errno == EINTR);
            continue;
        }
        /* Darwin can also deliver the outgoing Echo Request copy. */
        current->fixture_drained += n;
        matched = n == (ssize_t)len && reply[0] == (v6 ? 129 : 0) &&
                  !memcmp (reply + 4, (const unsigned char *)echo + 4, len - 4);
    }
    assert (matched);
    run_injector (v6, current->parameter_code, echo, len);
    return accepted;
}

#define sendto fixture_sendto
#include ICMP_ENGINE_SOURCE
#undef sendto

static int
bind_engine (int fd, int family, uint16_t identifier, void *context)
{
    Live *live = context;
    struct sockaddr_storage address;
    int v6 = family == AF_INET6;
    socklen_t len = loopback (&address, v6, identifier);
    live->fd[v6] = fd;
    return bind (fd, (void *)&address, len);
}

static int
active (void *context)
{
    (void)context;
    return 1;
}

static void
observe (const struct sockaddr *peer, socklen_t len, size_t bytes, int writing,
         void *context)
{
    Live *live = context;
    assert (peer && len && bytes);
    if (peer->sa_family == AF_INET)
        assert (((const struct sockaddr_in *)peer)->sin_addr.s_addr ==
                htonl (INADDR_LOOPBACK));
    else
        assert (peer->sa_family == AF_INET6 &&
                IN6_IS_ADDR_LOOPBACK (
                    &((const struct sockaddr_in6 *)peer)->sin6_addr));
    if (writing)
        live->written += bytes;
    else
        live->received += bytes;
}

static void
complete_live (HevIcmpRequest *request, int error, const struct sockaddr *peer,
               socklen_t peer_len, const struct sockaddr *local,
               socklen_t local_len, const unsigned char *echo, size_t len,
               void *context)
{
    Live *live = context;
    assert (!live->done && error && peer && peer_len && !echo && !len);
    assert (local && local_len && local->sa_family == peer->sa_family);
#ifdef __APPLE__
    assert (local->sa_len == local_len);
#endif
    if (local->sa_family == AF_INET)
        assert (local_len == sizeof (struct sockaddr_in) &&
                ((const struct sockaddr_in *)local)->sin_addr.s_addr ==
                    htonl (INADDR_LOOPBACK));
    else
        assert (local_len == sizeof (struct sockaddr_in6) &&
                IN6_IS_ADDR_LOOPBACK (
                    &((const struct sockaddr_in6 *)local)->sin6_addr));
    live->local_family = local->sa_family;
    live->done = 1;
    live->error = error;
    live->origin = request->error_origin;
    live->type = request->icmp_type;
    live->code = request->icmp_code;
    live->info = request->icmp_info;
}

static void
run_live (void *unused)
{
    (void)unused;
    for (int scenario = 0; scenario < 5; scenario++) {
        int v6 = scenario == 1;
        int parameter_code = scenario >= 2 ? scenario - 2 : -1;
        size_t echo_len = parameter_code >= 0 ? 236 : 24;
        Live live = { .fd = { -1, -1 }, .parameter_code = parameter_code };
        struct sockaddr_storage destination;
        socklen_t len = loopback (&destination, v6, 0);
        unsigned char echo[236] = { 0 };
        current = &live;
        HevIcmpEngine *engine =
            hev_icmp_engine_new (bind_engine, observe, complete_live, &live);
        assert (engine);
        hev_icmp_echo (echo, v6 ? AF_INET6 : AF_INET, 0x31415926);
        for (size_t i = 8; i < echo_len; i++)
            echo[i] = i;
        if (!v6) {
            echo[2] = echo[3] = 0;
            put16 (echo + 2, checksum (echo, echo_len, 0));
        }
        HevIcmpRequest *request = hev_icmp_request_new (
            NULL, 0, (void *)&destination, len, echo, echo_len, 3000, &live);
        assert (request && !hev_icmp_engine_send (engine, request));
        uint64_t deadline = hev_icmp_now () + 3500;
        while (!live.done && hev_icmp_now () < deadline) {
            hev_icmp_engine_poll (engine, active);
            if (!live.done)
                hev_task_sleep (10);
        }
        assert (live.done && live.origin == HEV_ICMP_ERROR_RECEIVED &&
                live.type == (parameter_code >= 0 ? 12 :
                              v6                  ? 3 :
                                                    11) &&
                live.code == (parameter_code >= 0 ? parameter_code : 0) &&
                !live.info);
        if (parameter_code >= 0)
            assert (live.error == EPROTO);
        assert (live.written == echo_len && live.received > 0 &&
                live.fixture_drained >= echo_len);
        hev_icmp_engine_free (engine);
        printf (
            "{\"result\":\"PASS\",\"role\":\"unprivileged_engine\",\"family\":%d,\"euid\":%lu,\"error_origin\":%d,\"icmp_type\":%d,\"icmp_code\":%d,\"info\":%u,\"local_family\":%d,\"engine_os_write_bytes\":%zu,\"engine_os_read_bytes\":%zu,\"fixture_drained_read_bytes\":%zu}\n",
            v6 ? 6 : 4, (unsigned long)geteuid (), live.origin, live.type,
            live.code, live.info, live.local_family, live.written,
            live.received, live.fixture_drained);
    }
    puts (
        "PASS: real loopback ICMP errors reached the unprivileged production engine; privileged injector and fixture-consumed Echo Reply are separate");
}

int
main (int argc, char **argv)
{
    assert (realpath (argv[0], program));
    if (argc == 2 && !strcmp (argv[1], "--probe-raw")) {
        for (int v6 = 0; v6 < 2; v6++) {
            int fd = raw_socket (v6);
            if (fd < 0)
                return 77;
            close (fd);
        }
        printf (
            "{\"role\":\"raw_capability_probe\",\"euid\":%lu,\"result\":\"AVAILABLE\"}\n",
            (unsigned long)geteuid ());
        return 0;
    }
    if (argc == 4 && !strcmp (argv[1], "--inject") &&
        (!strcmp (argv[2], "4") || !strcmp (argv[2], "6"))) {
        int v6 = !strcmp (argv[2], "6");
        int code = !strcmp (argv[3], "time") ? -1 :
                   strlen (argv[3]) == 1 && argv[3][0] >= '0' &&
                           argv[3][0] <= '2' ?
                                               argv[3][0] - '0' :
                                               -2;
        if (code < -1 || (v6 && code >= 0))
            return 2;
        return inject (v6, code);
    }
    assert (argc == 1 && geteuid () != 0);
    assert (!hev_task_system_init ());
    HevTask *task = hev_task_new (65536);
    assert (task);
    hev_task_run (task, run_live, NULL);
    hev_task_system_run ();
    hev_task_system_fini ();
    return 0;
}
