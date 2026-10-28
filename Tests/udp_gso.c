#define _GNU_SOURCE
/* Exercise the actual encoder on a small Hev task stack. Only the final socket
 * result is scripted; packet groups, ancillary headers and fallback are real.
 */
#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/socket.h>

#define hev_task_io_socket_sendmmsg gso_send
#ifdef hev_meter_sendmmsg
#undef hev_meter_sendmmsg
#define hev_meter_sendmmsg gso_meter_send
#define EXPECT_METER 1
#else
#define EXPECT_METER 0
#endif
#include "hev-socks5-udp.c"
#undef hev_task_io_socket_sendmmsg
#include "hev-socks5-client-udp.h"
#include <hev-task-system.h>

static HevSocks5UDPMsg *original;
static unsigned total, calls, meter_calls, accepted, group_count;
static int fault, error_number, partial, cancel_after;
static uint64_t accepted_bytes;
static unsigned char *seen;

static unsigned
inspect (struct msghdr *msg, int recording)
{
    size_t segments = msg->msg_iovlen / 3, bytes = 0;
    assert (segments && msg->msg_iovlen == segments * 3);
    assert (!msg->msg_name && !msg->msg_namelen);
    for (size_t j = 0; j < segments; j++) {
        struct iovec *v = msg->msg_iov + j * 3;
        unsigned id;
        assert (v[0].iov_len == 3 && !memcmp (v[0].iov_base, "\0\0\0", 3));
        memcpy (&id, v[2].iov_base, sizeof (id));
        assert (id < total && v[1].iov_base == original[id].addr);
        assert (v[1].iov_len ==
                (size_t)hev_socks5_addr_len (original[id].addr));
        assert (v[2].iov_base == original[id].buf &&
                v[2].iov_len == original[id].len);
        bytes += 3 + v[1].iov_len + v[2].iov_len;
        if (recording) {
            assert (!seen[id]);
            seen[id] = 1;
            accepted++;
        }
    }
#if defined(__linux__) && defined(UDP_SEGMENT)
    if (segments > 1) {
        struct cmsghdr *cm = CMSG_FIRSTHDR (msg);
        uint16_t size;
        assert (segments <= 64 && bytes <= 65000 && cm);
        assert ((uintptr_t)cm % _Alignof (struct cmsghdr) == 0);
        assert (cm->cmsg_level == SOL_UDP && cm->cmsg_type == UDP_SEGMENT);
        assert (cm->cmsg_len == CMSG_LEN (sizeof (size)));
        memcpy (&size, CMSG_DATA (cm), sizeof (size));
        assert (bytes == size * segments && !CMSG_NXTHDR (msg, cm));
    } else
#endif
        assert (segments == 1 && !msg->msg_control && !msg->msg_controllen);
    return bytes;
}

int
gso_send (int fd, void *messages, unsigned int count, int flags,
          HevTaskIOYielder yielder, void *self)
{
    struct mmsghdr *m = messages;
    assert (fd == 19 && count && flags == MSG_WAITALL && yielder);
    calls++;
    group_count = count;
    for (unsigned i = 0; i < count; i++)
        inspect (&m[i].msg_hdr, 0);
    /* A suspended send continues to borrow all vectors/control data. */
    hev_task_yield (HEV_TASK_YIELD);
    for (unsigned i = 0; i < count; i++)
        inspect (&m[i].msg_hdr, 0);
    if (calls == 1 && fault) {
        errno = error_number;
        if (cancel_after)
            hev_socks5_set_timeout (self, 0);
        if (fault == 1)
            return -1;
        return fault == 2 ? -2 : 0;
    }
    unsigned done = partial && calls == 1 ? 1 : count;
    for (unsigned i = 0; i < done; i++) {
        m[i].msg_len = inspect (&m[i].msg_hdr, 1);
        accepted_bytes += m[i].msg_len;
    }
    if (cancel_after)
        hev_socks5_set_timeout (self, 0);
    errno = EINVAL; /* A successful prefix must not trigger a second send. */
    return done;
}

#if EXPECT_METER
int
gso_meter_send (int fd, void *messages, unsigned int count, int flags,
                HevTaskIOYielder yielder, void *self)
{
    meter_calls++;
    return gso_send (fd, messages, count, flags, yielder, self);
}
#endif

static void
exercise (HevSocks5ClientUDP *client, unsigned num, unsigned length, int mixed,
          int failure, int error, int stop, int prefix)
{
    original = calloc (num, sizeof (*original));
    unsigned char *payload = calloc (num, (size_t)length + 4);
    HevSocks5Addr *addresses = calloc (num, sizeof (*addresses));
    seen = calloc (num, 1);
    assert (original && payload && addresses && seen);
    calls = meter_calls = accepted = group_count = 0;
    accepted_bytes = 0;
    total = num;
    fault = failure;
    error_number = error;
    cancel_after = stop;
    partial = prefix;
    for (unsigned i = 0; i < num; i++) {
        assert (hev_socks5_addr_from_ipv4 (
                    &addresses[i], (const unsigned char[]){ 127, 0, 0, 1 },
                    htons (1234)) > 0);
        original[i].addr = &addresses[i];
        original[i].buf = payload + (size_t)i * (length + 4);
        original[i].len = length + (mixed ? i % 2 : 0);
        memcpy (original[i].buf, &i, sizeof (i));
    }
    HEV_SOCKS5 (client)->timeout = 60000;
#if defined(__linux__) && defined(UDP_SEGMENT)
    udp_gso_max_size = 65535;
#endif
    int done = hev_socks5_udp_sendmmsg (client, original, num);
    if (failure == 2 || (failure == 1 && stop) || failure == 3) {
        assert (done == (failure == 2 ? -2 : failure == 3 ? 0 : -1));
        assert (calls == 1 && !accepted);
    } else if (prefix) {
#if defined(__linux__) && defined(UDP_SEGMENT)
        assert (done == 64 && group_count == 3);
#else
        assert (done == 1);
#endif
        assert (accepted == (unsigned)done && calls == 1);
        if (stop) {
            assert (hev_socks5_udp_sendmmsg (client, original + done,
                                             num - done) < 0);
            assert (calls == 1);
        } else {
            partial = 0;
            assert (hev_socks5_udp_sendmmsg (client, original + done,
                                             num - done) == (int)num - done);
            assert (accepted == num);
        }
    } else {
#if defined(__linux__) && defined(UDP_SEGMENT)
        assert (done == (int)num && accepted == num);
        assert (calls == (failure ? 2u : 1u));
#else
        assert (done == (failure ? -1 : (int)num));
        assert (calls == 1 && accepted == (failure ? 0 : num));
#endif
    }
    assert (meter_calls == (EXPECT_METER ? calls : 0));
    uint64_t expected = 0;
    for (unsigned i = 0; i < num; i++)
        if (seen[i])
            expected += 10 + original[i].len;
    assert (accepted_bytes == expected);
    free (seen);
    free (addresses);
    free (payload);
    free (original);
}

static void
cases (void *unused)
{
    (void)unused;
    HevSocks5ClientUDP *client =
        hev_socks5_client_udp_new (HEV_SOCKS5_TYPE_UDP_IN_UDP);
    assert (client);
    client->fd = 19;
    const unsigned counts[] = { 1, 2, 10, 63, 64, 65, 130, 342, 1025 };
    for (size_t i = 0; i < sizeof (counts) / sizeof (*counts); i++) {
        exercise (client, counts[i], 100, 0, 0, 0, 0, 0);
        exercise (client, counts[i], 100, 1, 0, 0, 0, 0);
    }
    const unsigned sizes[] = { 0, 1, 1000, 32490, 32491, 48001 };
    for (size_t i = 0; i < sizeof (sizes) / sizeof (*sizes); i++)
        exercise (client, 2, sizes[i], 0, 0, 0, 0, 0);
    const int errors[] = { EINVAL,     EMSGSIZE,    EIO,
                           EOPNOTSUPP, ENOPROTOOPT, ENOBUFS };
    for (size_t i = 0; i < sizeof (errors) / sizeof (*errors); i++)
        exercise (client, 2, 100, 0, 1, errors[i], 0, 0);
    exercise (client, 2, 100, 0, 2, EINVAL, 0, 0);
    exercise (client, 2, 100, 0, 1, EINVAL, 1, 0);
    exercise (client, 2, 100, 0, 3, EINVAL, 0, 0);
    exercise (client, 130, 100, 0, 0, 0, 0, 1);
    exercise (client, 130, 100, 0, 0, 0, 1, 1);
    client->fd = -1;
    hev_object_unref (HEV_OBJECT (client));
}

#if defined(__linux__) && defined(UDP_SEGMENT)
static pthread_barrier_t barrier;
static void *
thread_hint (void *value)
{
    assert (udp_gso_max_size == -1);
    udp_gso_max_size = (int)(intptr_t)value;
    int res = pthread_barrier_wait (&barrier);
    assert (!res || res == PTHREAD_BARRIER_SERIAL_THREAD);
    assert (udp_gso_max_size == (int)(intptr_t)value);
    return NULL;
}
#endif

int
main (void)
{
#if defined(__linux__) && defined(UDP_SEGMENT)
    pthread_t threads[2];
    udp_gso_max_size = 65535;
    assert (!pthread_barrier_init (&barrier, NULL, 2));
    assert (!pthread_create (&threads[0], NULL, thread_hint, (void *)111));
    assert (!pthread_create (&threads[1], NULL, thread_hint, (void *)222));
    assert (!pthread_join (threads[0], NULL) &&
            !pthread_join (threads[1], NULL));
    assert (!pthread_barrier_destroy (&barrier) && udp_gso_max_size == 65535);
#endif
    assert (!hev_task_system_init ());
    size_t stack = 8192;
#if defined(__has_feature)
#if __has_feature(address_sanitizer)
    stack = 65536;
#endif
#endif
    HevTask *task = hev_task_new (stack);
    assert (task);
    hev_task_run (task, cases, NULL);
    hev_task_system_run ();
    hev_task_system_fini ();
    printf (
        "PASS: 35 actual UDP sender cases, grouped/raw descriptors, bounded "
        "task stack %zu, prefix/cancel/error fallback, thread-local hints\n",
        stack);
    return 0;
}
