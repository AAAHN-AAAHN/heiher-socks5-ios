#define _GNU_SOURCE
#include <assert.h>
#include <stdio.h>
#include <errno.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/uio.h>
#include <unistd.h>
#include <hev-task.h>
#include <hev-task-io.h>
#include <hev-task-io-socket.h>
static int script[8], pos, used, cancel, yields, callbacks, writes;
static size_t accounted;
static ssize_t
result (void)
{
    assert (pos < used);
    int n = script[pos++];
    if (n < 0) {
        errno = -n;
        return -1;
    }
    return n;
}
static ssize_t
raw_recv (int fd, void *b, size_t n, int f)
{
    (void)fd;
    (void)b;
    (void)n;
    (void)f;
    return result ();
}
static ssize_t
raw_send (int fd, const void *b, size_t n, int f)
{
    return raw_recv (fd, (void *)b, n, f);
}
static ssize_t
raw_recvmsg (int fd, struct msghdr *m, int f)
{
    (void)m;
    return raw_recv (fd, NULL, 0, f);
}
static ssize_t
raw_sendmsg (int fd, const struct msghdr *m, int f)
{
    return raw_recvmsg (fd, (struct msghdr *)m, f);
}
static int
raw_recvmmsg (int fd, struct mmsghdr *m, unsigned n, int f, struct timespec *t)
{
    (void)fd;
    (void)n;
    (void)f;
    (void)t;
    int r = result ();
    for (int i = 0; i < r; i++)
        m[i].msg_len = i ? 7 : 0;
    return r;
}
static int
raw_sendmmsg (int fd, struct mmsghdr *m, unsigned n, int f)
{
    return raw_recvmmsg (fd, m, n, f, NULL);
}
#define recv raw_recv
#define send raw_send
#define recvmsg raw_recvmsg
#define sendmsg raw_sendmsg
#define recvmmsg raw_recvmmsg
#define sendmmsg raw_sendmmsg
#ifdef FORCE_FALLBACK
#undef MSG_WAITFORONE
#endif
#include "lib/io/socket/hev-task-io-socket.c"
#undef recv
#undef send
#undef recvmsg
#undef sendmsg
#undef recvmmsg
#undef sendmmsg
static int
yield (HevTaskYieldType type, void *c)
{
    assert (type == HEV_TASK_WAITIO && c == &pos);
    yields++;
    return cancel;
}
static void
observe (int fd, const struct msghdr *m, size_t n, int writing, void *c)
{
    assert (fd == 99 && c == &pos);
    (void)m;
    accounted += n;
    callbacks++;
    writes += writing;
    errno = ERANGE;
}
static void
reset (int a, int b, int c, int d)
{
    script[0] = a;
    script[1] = b;
    script[2] = c;
    script[3] = d;
    used = 4;
    pos = 0;
    cancel = 0;
    yields = callbacks = writes = 0;
    accounted = 0;
}
int
main (void)
{
    unsigned cases = 0;
    char b[32];
    struct iovec iov = { b, 10 };
    struct msghdr msg = { .msg_iov = &iov, .msg_iovlen = 1 };
    for (int wr = 0; wr < 2; wr++)
        for (int vect = 0; vect < 2; vect++)
            for (int stop = 0; stop < 2; stop++) {
                reset (4, -EAGAIN, 3, 0);
                cancel = stop;
                ssize_t n = vect ? (wr ? hev_task_io_socket_sendmsg_observed (
                                             99, &msg, MSG_WAITALL, yield, &pos,
                                             observe, &pos) :
                                         hev_task_io_socket_recvmsg_observed (
                                             99, &msg, MSG_WAITALL, yield, &pos,
                                             observe, &pos)) :
                                   (wr ? hev_task_io_socket_send_observed (
                                             99, b, 10, MSG_WAITALL, yield,
                                             &pos, observe, &pos) :
                                         hev_task_io_socket_recv_observed (
                                             99, b, 10, MSG_WAITALL, yield,
                                             &pos, observe, &pos));
                assert (n == (stop ? 4 : 7) && accounted == (size_t)n &&
                        yields == 1 && callbacks == (stop ? 1 : 2));
                assert (writes == (wr ? callbacks : 0));
                cases++;
            }
    reset (3, 0, 0, 0);
    assert (hev_task_io_socket_recv_observed (99, b, 10, MSG_PEEK, yield, &pos,
                                              observe, &pos) == 3);
    assert (!callbacks);
    cases++;
    reset (-EAGAIN, 0, 0, 0);
    assert (hev_task_io_socket_recv_observed (99, b, 10, MSG_DONTWAIT, yield,
                                              &pos, observe, &pos) == -1);
    assert (errno == EAGAIN && !callbacks && !yields);
    cases++;
    reset (35, 0, 0, 0);
    assert (hev_task_io_socket_recv_observed (99, b, 10, MSG_TRUNC, yield, &pos,
                                              observe, &pos) == 35);
    assert (accounted == 10);
    cases++;
    reset (35, 0, 0, 0);
    assert (hev_task_io_socket_recvmsg_observed (99, &msg, MSG_TRUNC, yield,
                                                 &pos, observe, &pos) == 35);
    assert (accounted == 10);
    cases++;
    for (int scenario = 0; scenario < 6; scenario++) {
        int wr = scenario / 3, stop = scenario % 3;
        struct mmsghdr mv[3] = { 0 };
        for (int i = 0; i < 3; i++) {
            mv[i].msg_hdr = msg;
            mv[i].msg_len = 999;
        }
#ifndef MSG_WAITFORONE
        reset (0, 7, stop ? -EAGAIN : -EIO, 0);
#else
        reset (2, stop ? -EAGAIN : -EIO, 0, 0);
#endif
        /* A canceled wait after accepted messages returns the prefix count;
         * only cancellation before any progress is observable as -2. */
        if (stop == 2)
            reset (-EAGAIN, 0, 0, 0);
        cancel = stop;
        int n = wr ? hev_task_io_socket_sendmmsg_observed (
                         99, mv, 3, MSG_WAITALL, yield, &pos, observe, &pos) :
                     hev_task_io_socket_recvmmsg_observed (
                         99, mv, 3, MSG_WAITALL, yield, &pos, observe, &pos);
        assert (n == (stop == 2 ? -2 : 2));
        assert (accounted == (stop == 2 ? 0 : 7));
        assert (callbacks == (stop == 2 ? 0 : 1));
        assert (errno == (stop ? EAGAIN : EIO) && yields == !!stop);
        cases++;
    }
    reset (4, -EIO, 0, 0);
    assert (hev_task_io_socket_recv_observed (99, b, 10, MSG_WAITALL, yield,
                                              &pos, NULL, NULL) == 4);
    assert (!callbacks && errno == EIO);
    cases++;
    printf (
        "PASS %u observed-helper groups: consuming bytes, partial/wait/cancel/error, errno, peeks, truncated copy, empty UDP, native/fallback prefixes\n",
        cases);
    return 0;
}
