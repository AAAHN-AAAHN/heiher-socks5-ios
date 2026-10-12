#define _GNU_SOURCE
/* Portable task-API fault injection around the unchanged production sources.
 * The real Hev scheduler and sockets use 8KiB stacks (64KiB under ASan). An injected
 * API failure is not a claim that the kernel actually exhausted its resources.
 * The separate Linux epoll probe exercises the native syscall failure path. */
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <hev-task.h>
#include <hev-task-system.h>
#include <hev-task-io.h>
#include <hev-task-io-socket.h>
#include <hev-memory-allocator.h>
#include "hev-socks5-server.h"

#ifndef __has_feature
#define __has_feature(x) 0
#endif
#if defined(__SANITIZE_ADDRESS__) || __has_feature(address_sanitizer)
#define TEST_STACK_SIZE 65536
#else
#define TEST_STACK_SIZE 8192
#endif

static int checked_add (HevTask *, int, unsigned int);
static int checked_mod (HevTask *, int, unsigned int);
static void *counted_malloc (size_t);
static void *counted_malloc0 (size_t);
static void counted_free (void *);
static ssize_t counted_plain_recv (int, void *, size_t, int);
static ssize_t counted_recv (int, void *, size_t, int, HevTaskIOYielder,
                             void *);
static void counted_splice (int, int, int, int, size_t, HevTaskIOYielder,
                            void *);
static int io_calls;

#define hev_task_add_fd checked_add
#define hev_task_mod_fd checked_mod
#define hev_malloc counted_malloc
#define hev_malloc0 counted_malloc0
#define hev_free counted_free
#define recv counted_plain_recv
#define hev_task_io_socket_recv counted_recv
#define hev_task_io_splice counted_splice
/* Statistics supplies the observed helper; keep its real observer intact. */
#define hev_task_io_splice_observed(...) \
    (io_calls++, hev_task_io_splice_observed (__VA_ARGS__))
#include "hev-socks5-misc.c"
#include "hev-socks5-udp.c"
#include "hev-socks5-server.c"
#undef task_io_yielder
#include "hev-socks5-tcp.c"
#undef task_io_yielder
#undef hev_task_add_fd
#undef hev_task_mod_fd
#undef hev_malloc
#undef hev_malloc0
#undef hev_free
#undef recv
#undef hev_task_io_socket_recv
#undef hev_task_io_splice
#undef hev_task_io_splice_observed

enum
{
    FACTORY,
    UDP_BACK,
    UDP_FRONT,
    SERVER,
    TCP,
    SERVICE_TCP,
    SERVICE_UDP_TCP,
    SERVICE_UDP_UDP
};
enum
{
    SUCCESS,
    FALLBACK,
    FAILURE
};
static const char *api_names[] = {
    "factory", "udp-back",    "udp-front",       "server",
    "tcp",     "service-tcp", "service-udp-tcp", "service-udp-udp"
};
static const char *mode_names[] = { "success", "fallback", "failure" };
static int api, mode, fail_alloc, armed, target = -1;
static int primary_calls, fallback_calls, result, passed;
static unsigned int allocation_calls, outstanding;
static void *allocations[8];
static HevSocks5Server self;

static int
registration (HevTask *task, int fd, unsigned int events, int add)
{
    int primary = add != (api == UDP_FRONT);
    if (armed && (target < 0 || target == fd)) {
        target = fd;
        if (primary)
            primary_calls++;
        else
            fallback_calls++;
        if (mode == FAILURE || (mode == FALLBACK && primary)) {
            /* A successful MOD requires an existing registration on epoll.
             * kqueue also accepts this state. The first API result itself is
             * injected so that backend ADD idempotence does not alter scope. */
            if (mode == FALLBACK && add)
                assert (hev_task_add_fd (task, fd, events) == 0);
            errno = ENOMEM;
            return -1;
        }
    }
    return add ? hev_task_add_fd (task, fd, events) :
                 hev_task_mod_fd (task, fd, events);
}

static int
checked_add (HevTask *task, int fd, unsigned int events)
{
    return registration (task, fd, events, 1);
}

static int
checked_mod (HevTask *task, int fd, unsigned int events)
{
    return registration (task, fd, events, 0);
}

static void *
counted_malloc (size_t size)
{
    void *ptr;
    size_t i;
    allocation_calls++;
    if ((int)allocation_calls == fail_alloc) {
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
    if (!ptr)
        return;
    for (i = 0; i < 8 && allocations[i] != ptr; i++) {
    }
    assert (i < 8 && outstanding);
    allocations[i] = NULL;
    outstanding--;
    free (ptr);
}

static ssize_t
counted_plain_recv (int fd, void *buf, size_t len, int flags)
{
    io_calls++;
    return recv (fd, buf, len, flags);
}

static ssize_t
counted_recv (int fd, void *buf, size_t len, int flags,
              HevTaskIOYielder yielder, void *data)
{
    io_calls++;
    return hev_task_io_socket_recv (fd, buf, len, flags, yielder, data);
}

static void
counted_splice (int ai, int ao, int bi, int bo, size_t size,
                HevTaskIOYielder yielder, void *data)
{
    io_calls++;
    hev_task_io_splice (ai, ao, bi, bo, size, yielder, data);
}

static int
is_open (int fd)
{
    return fd >= 0 && fcntl (fd, F_GETFD) >= 0;
}

static void
release_fd (int fd)
{
    if (is_open (fd)) {
        hev_task_del_fd (hev_task_self (), fd);
        assert (close (fd) == 0);
    }
}

static void
run_case (void *data)
{
    int front[2] = { -1, -1 }, back[2] = { -1, -1 };
    int datagram_front = -1;
    int ownership, should_fail = mode == FAILURE || fail_alloc;
    (void)data;
    if (api != FACTORY) {
        assert (hev_task_io_socket_socketpair (AF_UNIX, SOCK_STREAM, 0,
                                               front) == 0);
        assert (shutdown (front[1], SHUT_WR) == 0);
        assert (hev_socks5_server_construct (&self, front[0]) == 0);
        self.base.timeout = 100;
        self.base.type = HEV_SOCKS5_TYPE_UDP_IN_TCP;
        if (api == TCP || api == SERVICE_TCP) {
            assert (hev_task_io_socket_socketpair (AF_UNIX, SOCK_STREAM, 0,
                                                   back) == 0);
            assert (shutdown (back[1], SHUT_WR) == 0);
        } else if (api != SERVER) {
            back[0] = hev_task_io_socket_socket (AF_INET6, SOCK_DGRAM, 0);
            assert (back[0] >= 0);
        }
        target = api == UDP_FRONT || api == SERVER ? front[0] : back[0];
        if (api != SERVER && (api != UDP_FRONT || mode == SUCCESS))
            assert (hev_task_add_fd (hev_task_self (), front[0],
                                     POLLIN | POLLOUT) == 0);
        if (api >= SERVICE_TCP) {
            self.fds[0] = back[0];
            if (api == SERVICE_TCP)
                self.base.type = HEV_SOCKS5_TYPE_TCP;
            else if (api == SERVICE_UDP_UDP) {
                datagram_front =
                    hev_task_io_socket_socket (AF_INET6, SOCK_DGRAM, 0);
                assert (datagram_front >= 0);
                assert (hev_task_add_fd (hev_task_self (), datagram_front,
                                         POLLIN | POLLOUT) == 0);
                self.fds[1] = datagram_front;
                self.base.type = HEV_SOCKS5_TYPE_UDP_IN_UDP;
            }
        }
    }
    armed = 1;
    switch (api) {
    case FACTORY:
        result = hev_socks5_socket (SOCK_DGRAM);
        break;
    case UDP_BACK:
    case UDP_FRONT:
        result = hev_socks5_udp_splice (HEV_SOCKS5_UDP (&self), back[0]);
        break;
    case SERVER:
        result = hev_socks5_server_run (&self);
        break;
    case TCP:
        result = hev_socks5_tcp_splice (HEV_SOCKS5_TCP (&self), back[0]);
        break;
    case SERVICE_TCP:
    case SERVICE_UDP_TCP:
    case SERVICE_UDP_UDP:
        result = hev_socks5_server_service (&self);
        break;
    }
    armed = 0;
    ownership = api == FACTORY ?
                    (should_fail ? !is_open (target) : is_open (result)) :
                    is_open (front[0]) && (api == SERVER || is_open (back[0]));
    passed = ownership && !outstanding;
    if (api == SERVICE_UDP_UDP)
        passed &= is_open (datagram_front);
    if (should_fail)
        passed &= result == -1 && io_calls == 0;
    else
        passed &= api == FACTORY ? result >= 0 :
                  api == SERVER  ? result == -1 && io_calls == 1 :
                                   result == 0 && io_calls > 0;
    if (fail_alloc)
        passed &= allocation_calls == (unsigned int)fail_alloc &&
                  primary_calls <= 1 && !fallback_calls;
    else
        passed &= primary_calls == 1 &&
                  fallback_calls == (mode == SUCCESS ? 0 : 1);
    if (api == UDP_BACK || api == UDP_FRONT || api >= SERVICE_UDP_TCP) {
        /* Registration may precede allocation. Both orders must return with
         * no outstanding allocation and no data I/O on either failure. */
        if (mode == FAILURE)
            passed &= allocation_calls == 0 || allocation_calls == 2;
        else
            passed &= allocation_calls ==
                      (unsigned int)(fail_alloc ? fail_alloc : 2);
    }
    printf ("%s-%s alloc_fail=%d result=%d primary=%d fallback=%d io=%d "
            "allocations=%u outstanding=%u ownership=%d stack=%d %s\n",
            api_names[api], mode_names[mode], fail_alloc, result, primary_calls,
            fallback_calls, io_calls, allocation_calls, outstanding, ownership,
            TEST_STACK_SIZE, passed ? "PASS" : "FAIL");
    if (api == FACTORY)
        release_fd (target);
    release_fd (front[0]);
    release_fd (front[1]);
    release_fd (back[0]);
    release_fd (back[1]);
    release_fd (datagram_front);
}

static int
run_one (int which, int how, int allocation_failure)
{
    HevTask *task;
    api = which;
    mode = how;
    fail_alloc = allocation_failure;
    armed = primary_calls = fallback_calls = io_calls = result = passed = 0;
    target = -1;
    allocation_calls = outstanding = 0;
    memset (allocations, 0, sizeof (allocations));
    memset (&self, 0, sizeof (self));
    if (hev_task_system_init ())
        return 2;
    task = hev_task_new (TEST_STACK_SIZE);
    assert (task);
    hev_task_ref (task);
    hev_task_run (task, run_case, NULL);
    hev_task_system_run ();
    hev_task_unref (task);
    hev_task_system_fini ();
    return passed ? 0 : 1;
}

int
main (void)
{
    int which, how, failed = 0, total = 0;
    for (which = FACTORY; which <= TCP; which++) {
        for (how = SUCCESS; how <= FAILURE; how++) {
            failed += !!run_one (which, how, 0);
            total++;
        }
    }
    for (int n = 1; n <= 2; n++) {
        failed += !!run_one (UDP_BACK, SUCCESS, n);
        total++;
    }
    for (which = SERVICE_TCP; which <= SERVICE_UDP_UDP; which++) {
        failed += !!run_one (which, FAILURE, 0);
        total++;
    }
    printf ("reactor resources: %d/%d cases PASS; failures=%d\n",
            total - failed, total, failed);
    return failed ? 1 : 0;
}
