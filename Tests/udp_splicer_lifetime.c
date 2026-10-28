#define _GNU_SOURCE
/* Actual full relay loop, real sockets and Hev scheduling. Heap boundaries are
 * counted/faulted. Resolver and binder callbacks can close the real control peer;
 * the NAME converter still runs normally. No DNS suspension is simulated here. */
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <poll.h>
#include <hev-task.h>
#include <hev-task-system.h>
#include "hev-socks5-misc.h"

static void *counted_malloc (size_t size);
static void *counted_malloc0 (size_t size);
static void counted_free (void *ptr);
static unsigned int counted_sleep (unsigned int milliseconds);
static int convert_destination (const HevSocks5Addr *addr,
                                struct sockaddr_in6 *saddr, int *family);

#define hev_malloc counted_malloc
#define hev_malloc0 counted_malloc0
#define hev_free counted_free
#define hev_task_sleep counted_sleep
#define hev_socks5_addr_into_sockaddr6 convert_destination
#include "hev-socks5-udp.c"
#undef hev_malloc
#undef hev_malloc0
#undef hev_free
#undef hev_task_sleep
#undef hev_socks5_addr_into_sockaddr6

typedef struct
{
    const char *name;
    unsigned int fail_at;
    int bind_failure, backward, second_frame, eof, healthy, stopped;
    int close_control; /* 1: after conversion; 2: before successful bind return. */
} Case;

static Case test;
static void *allocations[8];
static unsigned int calls, outstanding, terminal_allocations, sleeps;
static int control[2], front, relay, returned, cancelled, bound, converted;
static HevSocks5 self;
static HevTask *owner;

static void *
counted_malloc (size_t size)
{
    void *ptr;
    size_t i;
    calls++;
    if (!self.timeout)
        terminal_allocations++;
    if (test.fail_at == calls) {
        errno = ENOMEM;
        return NULL;
    }
    ptr = malloc (size);
    assert (ptr);
    for (i = 0; i < 8 && allocations[i]; i++) {
    }
    assert (i < 8);
    allocations[i] = ptr;
    outstanding++;
    return ptr;
}

static void *
counted_malloc0 (size_t size)
{
    void *ptr = counted_malloc (size);
    if (ptr)
        memset (ptr, 0, size);
    return ptr;
}

static void
counted_free (void *ptr)
{
    size_t i;
    for (i = 0; i < 8 && allocations[i] != ptr; i++) {
    }
    assert (ptr && i < 8 && outstanding);
    allocations[i] = NULL;
    outstanding--;
    free (ptr);
}

static unsigned int
counted_sleep (unsigned int milliseconds)
{
    sleeps++;
    return hev_task_sleep (milliseconds);
}

static int
get_fd (HevSocks5UDP *object)
{
    (void)object;
    return front;
}

static void *
get_iface (HevObject *object, void *type)
{
    static HevSocks5UDPIface iface = { .get_fd = get_fd };
    (void)object;
    assert (type == HEV_SOCKS5_UDP_TYPE);
    return &iface;
}

static int
convert_destination (const HevSocks5Addr *addr, struct sockaddr_in6 *saddr,
                     int *family)
{
    int result = hev_socks5_addr_into_sockaddr6 (addr, saddr, family);
    converted++;
    if (test.close_control == 1)
        assert (shutdown (control[1], SHUT_WR) == 0);
    return result;
}

static int
bind_destination (HevSocks5 *object, int fd, const struct sockaddr *address)
{
    (void)object;
    (void)fd;
    (void)address;
    bound++;
    if (test.bind_failure) {
        errno = EADDRNOTAVAIL;
        return -1;
    }
    if (test.close_control == 2)
        assert (shutdown (control[1], SHUT_WR) == 0);
    return 0;
}

static void
consume (void *data)
{
    (void)data;
    int result = hev_socks5_udp_splicer (&self, relay);
    assert (result ==
            (test.stopped || (test.fail_at && test.fail_at <= 2) ? -1 : 0));
    returned = 1;
    assert (!outstanding);
    /* The association, not the splicer, owns these descriptors. */
    assert (fcntl (control[0], F_GETFD) >= 0 && fcntl (front, F_GETFD) >= 0 &&
            fcntl (relay, F_GETFD) >= 0);
    hev_task_del_fd (hev_task_self (), front);
    hev_task_del_fd (hev_task_self (), relay);
}

static void
stop (void *data)
{
    (void)data;
    /* Bounded watchdog; correctness uses terminal state, not elapsed-time bands.
     * A setup/receive failure must return without requiring this cancellation. */
    assert (hev_task_sleep (20) == 0);
    if (!returned) {
        cancelled = 1;
        hev_socks5_set_timeout (&self, 0);
        hev_task_wakeup (owner);
    }
}

static void
nonblocking (int fd)
{
    int flags = fcntl (fd, F_GETFL);
    assert (flags >= 0 && fcntl (fd, F_SETFL, flags | O_NONBLOCK) == 0);
}

static void
ready (int fd, short events)
{
    struct pollfd pfd = { .fd = fd, .events = events };
    assert (poll (&pfd, 1, 1000) == 1 && (pfd.revents & events));
}

static int
udp_socket (struct sockaddr_in6 *address)
{
    int fd = socket (AF_INET6, SOCK_DGRAM, 0);
    socklen_t size = sizeof (*address);
    assert (fd >= 0);
    nonblocking (fd);
    memset (address, 0, size);
#if defined(__APPLE__)
    address->sin6_len = size;
#endif
    address->sin6_family = AF_INET6;
    address->sin6_addr = in6addr_loopback;
    assert (bind (fd, (struct sockaddr *)address, size) == 0);
    assert (getsockname (fd, (struct sockaddr *)address, &size) == 0);
    return fd;
}

static void
send_frame (const struct sockaddr_in6 *address, unsigned int size)
{
    unsigned char *bytes = malloc (size + 22);
    size_t sent = 0;
    assert (bytes);
    bytes[0] = size >> 8;
    bytes[1] = size;
    bytes[2] = 22;
    bytes[3] = HEV_SOCKS5_ADDR_TYPE_IPV6;
    memcpy (bytes + 4, &address->sin6_addr, 16);
    memcpy (bytes + 20, &address->sin6_port, 2);
    memset (bytes + 22, 0x73, size);
    while (sent < size + 22) {
        ssize_t result;
        ready (control[1], POLLOUT);
        result = send (control[1], bytes + sent, size + 22 - sent, 0);
        assert (result > 0);
        sent += result;
    }
    free (bytes);
    ready (control[0], POLLIN);
}

static void
run (Case value, int buffer_count)
{
    struct sockaddr_in6 relay_address, target_address, peer_address,
        front_address;
    static HevSocks5Class klass = { .base.iface = get_iface,
                                    .binder = bind_destination };
    unsigned char reply[60001];
    HevTask *controller;
    int destination, peer, space = 256 * 1024;
    test = value;
    calls = outstanding = terminal_allocations = sleeps = 0;
    returned = cancelled = bound = converted = 0;
    memset (allocations, 0, sizeof (allocations));
    assert (socketpair (AF_UNIX, SOCK_STREAM, 0, control) == 0);
    nonblocking (control[0]);
    nonblocking (control[1]);
    for (size_t i = 0; i < 2; i++) {
        assert (setsockopt (control[i], SOL_SOCKET, SO_SNDBUF, &space,
                            sizeof (space)) == 0);
        assert (setsockopt (control[i], SOL_SOCKET, SO_RCVBUF, &space,
                            sizeof (space)) == 0);
    }
    relay = udp_socket (&relay_address);
    destination = udp_socket (&target_address);
    peer = udp_socket (&peer_address);
    assert (setsockopt (peer, SOL_SOCKET, SO_SNDBUF, &space, sizeof (space)) ==
            0);
    self = (HevSocks5){ .base.klass = &klass.base,
                        .fd = control[0],
                        .type = HEV_SOCKS5_TYPE_UDP_IN_TCP,
                        .timeout = test.stopped ? 0 : 1000 };
    front = control[0];
    if (test.close_control) {
        /* A real known-connected SOCKS UDP association, with a NAME "::1".
         * The independent stream remains the real control connection. */
        front = udp_socket (&front_address);
        assert (connect (front, (struct sockaddr *)&peer_address,
                         sizeof (peer_address)) == 0);
        self.type = HEV_SOCKS5_TYPE_UDP_IN_UDP;
        self.udp_associated = 1;
        memset (reply, 0, 10);
        reply[3] = HEV_SOCKS5_ADDR_TYPE_NAME;
        reply[4] = 3;
        memcpy (reply + 5, "::1", 3);
        memcpy (reply + 8, &target_address.sin6_port, 2);
        memset (reply + 10, 0x73, 48001);
        assert (sendto (peer, reply, 48011, 0,
                        (struct sockaddr *)&front_address,
                        sizeof (front_address)) == 48011);
        ready (front, POLLIN);
    } else {
        send_frame (&target_address, 48001);
    }
    if (test.second_frame)
        send_frame (&target_address, 58001);
    if (test.eof)
        assert (shutdown (control[1], SHUT_WR) == 0);
    if (test.backward) {
        memset (reply, 0x41, sizeof (reply));
        assert (sendto (peer, reply, sizeof (reply), 0,
                        (struct sockaddr *)&relay_address,
                        sizeof (relay_address)) == sizeof (reply));
        ready (relay, POLLIN);
    }
    assert (hev_task_system_init () == 0);
    hev_socks5_set_udp_copy_buffer_nums (buffer_count);
    owner = hev_task_new (-1);
    controller = hev_task_new (-1);
    assert (owner && controller);
    hev_task_run (owner, consume, NULL);
    hev_task_run (controller, stop, NULL);
    hev_task_system_run ();
    hev_task_system_fini ();
    printf ("%s: buffers=%d, allocations=%u, outstanding=%u, after-stop=%u, "
            "sleeps=%u, external-cancel=%d\n",
            test.name, buffer_count, calls, outstanding, terminal_allocations,
            sleeps, cancelled);
    fflush (stdout);
    assert (returned && !outstanding && !terminal_allocations);
    assert (cancelled == test.healthy && !!sleeps == test.healthy);
    if (test.stopped) {
        assert (!calls && !bound && !self.timeout);
        assert (recv (control[0], reply, 1, MSG_PEEK | MSG_DONTWAIT) == 1);
        assert (reply[0] == 48001 >> 8);
    }
    if (test.close_control) {
        assert (converted == 1 && bound == (test.close_control == 2));
        assert (!self.timeout);
        assert (recv (destination, reply, 1, MSG_DONTWAIT) == -1 &&
                errno == EAGAIN);
    }
    if (test.bind_failure)
        assert (bound == 1 && !self.timeout);
    if (test.backward && !test.healthy) {
        memset (reply, 0, sizeof (reply));
        assert (recv (relay, reply, sizeof (reply), MSG_PEEK | MSG_DONTWAIT) ==
                sizeof (reply));
        for (size_t i = 0; i < sizeof (reply); i++)
            assert (reply[i] == 0x41);
    }
    close (control[0]);
    close (control[1]);
    if (test.close_control)
        close (front);
    close (relay);
    close (peer);
    close (destination);
}

int
main (void)
{
    const Case cases[] = {
        { .name = "base allocation failure", .fail_at = 1 },
        { .name = "slot allocation failure", .fail_at = 2 },
        { .name = "first expansion failure", .fail_at = 3 },
        { .name = "second expansion failure", .fail_at = 4, .second_frame = 1 },
        { .name = "complete prefix then EOF", .eof = 1 },
        { .name = "healthy timer cancellation", .backward = 1, .healthy = 1 },
        { .name = "terminal forward with queued reply",
          .fail_at = 3,
          .backward = 1 },
        { .name = "destination binder failure", .bind_failure = 1 },
        { .name = "already cancelled before relay entry", .stopped = 1 },
        { .name = "UDP control closes after NAME conversion",
          .close_control = 1,
          .backward = 1 },
        { .name = "UDP control closes before bind returns",
          .close_control = 2,
          .backward = 1 },
    };
    signal (SIGPIPE, SIG_IGN);
    for (size_t i = 0; i < sizeof (cases) / sizeof (cases[0]); i++) {
        run (cases[i], 2);
        run (cases[i], 100);
    }
    puts (
        "PASS: full relay cleanup, retained socket ownership, sticky terminal "
        "state and no subsequent reply consumption or allocation");
    return 0;
}
