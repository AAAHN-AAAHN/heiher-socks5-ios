#define _GNU_SOURCE
/* Actual production codec/forwarder; completed I/O and resolution are controlled.
 * No rewritten parser, forward loop, timer, buffer helper, or application API. */
#define hev_task_io_socket_recv stream_recv
#define hev_task_io_socket_recvmsg stream_recvmsg
#define hev_task_io_socket_sendmsg stream_sendmsg
#define hev_task_io_socket_sendmmsg stream_sendmmsg
#define hev_socks5_addr_into_sockaddr6 stream_resolve
/* The composed audit aliases meter I/O for inherited fixtures. Keep this send
 * boundary distinct so bypassing udp_sendmmsg's meter hook is still detected. */
#ifdef hev_meter_sendmmsg
#undef hev_meter_sendmmsg
#define hev_meter_sendmmsg stream_meter_sendmmsg
#define FORWARD_EXPECT_METER 1
#else
#define FORWARD_EXPECT_METER 0
#endif
#include "hev-socks5-udp.c"
#undef hev_task_io_socket_recv
#undef hev_task_io_socket_recvmsg
#undef hev_task_io_socket_sendmsg
#undef hev_task_io_socket_sendmmsg
#undef hev_socks5_addr_into_sockaddr6

#include <assert.h>
#include <stdio.h>

static unsigned char wire[140000], sent[140000];
static size_t available, consumed, first_piece, emitted;
static int end_result, send_calls, body_calls;
static ssize_t send_result;
static unsigned long cases;

typedef struct
{
    unsigned mask;
    int result;
} ForwardCall;
/* Bit i identifies framed datagram i; datagram 1 has an empty payload. Each
 * call lists the exact offered vector and the completed lower-I/O result. */
static const struct
{
    unsigned drop, count, accepted;
    int result, bind_error;
    ForwardCall calls[4];
} forward_cases[] = {
    { 4, 1, 11, 1, 0, { { 11, 3 } } }, /* Middle resolution failure; empty kept. */
    { 15, 0, 0, 1, 0, { { 0, 0 } } }, /* All dropped: no bind or send. */
    { 0, 3, 13, 1, 0, { { 15, 1 }, { 14, -1 }, { 12, 2 } } },
    { 0, 1, 0, -1, 0, { { 15, -2 } } }, /* Direct cancellation is terminal. */
    { 0, 2, 1, -1, 0, { { 15, 1 }, { 14, -2 } } },
    { 0, 4, 0, 1, 0, { { 15, 0 }, { 14, 0 }, { 12, 0 }, { 8, 0 } } },
    { 0, 4, 0, 1, 0, { { 15, -1 }, { 14, -1 }, { 12, -1 }, { 8, -1 } } },
    { 0, 4, 4, 1, 0, { { 15, 0 }, { 14, -1 }, { 12, 1 }, { 8, 0 } } },
    { 9, 1, 6, 1, 0, { { 6, 2 } } }, /* Bind first valid compacted address. */
    { 13, 1, 2, 1, 0, { { 2, 1 } } }, /* Only an empty datagram. */
    { 0, 0, 0, -1, -1, { { 0, 0 } } }, /* Binder failure stays terminal. */
};
static unsigned forward_case, forward_calls, forward_resolved, forward_bound;
static unsigned forward_accepted, forward_meter_calls;
static HevSocks5UDPMsg forward_messages[4];

int
stream_resolve (const HevSocks5Addr *source, struct sockaddr_in6 *address,
                int *family)
{
    unsigned id = forward_resolved++;
    assert (id < 4);
    assert (!memcmp (source, forward_messages[id].addr,
                     hev_socks5_addr_len (source)));
    if (forward_cases[forward_case].drop & (1u << id))
        return -1;
    memset (address, 0, sizeof (*address));
    address->sin6_family = AF_INET6;
    address->sin6_port = htons (100 + id);
    *family = AF_INET6;
    return 0;
}

static int
forward_bind (HevSocks5 *self, int fd, const struct sockaddr *address)
{
    unsigned first = 0;
    (void)self;
    while (forward_cases[forward_case].drop & (1u << first))
        first++;
    assert (first < 4 && fd == 23 && !forward_bound++);
    assert (ntohs (((const struct sockaddr_in6 *)address)->sin6_port) ==
            100 + first);
    return forward_cases[forward_case].bind_error;
}

static int
forward_send (int fd, void *messages, unsigned count, int flags,
              HevTaskIOYielder yielder, void *self)
{
    struct mmsghdr *vector = messages;
    const ForwardCall *call;
    unsigned index = 0;
    assert (fd == 23 && flags == MSG_WAITALL && self);
    assert (yielder == task_io_yielder);
    assert (forward_calls < forward_cases[forward_case].count);
    call = &forward_cases[forward_case].calls[forward_calls++];
    for (unsigned id = 0; id < 4; id++) {
        struct msghdr *message;
        struct sockaddr_in6 *address;
        if (!(call->mask & (1u << id)))
            continue;
        assert (index < count);
        message = &vector[index].msg_hdr;
        address = message->msg_name;
        assert (message->msg_namelen == sizeof (*address));
        assert (address->sin6_family == AF_INET6);
        assert (ntohs (address->sin6_port) == 100 + id);
        assert (!message->msg_control && !message->msg_controllen);
        assert (message->msg_iovlen == 1);
        assert (message->msg_iov[0].iov_len == forward_messages[id].len);
        assert (!memcmp (message->msg_iov[0].iov_base, forward_messages[id].buf,
                         forward_messages[id].len));
        if ((int)index < call->result) {
            assert (!(forward_accepted & (1u << id)));
            forward_accepted |= 1u << id;
            vector[index].msg_len = message->msg_iov[0].iov_len;
        }
        index++;
    }
    assert (index == count);
    errno = EIO;
    return call->result;
}

int
stream_sendmmsg (int fd, void *messages, unsigned count, int flags,
                 HevTaskIOYielder yielder, void *self)
{
    assert (
        !FORWARD_EXPECT_METER); /* Raw send must not bypass composed meter. */
    return forward_send (fd, messages, count, flags, yielder, self);
}

#if FORWARD_EXPECT_METER
int
stream_meter_sendmmsg (int fd, void *messages, unsigned count, int flags,
                       HevTaskIOYielder yielder, void *self)
{
    forward_meter_calls++;
    return forward_send (fd, messages, count, flags, yielder, self);
}
#endif

static int
get_fd (HevSocks5UDP *self)
{
    (void)self;
    return 19;
}

static void *
get_iface (HevObject *self, void *type)
{
    static HevSocks5UDPIface iface = { .get_fd = get_fd };
    (void)self;
    (void)type;
    return &iface;
}

static ssize_t
read_part (void *buf, size_t length)
{
    if (length > available - consumed)
        length = available - consumed;
    if (!length) {
        errno = EAGAIN;
        return end_result;
    }
    memcpy (buf, wire + consumed, length);
    consumed += length;
    return length;
}

ssize_t
stream_recv (int fd, void *buf, size_t length, int flags,
             HevTaskIOYielder yielder, void *data)
{
    (void)yielder;
    (void)data;
    assert (fd == 19 && length <= 5);
    if (!(flags & MSG_WAITALL) && length > first_piece)
        length = first_piece;
    return read_part (buf, length);
}

ssize_t
stream_recvmsg (int fd, struct msghdr *message, int flags,
                HevTaskIOYielder yielder, void *data)
{
    size_t count = 0;
    (void)yielder;
    (void)data;
    assert (fd == 19 && flags == MSG_WAITALL && message->msg_iovlen == 2);
    body_calls++;
    for (int i = 0; i < 2; i++) {
        struct iovec *iov = &message->msg_iov[i];
        ssize_t result;
        if (!iov->iov_len)
            continue;
        result = read_part (iov->iov_base, iov->iov_len);
        if (result <= 0)
            return count ? (ssize_t)count : result;
        count += result;
        if ((size_t)result != iov->iov_len)
            break;
    }
    return count;
}

ssize_t
stream_sendmsg (int fd, const struct msghdr *message, int flags,
                HevTaskIOYielder yielder, void *data)
{
    (void)yielder;
    (void)data;
    assert (fd == 19 && flags == MSG_WAITALL);
    send_calls++;
    emitted = 0;
    for (size_t i = 0; i < (size_t)message->msg_iovlen; i++) {
        const struct iovec *iov = &message->msg_iov[i];
        assert (iov->iov_len <= sizeof (sent) - emitted);
        memcpy (sent + emitted, iov->iov_base, iov->iov_len);
        emitted += iov->iov_len;
    }
    errno = EIO;
    return send_result;
}

static size_t
frame (unsigned char *out, int atype, size_t payload)
{
    size_t address = atype == 1 ? 7 : atype == 4 ? 19 : 252;
    out[0] = payload >> 8;
    out[1] = payload;
    out[2] = 3 + address;
    out[3] = atype;
    for (size_t i = 1; i < address; i++)
        out[3 + i] = (i * 17) % 251;
    if (atype == 3)
        out[4] = 248; /* Largest NAME that fits this framing's 8-bit header. */
    for (size_t i = 0; i < payload; i++)
        out[3 + address + i] = (i * 31) % 251;
    return 3 + address + payload;
}

static void
receive_case (int atype, size_t payload, size_t cut, int prefix, int managed)
{
    HevObjectClass klass = { .iface = get_iface };
    HevSocks5 self = { .base.klass = &klass,
                       .type = HEV_SOCKS5_TYPE_UDP_IN_TCP,
                       .timeout = 60000 };
    unsigned char base[2][UDP_BUF_SIZE];
    UDPBuffer slots[2] = { 0 };
    UDPBuffers owner = { .slots = slots, .count = 2 };
    HevSocks5UDPMsg messages[2] = { 0 };
    size_t head = prefix ? frame (wire, 1, 7) : 0;
    size_t total = frame (wire + head, atype, payload);
    size_t address = total - payload - 3;
    int result, wanted, expected = prefix + (cut == total);

    assert (cut <= total);
    available = head + cut;
    consumed = 0;
    for (int i = 0; i < 2; i++) {
        slots[i] = (UDPBuffer){ .base = base[i],
                                .capacity = UDP_BUF_SIZE,
                                .owner = &owner };
        messages[i].buf = managed ? base[i] : malloc (70000);
        assert (messages[i].buf);
        messages[i].len = managed ? UDP_BUF_SIZE : 70000;
    }
    result = hev_socks5_udp_recvmmsg_tcp (&self, messages, prefix + 1, 1,
                                          managed ? slots : NULL);
    assert (consumed == available);
    wanted = expected ? expected : (!cut && !end_result ? 0 : -1);
    assert (result == wanted);
    assert (self.timeout ==
            (cut == total || (!cut && end_result == -1) ? 60000 : 0));
    if (prefix) {
        assert (messages[0].len == 7);
        assert (!memcmp (messages[0].addr, wire + 3, 7));
        assert (!memcmp (messages[0].buf, wire + 10, 7));
    }
    if (cut == total) {
        HevSocks5UDPMsg *message = &messages[prefix];
        assert (message->len == payload);
        assert (!memcmp (message->addr, wire + head + 3, address));
        assert (!memcmp (message->buf, wire + head + 3 + address, payload));
        if (managed) {
            size_t capacity;
            assert (udp_buffer_round (address + payload, &capacity) == 0);
            assert (slots[prefix].capacity == capacity);
        }
    }
    for (int i = 0; i < 2; i++) {
        if (managed) {
            assert (udp_buffer_resize (&slots[i], UDP_BUF_SIZE) == 0);
        } else {
            /* A successful receive advances buf but returns addr at its base. */
            free (i < expected ? (void *)messages[i].addr : messages[i].buf);
        }
    }
    cases++;
}

static void
receive_boundaries (void)
{
    const size_t lengths[] = { 0,    1,    1493,  1494,  1500, 1501,
                               2001, 2048, 30001, 48001, 65535 };
    for (int type = 1; type <= 4; type++) {
        if (type == 2)
            continue;
        for (int managed = 0; managed <= 1; managed++) {
            for (first_piece = 1; first_piece <= 5; first_piece++) {
                for (size_t i = 0; i < sizeof (lengths) / sizeof (*lengths);
                     i++) {
                    size_t total = frame (wire, type, lengths[i]);
                    end_result = 0;
                    receive_case (type, lengths[i], total, 0, managed);
                    receive_case (type, lengths[i], total, 1, managed);
                }
            }
            /* Every missing byte through a >1500-byte frame, with/without a
             * complete preceding message. EOF and canceled wait stay distinct. */
            first_piece = 2;
            size_t total = frame (wire, type, 2048);
            for (size_t cut = 0; cut < total; cut++) {
                for (end_result = 0; end_result >= -2; end_result--) {
                    receive_case (type, 2048, cut, 0, managed);
                    receive_case (type, 2048, cut, 1, managed);
                }
            }
        }
    }
}

/* All declared type/header-byte combinations: reject inconsistent headers
 * before requesting a body. Valid headers still reject this incomplete stream. */
static void
header_boundaries (void)
{
    HevObjectClass klass = { .iface = get_iface };
    HevSocks5 self = { .base.klass = &klass,
                       .type = HEV_SOCKS5_TYPE_UDP_IN_TCP };
    unsigned char base[UDP_BUF_SIZE];
    UDPBuffer slot = { .base = base, .capacity = UDP_BUF_SIZE };
    UDPBuffers owner = { .slots = &slot, .count = 1 };
    slot.owner = &owner;
    for (int type = 0; type <= UINT8_MAX; type++) {
        int valid_header = type == 1 ? 10 :
                           type == 4 ? 22 :
                           type == 3 ? 255 :
                                       -1;
        for (int length = 0; length <= UINT8_MAX; length++) {
            HevSocks5UDPMsg message = { .buf = base, .len = sizeof (base) };
            wire[0] = 0;
            wire[1] = 1;
            wire[2] = length;
            wire[3] = type;
            wire[4] = 248;
            available = 5;
            consumed = body_calls = 0;
            first_piece = 5;
            end_result = 0;
            self.timeout = 60000;
            assert (hev_socks5_udp_recvmmsg_tcp (&self, &message, 1, 1,
                                                 &slot) == -1);
            assert (consumed == 5 && body_calls == (length == valid_header));
            assert (!self.timeout && !slot.history && !message.addr);
            cases++;
        }
    }
}

static void
send_boundaries (void)
{
    HevObjectClass klass = { .iface = get_iface };
    HevSocks5 self = { .base.klass = &klass,
                       .type = HEV_SOCKS5_TYPE_UDP_IN_TCP,
                       .timeout = 60000 };
    HevSocks5UDPMsg messages[2];
    size_t first = frame (wire, 1, 7);
    size_t second = frame (wire + first, 4, 2048);
    size_t total = first + second;
    messages[0] = (HevSocks5UDPMsg){ (void *)(wire + 3), wire + 10, 7 };
    messages[1] = (HevSocks5UDPMsg){ (void *)(wire + first + 3),
                                     wire + first + 22, 2048 };
    for (send_result = -2; send_result <= (ssize_t)total; send_result++) {
        int result;
        self.timeout = 60000;
        send_calls = 0;
        result = hev_socks5_udp_sendmmsg_tcp (&self, messages, 2);
        assert (send_calls == 1 && emitted == total);
        assert (!memcmp (sent, wire, total));
        assert (result == (send_result == (ssize_t)total ? 2 : -1));
        assert (self.timeout == (result == 2 ? 60000 : 0));
        cases++;
    }
    /* The allocation policy has no 65536 cap; the existing wire field still
     * cannot represent 65536 payload bytes. Do not silently wrap it to zero. */
    messages[0].len = 65536;
    send_calls = 0;
    assert (hev_socks5_udp_sendmmsg_tcp (&self, messages, 1) == -1);
    assert (!send_calls);
    cases++;
}

static void
forward_boundaries (void)
{
    const int types[] = { 1, 3, 4 };
    HevSocks5Class klass = { .base.iface = get_iface, .binder = forward_bind };
    unsigned long count = 0;
    for (forward_case = 0;
         forward_case < sizeof (forward_cases) / sizeof (*forward_cases);
         forward_case++) {
        for (int managed = 0; managed <= 1; managed++) {
            for (int rotation = 0; rotation < 3; rotation++) {
                for (first_piece = 1; first_piece <= 5; first_piece += 4) {
                    HevSocks5 self = { .base.klass = &klass.base,
                                       .type = HEV_SOCKS5_TYPE_UDP_IN_TCP,
                                       .timeout = 60000 };
                    unsigned char base[4][UDP_BUF_SIZE];
                    UDPBuffer slots[4] = { 0 };
                    UDPBuffers owner = { .slots = slots, .count = 4 };
                    size_t lengths[] = { 7, 0, 23, managed ? 2048 : 1232 };
                    int bind = 0;
                    available = consumed = 0;
                    end_result = -1;
                    forward_calls = forward_resolved = forward_bound = 0;
                    forward_accepted = forward_meter_calls = 0;
                    for (unsigned id = 0; id < 4; id++) {
                        unsigned char *head = wire + available;
                        size_t size = frame (head, types[(rotation + id) % 3],
                                             lengths[id]);
                        forward_messages[id] =
                            (HevSocks5UDPMsg){ (void *)(head + 3),
                                               head + size - lengths[id],
                                               lengths[id] };
                        available += size;
                        slots[id] = (UDPBuffer){ .base = base[id],
                                                 .capacity = UDP_BUF_SIZE,
                                                 .owner = &owner };
                    }
                    assert (hev_socks5_udp_fwd_f (&self, 23, base, 4, &bind,
                                                  managed ? slots : NULL) ==
                            forward_cases[forward_case].result);
                    assert (consumed == available && forward_resolved == 4);
                    assert (forward_accepted ==
                            forward_cases[forward_case].accepted);
                    assert (forward_calls == forward_cases[forward_case].count);
                    assert (forward_bound ==
                            (forward_cases[forward_case].drop != 15));
                    assert (bind == (forward_bound &&
                                     !forward_cases[forward_case].bind_error));
                    assert (forward_meter_calls ==
                            (FORWARD_EXPECT_METER ? forward_calls : 0));
                    if (forward_cases[forward_case].result == 1) {
                        assert (!hev_socks5_udp_fwd_f (
                            &self, 23, base, 4, &bind, managed ? slots : NULL));
                        assert (forward_resolved == 4);
                        assert (forward_calls ==
                                forward_cases[forward_case].count);
                    }
                    for (unsigned id = 0; id < 4; id++)
                        assert (!udp_buffer_resize (&slots[id], UDP_BUF_SIZE));
                    assert (self.timeout == 60000);
                    count++;
                }
            }
        }
    }
    printf (
        "PASS: %lu actual forward cases; compact vectors, empty payload, bounded errors, direct cancellation, meter route %s\n",
        count, FORWARD_EXPECT_METER ? "checked" : "UDP only");
}

int
main (void)
{
    receive_boundaries ();
    header_boundaries ();
    send_boundaries ();
    forward_boundaries ();
    printf (
        "PASS: %lu stream boundary cases; exact payload/address, partial-frame prefix and terminal write checks\n",
        cases);
    return 0;
}
