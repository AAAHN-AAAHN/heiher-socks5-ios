#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/uio.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <hev-task.h>
#include <hev-task-io.h>
#include <hev-task-io-socket.h>

/* Include the actual I/O helpers and UDP codec. Only raw syscall outcomes are
 * controlled: an EINTR consumes nothing; completed prefixes remain real input. */
static int script[12], step, steps, cancel, yields, batch, completed;
static unsigned char expected[64], actual[64];
static size_t cursor;

static int
next (void)
{
    assert (step < steps);
    int result = script[step++];
    if (result < 0) {
        errno = -result;
        return -1;
    }
    return result;
}

static ssize_t
transfer (struct iovec *iov, size_t count, int writing)
{
    int n = next ();
    if (n < 0)
        return -1;
    if (batch) {
        assert (n == 1);
        n = completed++ ? 7 : 0;
    }
    size_t remaining = n;
    assert (cursor + remaining <= sizeof (expected));
    for (size_t i = 0; i < count && remaining; i++) {
        size_t take = iov[i].iov_len < remaining ? iov[i].iov_len : remaining;
        if (writing)
            assert (!memcmp (iov[i].iov_base, expected + cursor, take));
        else
            memcpy (iov[i].iov_base, expected + cursor, take);
        cursor += take;
        remaining -= take;
    }
    assert (!remaining);
    return n;
}

static ssize_t
raw_recv (int fd, void *buf, size_t len, int flags)
{
    struct iovec iov = { buf, len };
    return transfer (&iov, 1, 0);
}

static ssize_t
raw_send (int fd, const void *buf, size_t len, int flags)
{
    struct iovec iov = { (void *)buf, len };
    return transfer (&iov, 1, 1);
}

static ssize_t
raw_recvfrom (int fd, void *buf, size_t len, int flags, struct sockaddr *addr,
              socklen_t *length)
{
    return raw_recv (fd, buf, len, flags);
}

static ssize_t
raw_sendto (int fd, const void *buf, size_t len, int flags,
            const struct sockaddr *addr, socklen_t length)
{
    return raw_send (fd, buf, len, flags);
}

static ssize_t
raw_recvmsg (int fd, struct msghdr *msg, int flags)
{
    return transfer (msg->msg_iov, msg->msg_iovlen, 0);
}

static ssize_t
raw_sendmsg (int fd, const struct msghdr *msg, int flags)
{
    return transfer (msg->msg_iov, msg->msg_iovlen, 1);
}

#if defined(MSG_WAITFORONE) && !defined(FORCE_FALLBACK)
static int
raw_recvmmsg (int fd, struct mmsghdr *msg, unsigned count, int flags,
              struct timespec *timeout)
{
    int n = next ();
    assert (n <= (int)count);
    if (n > 0) {
        assert (n == 1);
        msg[0].msg_len = completed++ ? 7 : 0;
        cursor += msg[0].msg_len;
    }
    return n;
}

static int
raw_sendmmsg (int fd, struct mmsghdr *msg, unsigned count, int flags)
{
    return raw_recvmmsg (fd, msg, count, flags, NULL);
}
#endif

/* The ordinary TCP relay owns separate read/write cursors. A temporary
 * interruption must not turn either direction into EOF or lose buffered bytes. */
static int splicing, interrupt_read, interrupt_write, shutdowns;
static size_t input_bytes, output_bytes;

static ssize_t
splice_result (struct iovec *iov, int count, int writing, size_t limit)
{
    int *pending = writing ? &interrupt_write : &interrupt_read;
    if (*pending) {
        *pending = 0;
        errno = EINTR;
        return -1;
    }
    size_t *done = writing ? &output_bytes : &input_bytes;
    size_t size = writing ? input_bytes - output_bytes : 9 - input_bytes;
    if (writing && !output_bytes && size > 3)
        size = 3;
    if (size > limit)
        size = limit;
    size_t remaining = size;
    for (int i = 0; i < count && remaining; i++) {
        size_t take = remaining < iov[i].iov_len ? remaining : iov[i].iov_len;
        if (writing)
            assert (!memcmp (iov[i].iov_base, expected + *done, take));
        else
            memcpy (iov[i].iov_base, expected + *done, take);
        *done += take;
        remaining -= take;
    }
    if (!iov)
        *done += size;
    else
        assert (!remaining);
    return size;
}

static ssize_t
raw_readv (int fd, const struct iovec *iov, int count)
{
    if (splicing)
        return splice_result ((void *)iov, count, 0, 64);
    return transfer ((void *)iov, count, 0);
}

static ssize_t
raw_writev (int fd, const struct iovec *iov, int count)
{
    if (splicing)
        return splice_result ((void *)iov, count, 1, 64);
    return transfer ((void *)iov, count, 1);
}

static int
raw_shutdown (int fd, int how)
{
    assert (splicing && fd == 100 && how == SHUT_WR);
    shutdowns++;
    return 0;
}

#if defined(__linux__) && defined(ENABLE_IO_SPLICE_SYSCALL)
static ssize_t
raw_splice (int in, loff_t *off_in, int out, loff_t *off_out, size_t size,
            unsigned flags)
{
    assert (splicing && !off_in && !off_out);
    assert ((in == 99 && out == 91) || (in == 90 && out == 100));
    return splice_result (NULL, 0, in == 90, size);
}
#endif

#define read(fd, buf, len) raw_recv (fd, buf, len, 0)
#define write(fd, buf, len) raw_send (fd, buf, len, 0)
#define readv raw_readv
#define writev raw_writev
#define shutdown raw_shutdown
#define splice raw_splice
#include "lib/io/basic/hev-task-io.c"
#undef read
#undef write
#undef readv
#undef writev
#undef shutdown
#undef splice

#define recv raw_recv
#define send raw_send
#define recvfrom raw_recvfrom
#define sendto raw_sendto
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
#undef recvfrom
#undef sendto
#undef recvmsg
#undef sendmsg
#undef recvmmsg
#undef sendmmsg
#include "hev-socks5-udp.c"

static int
wait_io (HevTaskYieldType type, void *context)
{
    assert (type == HEV_TASK_WAITIO && context == &step);
    yields++;
    return cancel;
}

static void
reset (const int *values, size_t count, int stop, int messages)
{
    assert (count <= sizeof (script) / sizeof (*script));
    memcpy (script, values, count * sizeof (*values));
    steps = count;
    step = yields = completed = 0;
    cursor = 0;
    cancel = stop;
    batch = messages;
    memset (actual, 0, sizeof (actual));
}

static ssize_t
invoke (int operation, int flags)
{
    unsigned char *data = operation & 1 ? expected : actual;
    struct iovec iov[] = { { data, 3 }, { data + 3, 7 } };
    struct msghdr msg = { .msg_iov = iov, .msg_iovlen = 2 };
    struct sockaddr_in address = { .sin_family = AF_INET };
    socklen_t length = sizeof (address);
    switch (operation) {
    case 0:
        return hev_task_io_socket_recv (99, data, 10, flags, wait_io, &step);
    case 1:
        return hev_task_io_socket_send (99, data, 10, flags, wait_io, &step);
    case 2:
        return hev_task_io_socket_recvfrom (
            99, data, 10, flags, (void *)&address, &length, wait_io, &step);
    case 3:
        return hev_task_io_socket_sendto (99, data, 10, flags, (void *)&address,
                                          length, wait_io, &step);
    case 4:
        return hev_task_io_socket_recvmsg (99, &msg, flags, wait_io, &step);
    case 5:
        return hev_task_io_socket_sendmsg (99, &msg, flags, wait_io, &step);
    case 8:
        return hev_task_io_read (99, data, 10, wait_io, &step);
    case 9:
        return hev_task_io_write (99, data, 10, wait_io, &step);
    case 10:
        return hev_task_io_readv (99, iov, 2, wait_io, &step);
    case 11:
        return hev_task_io_writev (99, iov, 2, wait_io, &step);
    default: {
        struct iovec viov[] = { { data, 0 }, { data, 7 } };
        struct mmsghdr vector[2] = { 0 };
        for (int i = 0; i < 2; i++) {
            vector[i].msg_hdr.msg_iov = &viov[i];
            vector[i].msg_hdr.msg_iovlen = 1;
            vector[i].msg_len = 999;
        }
        int n = operation == 6 ?
                    hev_task_io_socket_recvmmsg (99, vector, 2, flags, wait_io,
                                                 &step) :
                    hev_task_io_socket_sendmmsg (99, vector, 2, flags, wait_io,
                                                 &step);
        assert (completed == (n > 0 ? n : 0));
        if (n > 0)
            assert (!vector[0].msg_len);
        if (n == 2)
            assert (vector[1].msg_len == 7);
        return n;
    }
    }
}

static int
stream_fd (HevSocks5UDP *self)
{
    return 99;
}

static void *
stream_iface (HevObject *self, void *type)
{
    static HevSocks5UDPIface iface = { .get_fd = stream_fd };
    assert (type == HEV_SOCKS5_UDP_TYPE);
    return &iface;
}

static void
framing (void)
{
    const unsigned char wire[] = { 0,    7,   10,  1,   127, 0,   0,   1,  0x12,
                                   0x34, 'p', 'a', 'y', 'l', 'o', 'a', 'd' };
    const int receive[] = { -EINTR, 2, -EINTR, 3, -EINTR, 4, -EINTR, 8 };
    const int send[] = { -EINTR, 4, -EINTR, 13 };
    HevObjectClass klass = { .iface = stream_iface };
    HevSocks5 self = { .base.klass = &klass,
                       .type = HEV_SOCKS5_TYPE_UDP_IN_TCP,
                       .timeout = 60000 };
    HevSocks5UDPMsg msg = { .buf = actual, .len = sizeof (actual) };
    memcpy (expected, wire, sizeof (wire));
    reset (receive, sizeof (receive) / sizeof (*receive), 0, 0);
    assert (hev_socks5_udp_recvmmsg_tcp (&self, &msg, 1, 1, NULL) == 1);
    assert (cursor == sizeof (wire) && step == steps && self.timeout == 60000);
    assert (msg.len == 7 && !memcmp (msg.addr, wire + 3, 7) &&
            !memcmp (msg.buf, wire + 10, 7));
    UDPWorkspace workspace;
    void *storage = udp_workspace_new (&workspace, 1, NULL);
    assert (storage);
    msg = (HevSocks5UDPMsg){ (void *)(expected + 3), expected + 10, 7 };
    reset (send, sizeof (send) / sizeof (*send), 0, 0);
    assert (hev_socks5_udp_sendmmsg_tcp (&self, &msg, 1, &workspace) == 1);
    assert (cursor == sizeof (wire) && step == steps && self.timeout == 60000);
    hev_free (storage);
}

/* The Statistics composition adds optional byte outputs to this private
 * helper; its owned driver supplies the matching signature. */
#ifdef UDP_IO_OBSERVED
#define relay_step(s, in, out) task_io_splice (s, in, out, NULL, NULL)
#else
#define relay_step task_io_splice
#endif

static void
splice_boundaries (void)
{
    for (int input = 0; input < 2; input++)
        for (int output = 0; output < 2; output++) {
            HevTaskIOSplicer relay;
            splicing = 1;
            interrupt_read = input;
            interrupt_write = output;
            input_bytes = output_bytes = shutdowns = 0;
#ifdef ENABLE_IO_SPLICE_SYSCALL
            relay = (HevTaskIOSplicer){ .fd = { 90, 91 }, .blen = 64 };
#else
            assert (task_io_splicer_init (&relay, 64) == 0);
#endif
            assert (relay_step (&relay, 99, 100) == 1);
            assert (input_bytes == 9 && output_bytes == 3 && !shutdowns);
            assert (relay_step (&relay, 99, 100) == 1);
            assert (input_bytes == 9 && output_bytes == 9 && !shutdowns);
            assert (relay_step (&relay, 99, 100) == -1 && shutdowns == 1);
#ifndef ENABLE_IO_SPLICE_SYSCALL
            task_io_splicer_fini (&relay);
#endif
            splicing = 0;
        }
}

int
main (void)
{
    static const struct
    {
        int sequence[6], count, result, waits, stop, flags, error;
    } cases[] = {
        { { -EINTR, -EINTR, 4, 6 }, 4, 10, 0, 0, MSG_WAITALL, 0 },
        { { 4, -EINTR, 6 }, 3, 10, 0, 0, MSG_WAITALL, 0 },
        { { -EINTR, -EAGAIN, 4, 6 }, 4, 10, 1, 0, MSG_WAITALL, 0 },
        { { 4, -EINTR, -EAGAIN }, 3, 4, 1, 1, MSG_WAITALL, EAGAIN },
        { { -EINTR, -EAGAIN }, 2, -2, 1, 1, MSG_WAITALL, EAGAIN },
        { { -EINTR, -EIO }, 2, -1, 0, 0, MSG_WAITALL, EIO },
        { { 4, -EINTR, -EIO }, 3, 4, 0, 0, MSG_WAITALL, EIO },
        { { -EINTR, -EAGAIN }, 2, -1, 0, 0, MSG_DONTWAIT, EAGAIN },
        { { -EINTR, 4 }, 2, 4, 0, 0, 0, 0 },
    };
    for (unsigned i = 0; i < sizeof (expected); i++)
        expected[i] = i + 1;
    unsigned count = 0;
    for (int op = 0; op < 8; op++)
        for (unsigned i = 0; i < sizeof (cases) / sizeof (*cases); i++) {
            int sequence[6], result = cases[i].result;
            memcpy (sequence, cases[i].sequence, sizeof (sequence));
            if (op >= 6) {
                for (int j = 0; j < cases[i].count; j++)
                    if (sequence[j] > 0)
                        sequence[j] = 1;
                if (result > 0)
                    result = result == 10 ? 2 : 1;
            }
            reset (sequence, cases[i].count, cases[i].stop, op >= 6);
            assert (invoke (op, cases[i].flags) == result);
            assert (step == steps && yields == cases[i].waits);
            if (cases[i].error)
                assert (errno == cases[i].error);
            size_t bytes = result > 0 ? (op < 6      ? result :
                                         result == 2 ? 7 :
                                                       0) :
                                        0;
            assert (cursor == bytes);
            if (op < 6 && !(op & 1))
                assert (!memcmp (actual, expected, bytes));
            count++;
        }
    static const struct
    {
        int sequence[3], count, result, waits, stop;
    } basic[] = {
        { { -EINTR, -EINTR, 10 }, 3, 10, 0, 0 },
        { { -EINTR, -EAGAIN, 10 }, 3, 10, 1, 0 },
        { { -EINTR, -EAGAIN }, 2, -2, 1, 1 },
        { { -EINTR, -EIO }, 2, -1, 0, 0 },
        { { -EINTR, 0 }, 2, 0, 0, 0 },
        { { -EINTR, 4 }, 2, 4, 0, 0 },
    };
    for (int op = 8; op < 12; op++)
        for (unsigned i = 0; i < sizeof (basic) / sizeof (*basic); i++) {
            reset (basic[i].sequence, basic[i].count, basic[i].stop, 0);
            assert (invoke (op, 0) == basic[i].result);
            assert (step == steps && yields == basic[i].waits);
            assert (cursor == (basic[i].result > 0 ? basic[i].result : 0));
            if (!(op & 1))
                assert (!memcmp (actual, expected, cursor));
            count++;
        }
    splice_boundaries ();
    framing ();
    printf (
        "PASS %u I/O interruption groups, 4 TCP relay boundaries and 2 actual UDP-over-TCP codecs: prefixes, cancellation, nonblocking, errors, empty messages\n",
        count);
    return 0;
}
