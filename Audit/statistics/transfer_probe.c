/* Test-only: include the production I/O implementation without editing it. */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/uio.h>
#include <unistd.h>

static ssize_t probe_readv(int, const struct iovec *, int);
static ssize_t probe_writev(int, const struct iovec *, int);
static int probe_shutdown(int, int);
#ifdef ENABLE_IO_SPLICE_SYSCALL
static ssize_t probe_splice(int, loff_t *, int, loff_t *, size_t, unsigned int);
#endif

#define readv probe_readv
#define writev probe_writev
#define shutdown probe_shutdown
#define splice probe_splice
#include "lib/io/basic/hev-task-io.c"
#undef readv
#undef writev
#undef shutdown
#undef splice

static int read_result, write_result, shutdown_count, calls;
static int directional;
static int callback_count;
static size_t callback_received, callback_sent;

static ssize_t result(int value)
{
    calls++;
    if (value < 0) {
        errno = -value;
        return -1;
    }
    return value;
}

static ssize_t probe_readv(int fd, const struct iovec *iov, int count)
{
    int value = directional ? (fd == 10 ? 5 : 7) : read_result;
    size_t capacity = 0, left = value > 0 ? (size_t)value : 0;
    for (int i = 0; i < count; i++) {
        size_t n = left < iov[i].iov_len ? left : iov[i].iov_len;
        memset(iov[i].iov_base, 'x', n);
        capacity += iov[i].iov_len;
        left -= n;
    }
    assert(value <= 0 || (size_t)value <= capacity);
    return result(value);
}

static ssize_t probe_writev(int fd, const struct iovec *iov, int count)
{
    int value = directional ? (fd == 20 ? 3 : -EPIPE) : write_result;
    size_t available = 0;
    for (int i = 0; i < count; i++)
        available += iov[i].iov_len;
    assert(value <= 0 || (size_t)value <= available);
    return result(value);
}

static int probe_shutdown(int fd, int how)
{
    (void)fd;
    assert(how == SHUT_WR);
    shutdown_count++;
    return 0;
}

#ifdef ENABLE_IO_SPLICE_SYSCALL
static ssize_t probe_splice(int in, loff_t *off_in, int out, loff_t *off_out,
                            size_t length, unsigned int flags)
{
    (void)out; (void)off_in; (void)off_out; (void)flags;
    int value = in == 10 ? read_result : write_result;
    assert(value <= 0 || (size_t)value <= length);
    return result(value);
}
#endif

static void initialize(HevTaskIOSplicer *s)
{
#ifdef ENABLE_IO_SPLICE_SYSCALL
    memset(s, 0, sizeof(*s));
    s->fd[0] = 30;
    s->fd[1] = 31;
    s->blen = 64;
#else
    assert(task_io_splicer_init(s, 64) == 0);
#endif
}

static void finish(HevTaskIOSplicer *s)
{
#ifndef ENABLE_IO_SPLICE_SYSCALL
    task_io_splicer_fini(s);
#else
    (void)s;
#endif
}

static size_t pending(HevTaskIOSplicer *s)
{
#ifdef ENABLE_IO_SPLICE_SYSCALL
    return s->wlen;
#else
    return hev_circular_buffer_get_use_size(s->buf);
#endif
}

static void record(size_t received, size_t sent, void *data)
{
    assert(data == &callback_count);
    callback_count++;
    callback_received += received;
    callback_sent += sent;
}

static int stop_after_loop(HevTaskYieldType type, void *data)
{
    (void)type;
    assert(data == &calls);
    return 1;
}

int main(void)
{
    HevTaskIOSplicer s;
    size_t received = 0, sent = 0;
    initialize(&s);
    read_result = 5; write_result = 2;
    task_io_splice(&s, 10, 20, &received, &sent);
    assert(received == 5 && sent == 2 && pending(&s) == 3);
    read_result = -EAGAIN; write_result = 1;
    task_io_splice(&s, 10, 20, &received, &sent);
    assert(received == 5 && sent == 3 && pending(&s) == 2);
    read_result = -EAGAIN; write_result = -EAGAIN;
    task_io_splice(&s, 10, 20, &received, &sent);
    assert(received == 5 && sent == 3 && pending(&s) == 2);
    read_result = 0; write_result = 2;
    task_io_splice(&s, 10, 20, &received, &sent);
    assert(received == 5 && sent == 5 && pending(&s) == 0);
    task_io_splice(&s, 10, 20, &received, &sent);
    assert(shutdown_count == 1 && received == 5 && sent == 5);
    finish(&s);
    puts("PASS: partial write, EAGAIN, retry and EOF count exact bytes once");

    initialize(&s);
    received = sent = 0;
    read_result = 7; write_result = -EPIPE;
    task_io_splice(&s, 10, 20, &received, &sent);
    assert(received == 7 && sent == 0 && pending(&s) == 7);
    finish(&s);
    puts("PASS: successful external reads survive a following delivery error");

    initialize(&s);
    received = sent = 0;
    read_result = -ECONNRESET; write_result = 0;
    task_io_splice(&s, 10, 20, &received, &sent);
    assert(received == 0 && sent == 0);
    finish(&s);
    initialize(&s);
    read_result = 3; write_result = 3;
    task_io_splice(&s, 10, 20, NULL, NULL);
    assert(received == 0 && sent == 0 && pending(&s) == 0);
    finish(&s);
    puts("PASS: failed read and disabled counters add no bytes");
#ifndef ENABLE_IO_SPLICE_SYSCALL
    directional = 1;
    calls = 0;
    hev_task_io_splice_with_stats(10, 10, 20, 20, 64, stop_after_loop,
                                 &calls, record, &callback_count);
    assert(callback_count == 1 && callback_received == 7 && callback_sent == 3);
    int measured_calls = calls;
    calls = 0;
    hev_task_io_splice(10, 10, 20, 20, 64, stop_after_loop, &calls);
    assert(calls == measured_calls && callback_count == 1);
    puts("PASS: external-side callback precedes cancellation; legacy API preserves I/O call count");
#endif
    return 0;
}
