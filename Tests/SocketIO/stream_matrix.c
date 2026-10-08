/* Include the actual relay. Script only syscall outcomes and cancellation;
 * callback delivery and buffering remain production; registry is tested separately. */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/uio.h>
#include <unistd.h>

static ssize_t scripted_read (int, const struct iovec *, int);
static ssize_t scripted_write (int, const struct iovec *, int);
static int scripted_shutdown (int, int);
#ifdef ENABLE_IO_SPLICE_SYSCALL
static ssize_t scripted_splice (int, loff_t *, int, loff_t *, size_t,
                                unsigned int);
#endif
#define readv scripted_read
#define writev scripted_write
#define shutdown scripted_shutdown
#define splice scripted_splice
#include "lib/io/basic/hev-task-io.c"
#undef readv
#undef writev
#undef shutdown
#undef splice
#include <hev-task-system.h>

/* Descriptors are labels in the I/O substitutes, not real client sockets. */
enum
{
    client_read = 101,
    server_read = 102,
    server_write = 103,
    client_write = 104
};
typedef struct
{
    int operation, value;
} TraceItem;
static TraceItem reference[64];
static size_t reference_count;
static unsigned int completed_cases;
static struct
{
    int action[4], tick, cancel_at, measured;
    size_t pending[2];
    size_t actual[4], reported[4];
    TraceItem events[64];
    size_t event_count;
    unsigned int callbacks, syscalls;
    void *token;
} state;

static void
trace (int operation, int value)
{
    assert (state.event_count < 64);
    state.events[state.event_count++] = (TraceItem){ operation, value };
}

static int
planned (int operation)
{
    static const int warm[] = { 31, 5, 29, 3 };
    static const int drain[] = { 0, 7, 0, 11 };
    assert (state.tick <= 4);
    if (!state.tick)
        return warm[operation];
    if (state.tick == 1)
        return state.action[operation];
    return drain[operation];
}

static ssize_t
io_result (int operation, size_t capacity)
{
    int value = planned (operation);
    int direction = operation / 2;
    if (value > 0 && (size_t)value > capacity)
        value = (int)capacity;
    /* A full pipe has no read capacity; do not invent EOF from that condition. */
    if (planned (operation) > 0 && !capacity)
        value = -EAGAIN;
    state.syscalls++;
    trace (operation, value);
    if (value < 0) {
        errno = -value;
        return -1;
    }
    if (!(operation & 1)) {
        state.pending[direction] += value;

    } else {
        assert ((size_t)value <= state.pending[direction]);
        state.pending[direction] -= value;
    }
    state.actual[(int[]){ 0, 3, 2, 1 }[operation]] += value;
    return value;
}

static ssize_t
scripted_read (int fd, const struct iovec *iov, int count)
{
    size_t capacity = 0, remaining;
    int operation = fd == client_read ? 0 : 2;
    assert (fd == client_read || fd == server_read);
    for (int i = 0; i < count; i++)
        capacity += iov[i].iov_len;
    ssize_t result = io_result (operation, capacity);
    remaining = result > 0 ? (size_t)result : 0;
    for (int i = 0; i < count && remaining; i++) {
        size_t n = remaining < iov[i].iov_len ? remaining : iov[i].iov_len;
        memset (iov[i].iov_base, operation ? 0xb2 : 0xa1, n);
        remaining -= n;
    }
    assert (!remaining);
    return result;
}

static ssize_t
scripted_write (int fd, const struct iovec *iov, int count)
{
    size_t available = 0, remaining;
    int operation = fd == server_write ? 1 : 3;
    assert (fd == server_write || fd == client_write);
    for (int i = 0; i < count; i++)
        available += iov[i].iov_len;
    assert (available == state.pending[operation / 2]);
    ssize_t result = io_result (operation, available);
    remaining = result > 0 ? (size_t)result : 0;
    for (int i = 0; i < count && remaining; i++) {
        size_t n = remaining < iov[i].iov_len ? remaining : iov[i].iov_len;
        const unsigned char *bytes = iov[i].iov_base;
        for (size_t j = 0; j < n; j++)
            assert (bytes[j] == (operation == 1 ? 0xa1 : 0xb2));
        remaining -= n;
    }
    assert (!remaining);
    return result;
}

static int
scripted_shutdown (int fd, int how)
{
    assert ((fd == server_write || fd == client_write) && how == SHUT_WR);
    trace (4, fd);
    return 0;
}

#ifdef ENABLE_IO_SPLICE_SYSCALL
static ssize_t
scripted_splice (int in, loff_t *off_in, int out, loff_t *off_out,
                 size_t capacity, unsigned int flags)
{
    int operation;
    assert (!off_in && !off_out);
    assert (flags == (SPLICE_F_MOVE | SPLICE_F_NONBLOCK));
    if (in == client_read || in == server_read) {
        operation = in == client_read ? 0 : 2;
        size_t room = 64 - state.pending[operation / 2];
        if (capacity > room)
            capacity = room;
    } else {
        assert (out == server_write || out == client_write);
        operation = out == server_write ? 1 : 3;
        if (capacity > state.pending[operation / 2])
            capacity = state.pending[operation / 2];
    }
    return io_result (operation, capacity);
}
#endif

static void
record (const size_t bytes[4], void *token)
{
    assert (state.measured && token == state.token);
    for (int i = 0; i < 4; i++) {
        assert (bytes[i] == state.actual[i] - state.reported[i]);
        state.reported[i] += bytes[i];
    }
    state.callbacks++;
}

static int
on_yield (HevTaskYieldType type, void *data)
{
    assert (data == &state);
    assert (type == HEV_TASK_YIELD || type == HEV_TASK_WAITIO);
    if (state.measured) {
        for (int i = 0; i < 4; i++)
            assert (state.actual[i] == state.reported[i]);
    }
    trace (5, type);
    return state.tick++ >= state.cancel_at;
}

static void
run_case (const int *actions, int cancel, void *token, size_t id, int mode)
{
    memset (&state, 0, sizeof (state));
    memcpy (state.action, actions, sizeof (state.action));
    state.cancel_at = cancel;
    state.measured = mode == 0;
    state.token = token;
    if (mode == 2)
        hev_task_io_splice (client_read, client_write, server_read,
                            server_write, 64, on_yield, &state);
    else
        hev_task_io_splice_observed (client_read, client_write, server_read,
                                     server_write, 64, on_yield, &state,
                                     state.measured ? record : NULL, token);
    assert (state.syscalls && state.tick <= 5);
    for (int i = 0; i < 4; i++)
        assert (state.reported[i] == (state.measured ? state.actual[i] : 0));
    assert (state.measured ? state.callbacks > 0 : state.callbacks == 0);
    if (!mode) {
        reference_count = state.event_count;
        memcpy (reference, state.events, reference_count * sizeof (*reference));
    } else {
        assert (state.event_count == reference_count);
        for (size_t i = 0; i < reference_count; i++) {
            assert (state.events[i].operation == reference[i].operation);
            assert (state.events[i].value == reference[i].value);
        }
    }
}

static void
run_matrix (void *unused)
{
    (void)unused;
    static const int reads[] = { 0, -EAGAIN, -ECONNRESET, 1, 7, 63 };
    static const int writes[] = { 0, -EAGAIN, -EPIPE, 1, 7, 63 };
    void *tokens[3] = { NULL };
    unsigned int cases = 0;

    for (unsigned int combination = 0; combination < 1296; combination++) {
        int actions[4];
        unsigned int digits = combination;
        for (int i = 0; i < 4; i++, digits /= 6)
            actions[i] = i & 1 ? writes[digits % 6] : reads[digits % 6];
        for (int cancel = 0; cancel < 4; cancel++) {
            for (size_t id = 0; id < 1; id++) {
                for (int mode = 0; mode < 3; mode++)
                    run_case (actions, cancel, tokens[id], id, mode);
                cases++;
            }
        }
    }
    printf (
        "PASS: %u TCP I/O/cancellation/attribution cases x 3 callback modes; "
        "four exact stream boundaries, "
        "unchanged disabled/legacy I/O traces; scripted syscalls, not "
        "physical transfers\n",
        cases);
    assert (cases == 5184);
    completed_cases = cases;
}

int
main (void)
{
    assert (hev_task_system_init () == 0);
    HevTask *task = hev_task_new (128 * 1024);
    assert (task);
    hev_task_run (task, run_matrix, NULL);
    hev_task_system_run ();
    hev_task_unref (task);
    hev_task_system_fini ();
    assert (completed_cases == 5184);
    return 0;
}
