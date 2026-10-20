#define _GNU_SOURCE
#include <sys/socket.h>

ssize_t stream_datagram_recv (int fd, void *buf, size_t length, int flags);
#if defined(__APPLE__)
int stream_datagram_getsockopt (int fd, int level, int option, void *value,
                                socklen_t *length);
#endif

/* Actual production codec/forwarder; completed I/O and resolution are controlled.
 * No rewritten parser, forward loop, timer, buffer helper, or application API. */
#define hev_task_io_socket_recv stream_recv
#define hev_task_io_socket_recvmsg stream_recvmsg
#define hev_task_io_socket_recvmmsg stream_recvmmsg
#define hev_task_io_socket_sendmsg stream_sendmsg
#define hev_task_io_socket_sendmmsg stream_sendmmsg
#define hev_socks5_addr_into_sockaddr6 stream_resolve
#define recv stream_datagram_recv
#if defined(__APPLE__)
#define getsockopt stream_datagram_getsockopt
#endif
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
#undef hev_task_io_socket_recvmmsg
#undef hev_task_io_socket_sendmsg
#undef hev_task_io_socket_sendmmsg
#undef hev_socks5_addr_into_sockaddr6
#undef recv
#if defined(__APPLE__)
#undef getsockopt
#endif

#include <assert.h>
#include <stdio.h>
#include <hev-task-system.h>

static unsigned char wire[140000], sent[140000];
static size_t available, consumed, first_piece, emitted;
static int end_result, send_calls, body_calls;
static ssize_t send_result;
static unsigned long cases;
static int chunk_active, chunk_fault_call, chunk_cancel_call;
static ssize_t chunk_fault_result;
static unsigned chunk_requested, chunk_frames_seen;
static int name_send_active;

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
    int result, bind_error, stop;
    ForwardCall calls[4];
} forward_cases[] = {
    { 4,
      1,
      11,
      1,
      0,
      0,
      { { 11, 3 } } }, /* Middle resolution failure; empty kept. */
    { 15, 0, 0, 1, 0, 0, { { 0, 0 } } }, /* All dropped: no bind or send. */
    { 0, 3, 13, 1, 0, 0, { { 15, 1 }, { 14, -1 }, { 12, 2 } } },
    { 0, 1, 0, -1, 0, 0, { { 15, -2 } } }, /* Direct cancellation is terminal. */
    { 0, 2, 1, -1, 0, 0, { { 15, 1 }, { 14, -2 } } },
    { 0, 4, 0, 1, 0, 0, { { 15, 0 }, { 14, 0 }, { 12, 0 }, { 8, 0 } } },
    { 0, 4, 0, 1, 0, 0, { { 15, -1 }, { 14, -1 }, { 12, -1 }, { 8, -1 } } },
    { 0, 4, 4, 1, 0, 0, { { 15, 0 }, { 14, -1 }, { 12, 1 }, { 8, 0 } } },
    { 9, 1, 6, 1, 0, 0, { { 6, 2 } } }, /* Bind first valid compacted address. */
    { 13, 1, 2, 1, 0, 0, { { 2, 1 } } }, /* Only an empty datagram. */
    { 0, 0, 0, -1, -1, 1, { { 0, 0 } } }, /* Binder failure stays terminal. */
    { 0, 0, 0, -1, 0, 2, { { 0, 0 } } }, /* Canceled in successful resolution. */
    { 1, 0, 0, -1, 0, 2, { { 0, 0 } } }, /* Canceled in failed resolution. */
    { 0, 0, 0, -1, 0, 3, { { 0, 0 } } }, /* Canceled in successful binding. */
    { 0, 0, 0, -1, -1, 3, { { 0, 0 } } }, /* Canceled in failed binding. */
    { 0, 1, 1, -1, 0, 1, { { 15, 1 } } }, /* Terminal after a completed prefix. */
    { 0, 1, 0, -1, 0, 1, { { 15, -1 } } }, /* Terminal with an ordinary error. */
};
static unsigned forward_case, forward_calls, forward_resolved, forward_bound;
static unsigned forward_accepted, forward_meter_calls;
static int forward_terminal_receive;
static HevSocks5 *forward_resolve_self;
static HevSocks5UDPMsg forward_messages[4];
static const struct
{
    unsigned count, accepted;
    int result, stop;
    ForwardCall calls[4];
} backward_cases[] = {
    { 1, 15, 1, 0, { { 15, 4 } } },
    { 3, 13, 1, 0, { { 15, 1 }, { 14, -1 }, { 12, 2 } } },
    { 1, 0, -1, 0, { { 15, -2 } } },
    { 2, 1, -1, 0, { { 15, 1 }, { 14, -2 } } },
    { 4, 0, 1, 0, { { 15, 0 }, { 14, 0 }, { 12, 0 }, { 8, 0 } } },
    { 4, 0, 1, 0, { { 15, -1 }, { 14, -1 }, { 12, -1 }, { 8, -1 } } },
    { 4, 4, 1, 0, { { 15, 0 }, { 14, -1 }, { 12, 1 }, { 8, 0 } } },
    { 1, 0, -1, 1, { { 15, -1 } } }, /* Canceled with an ordinary error. */
    { 1, 1, -1, 1, { { 15, 1 } } }, /* Cancellation after a sent prefix. */
    { 0, 0, -1, -1, { { 0, 0 } } }, /* Already canceled before sending. */
};
static const size_t backward_lengths[] = { 7, 0, 23, 31 };
static unsigned char backward_payloads[4][31];
static unsigned backward_case, backward_calls, backward_accepted;
static unsigned backward_receive_index;
static int backward_active;

ssize_t
stream_datagram_recv (int fd, void *buf, size_t length, int flags)
{
    if (backward_active && fd == 23 && (flags & MSG_PEEK)) {
        if (backward_receive_index < 4)
            return backward_lengths[backward_receive_index];
        errno = EAGAIN;
        return -1;
    }
    return recv (fd, buf, length, flags);
}

#if defined(__APPLE__)
int
stream_datagram_getsockopt (int fd, int level, int option, void *value,
                            socklen_t *length)
{
    if (backward_active && fd == 23 && level == SOL_SOCKET &&
        option == SO_NREAD) {
        assert (*length == sizeof (int));
        *(int *)value = backward_receive_index < 4 ?
                            backward_lengths[backward_receive_index] :
                            0;
        return 0;
    }
    return getsockopt (fd, level, option, value, length);
}
#endif

int
stream_recvmmsg (int fd, void *messages, unsigned count, int flags,
                 HevTaskIOYielder yielder, void *self)
{
    struct mmsghdr *vector = messages;
    assert (backward_active && fd == 23 && count == 1);
    assert (flags == MSG_DONTWAIT && yielder == task_io_yielder && self);
    for (unsigned i = 0; i < count; i++) {
        unsigned id = backward_receive_index++;
        struct msghdr *msg = &vector[i].msg_hdr;
        struct sockaddr_in6 *addr = msg->msg_name;
        assert (id < 4);
        assert (msg->msg_namelen == sizeof (*addr));
        memset (addr, 0, sizeof (*addr));
        addr->sin6_family = AF_INET6;
        addr->sin6_port = htons (100 + id);
        addr->sin6_addr.s6_addr[10] = addr->sin6_addr.s6_addr[11] = 0xff;
        addr->sin6_addr.s6_addr[12] = 127;
        addr->sin6_addr.s6_addr[15] = 1;
        assert (msg->msg_iovlen == 1 && msg->msg_iov[0].iov_len >= 31);
        memcpy (msg->msg_iov[0].iov_base, backward_payloads[id],
                backward_lengths[id]);
        vector[i].msg_len = backward_lengths[id];
    }
    return count;
}

static int
backward_send (int fd, void *messages, unsigned count, int flags,
               HevTaskIOYielder yielder, void *self)
{
    struct mmsghdr *vector = messages;
    const ForwardCall *call;
    unsigned index = 0;
    assert (fd == 19 && flags == MSG_WAITALL && yielder == task_io_yielder);
    assert (backward_calls < backward_cases[backward_case].count);
    call = &backward_cases[backward_case].calls[backward_calls++];
    for (unsigned id = 0; id < 4; id++) {
        struct msghdr *msg;
        HevSocks5Addr *addr;
        if (!(call->mask & (1u << id)))
            continue;
        assert (index < count);
        msg = &vector[index].msg_hdr;
        assert (!msg->msg_name && !msg->msg_namelen && msg->msg_iovlen == 3);
        assert (msg->msg_iov[0].iov_len == 3);
        assert (!memcmp (msg->msg_iov[0].iov_base, "\0\0", 3));
        addr = msg->msg_iov[1].iov_base;
        assert (msg->msg_iov[1].iov_len == 7 && addr->atype == 1);
        assert (addr->ipv4.port == htons (100 + id));
        assert (msg->msg_iov[2].iov_len == backward_lengths[id]);
        assert (!memcmp (msg->msg_iov[2].iov_base, backward_payloads[id],
                         backward_lengths[id]));
        if ((int)index < call->result) {
            assert (!(backward_accepted & (1u << id)));
            backward_accepted |= 1u << id;
        }
        index++;
    }
    assert (index == count);
    if (backward_cases[backward_case].stop)
        hev_socks5_set_timeout (self, 0);
    errno = EIO;
    return call->result;
}

int
stream_resolve (const HevSocks5Addr *source, struct sockaddr_in6 *address,
                int *family)
{
    unsigned id = forward_resolved++;
    assert (!forward_terminal_receive);
    assert (id < 4);
    if (forward_resolve_self) {
        assert (!id); /* No next resolver may run after cancellation. */
        hev_socks5_set_timeout (forward_resolve_self, 0);
    }
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
    while (forward_cases[forward_case].drop & (1u << first))
        first++;
    assert (first < 4 && fd == 23 && !forward_bound++);
    assert (ntohs (((const struct sockaddr_in6 *)address)->sin6_port) ==
            100 + first);
    if (forward_cases[forward_case].stop == 3)
        hev_socks5_set_timeout (self, 0);
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
    if (forward_cases[forward_case].stop)
        hev_socks5_set_timeout (self, 0);
    errno = EIO;
    return call->result;
}

static int
name_sendmmsg (int fd, void *messages, unsigned count, int flags)
{
    struct mmsghdr *vector = messages;
    assert (fd == 19 && count == 2 && flags == MSG_WAITALL);
    send_calls++;
    emitted = 0;
    for (unsigned i = 0; i < count; i++) {
        struct msghdr *msg = &vector[i].msg_hdr;
        assert (msg->msg_iovlen == 3);
        assert (!memcmp (msg->msg_iov[0].iov_base, "\0\0", 3));
        for (unsigned j = 0; j < 3; j++) {
            assert (msg->msg_iov[j].iov_len <= sizeof (sent) - emitted);
            memcpy (sent + emitted, msg->msg_iov[j].iov_base,
                    msg->msg_iov[j].iov_len);
            emitted += msg->msg_iov[j].iov_len;
        }
    }
    return count;
}

int
stream_sendmmsg (int fd, void *messages, unsigned count, int flags,
                 HevTaskIOYielder yielder, void *self)
{
    assert (
        !FORWARD_EXPECT_METER); /* Raw send must not bypass composed meter. */
    if (name_send_active)
        return name_sendmmsg (fd, messages, count, flags);
    return backward_active ?
               backward_send (fd, messages, count, flags, yielder, self) :
               forward_send (fd, messages, count, flags, yielder, self);
}

#if FORWARD_EXPECT_METER
int
stream_meter_sendmmsg (int fd, void *messages, unsigned count, int flags,
                       HevTaskIOYielder yielder, void *self)
{
    forward_meter_calls++;
    if (name_send_active)
        return name_sendmmsg (fd, messages, count, flags);
    return backward_active ?
               backward_send (fd, messages, count, flags, yielder, self) :
               forward_send (fd, messages, count, flags, yielder, self);
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
    size_t start;
    assert (fd == 19 && flags == MSG_WAITALL);
    send_calls++;
    if (!chunk_active)
        emitted = 0;
    start = emitted;
    for (size_t i = 0; i < (size_t)message->msg_iovlen; i++) {
        const struct iovec *iov = &message->msg_iov[i];
        assert (iov->iov_len <= sizeof (sent) - emitted);
        memcpy (sent + emitted, iov->iov_base, iov->iov_len);
        emitted += iov->iov_len;
    }
    errno = EIO;
    if (chunk_active) {
        unsigned remaining = chunk_requested - chunk_frames_seen;
        unsigned frames = remaining > 10 ? 10 : remaining;
        assert (yielder == task_io_yielder && HEV_SOCKS5 (data)->timeout);
        assert (message->msg_iovlen == frames * 3);
        chunk_frames_seen += frames;
        if (send_calls == chunk_cancel_call)
            hev_socks5_set_timeout (data, 0);
        if (send_calls == chunk_fault_call)
            return chunk_fault_result == SSIZE_MAX ?
                       (ssize_t)(emitted - start) - 1 :
                       chunk_fault_result;
        return emitted - start;
    }
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
domain_boundaries (void)
{
    const struct
    {
        size_t cut;
        int nul, empty;
    } checks[] = { { 17, -1, 0 }, { 17, 0, 0 }, { 17, 4, 0 },  { 17, 8, 0 },
                   { 4, -1, 0 },  { 5, -1, 0 }, { 13, -1, 0 }, { 15, -1, 0 },
                   { 7, -1, 1 },  { 8, -1, 1 } };
    HevSocks5Class klass = { .base.iface = get_iface, .binder = forward_bind };
    UDPWorkspace workspace;
    void *allocation = udp_workspace_new (&workspace, 2, NULL);
    assert (allocation);
    for (int managed = 0; managed < 2; managed++) {
        for (int prefix = 0; prefix < 2; prefix++) {
            for (unsigned i = 0; i < sizeof (checks) / sizeof (*checks); i++) {
                HevSocks5 self = { .base.klass = &klass.base,
                                   .type = HEV_SOCKS5_TYPE_UDP_IN_TCP,
                                   .timeout = 60000 };
                unsigned char base[2][UDP_BUF_SIZE];
                UDPBuffer slots[2] = { 0 };
                UDPBuffers owner = { .slots = slots, .count = 2 };
                HevSocks5UDPMsg messages[2] = { 0 };
                size_t head = prefix ? frame (wire, 1, 7) : 0;
                int invalid_name = checks[i].empty || checks[i].nul >= 0;
                int valid = !invalid_name && checks[i].cut == 17;
                unsigned char packet[] = { 0,   1,   16,  3,   9,   '1',
                                           '2', '7', '.', '0', '.', '0',
                                           '.', '1', 0,   53,  42 };
                if (checks[i].empty) {
                    packet[1] = checks[i].cut - 7;
                    packet[2] = 7;
                    packet[4] = 0;
                }
                memcpy (wire + head, packet, sizeof (packet));
                if (checks[i].nul >= 0)
                    wire[head + 5 + checks[i].nul] = 0;
                available = head + checks[i].cut;
                consumed = end_result = 0;
                first_piece = 2;
                for (int id = 0; id < 2; id++) {
                    slots[id] = (UDPBuffer){ .base = base[id],
                                             .capacity = UDP_BUF_SIZE,
                                             .owner = &owner };
                    messages[id].buf = base[id];
                    messages[id].len = sizeof (base[id]);
                }
                int result = hev_socks5_udp_recvmmsg_tcp (
                    &self, messages, prefix + 1, 1, managed ? slots : NULL);
                assert (result == (valid ? prefix + 1 : prefix ? prefix : -1));
                assert (consumed == available &&
                        self.timeout == (valid ? 60000 : 0));
                if (prefix) {
                    assert (messages[0].len == 7);
                    assert (!memcmp (messages[0].addr, wire + 3, 7));
                    assert (!memcmp (messages[0].buf, wire + 10, 7));
                }
                if (valid) {
                    assert (messages[prefix].len == 1);
                    assert (!memcmp (messages[prefix].addr, packet + 3, 13));
                    assert (*(unsigned char *)messages[prefix].buf == 42);
                } else {
                    assert (!messages[prefix].addr);
                    assert (messages[prefix].buf == base[prefix]);
                    assert (messages[prefix].len == sizeof (base[prefix]));
                    assert (errno == (invalid_name ? EINVAL : EPIPE));
                }
                if (invalid_name) {
                    int bind = 0;
                    self.timeout = 60000;
                    consumed = 0;
                    forward_calls = forward_resolved = forward_bound = 0;
                    forward_meter_calls = 0;
                    forward_terminal_receive = 1;
                    assert (hev_socks5_udp_fwd_f (&self, 23, prefix + 1, &bind,
                                                  slots, &workspace) == -1);
                    assert (!self.timeout && consumed == available);
                    assert (!forward_resolved && !forward_bound && !bind);
                    assert (!forward_calls && !forward_meter_calls);
                    forward_terminal_receive = 0;
                }
                cases++;
            }
        }
    }
    puts (
        "PASS: complete and bounded NAME frames; NUL rejection preserves prior count and caller storage; terminal prefixes stop forwarding");
    hev_free (allocation);
}

static void
send_boundaries (void)
{
    HevObjectClass klass = { .iface = get_iface };
    HevSocks5 self = { .base.klass = &klass,
                       .type = HEV_SOCKS5_TYPE_UDP_IN_TCP,
                       .timeout = 60000 };
    HevSocks5UDPMsg messages[2];
    UDPWorkspace workspace;
    void *allocation = udp_workspace_new (&workspace, 2, NULL);
    size_t first = frame (wire, 1, 7);
    size_t second = frame (wire + first, 4, 2048);
    size_t total = first + second;
    assert (allocation);
    messages[0] = (HevSocks5UDPMsg){ (void *)(wire + 3), wire + 10, 7 };
    messages[1] = (HevSocks5UDPMsg){ (void *)(wire + first + 3),
                                     wire + first + 22, 2048 };
    for (send_result = -2; send_result <= (ssize_t)total; send_result++) {
        int result;
        self.timeout = 60000;
        send_calls = 0;
        result = hev_socks5_udp_sendmmsg_tcp (&self, messages, 2, &workspace);
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
    assert (hev_socks5_udp_sendmmsg_tcp (&self, messages, 1, &workspace) == -1);
    assert (!send_calls);
    cases++;
    hev_free (allocation);
}

/* A complete configured batch may need several bounded native sendmsg calls.
 * Check the serialized stream independently, including zero-byte datagrams. */
static void
send_chunk_boundaries (void)
{
    const unsigned counts[] = { 9, 10, 11, 21, 343 };
    const int types[] = { 1, 3, 4 };
    const ssize_t failures[] = { -2, -1, 0, 1, SSIZE_MAX };
    HevObjectClass klass = { .iface = get_iface };
    HevSocks5 self = { .base.klass = &klass,
                       .type = HEV_SOCKS5_TYPE_UDP_IN_TCP,
                       .timeout = 60000 };
    UDPWorkspace workspace;
    void *allocation = udp_workspace_new (&workspace, 343, NULL);
    HevSocks5UDPMsg *messages = calloc (343, sizeof (*messages));
    size_t ends[344] = { 0 };
    assert (allocation && messages);
    for (unsigned i = 0; i < 343; i++) {
        size_t length = i % 5 ? 4 + i % 13 : 0;
        unsigned char *head = wire + ends[i];
        size_t size = frame (head, types[i % 3], length);
        size_t header = size - length;
        assert (size <= sizeof (wire) - ends[i]);
        head[header - 2] = i >> 8;
        head[header - 1] = i;
        for (size_t j = 0; j < length; j++)
            head[header + j] = (i * 13 + j) % 251;
        messages[i] =
            (HevSocks5UDPMsg){ (void *)(head + 3), head + header, length };
        ends[i + 1] = ends[i] + size;
    }
    chunk_active = 1;
    chunk_fault_call = chunk_cancel_call = 0;
    for (unsigned i = 0; i < sizeof (counts) / sizeof (*counts); i++) {
        chunk_requested = counts[i];
        chunk_frames_seen = emitted = send_calls = 0;
        self.timeout = 60000;
        assert (hev_socks5_udp_sendmmsg_tcp (&self, messages, counts[i],
                                             &workspace) == (int)counts[i]);
        assert (send_calls == (int)((counts[i] + 9) / 10));
        assert (chunk_frames_seen == counts[i] && emitted == ends[counts[i]]);
        assert (!memcmp (sent, wire, emitted) && self.timeout == 60000);
        cases++;
    }

    /* An error/short second chunk must never append the third chunk. The
     * positive one-frame prefix is incomplete even at a frame boundary. */
    chunk_requested = 31;
    chunk_fault_call = 2;
    for (unsigned i = 0; i <= sizeof (failures) / sizeof (*failures); i++) {
        chunk_fault_result = i < sizeof (failures) / sizeof (*failures) ?
                                 failures[i] :
                                 (ssize_t)(ends[11] - ends[10]);
        chunk_frames_seen = emitted = send_calls = 0;
        self.timeout = 60000;
        assert (hev_socks5_udp_sendmmsg_tcp (&self, messages, 31, &workspace) ==
                -1);
        assert (send_calls == 2 && chunk_frames_seen == 20);
        assert (emitted == ends[20] && !memcmp (sent, wire, emitted));
        assert (!self.timeout);
        cases++;
    }
    chunk_fault_call = 0;
    for (chunk_cancel_call = 1; chunk_cancel_call <= 2; chunk_cancel_call++) {
        chunk_frames_seen = emitted = send_calls = 0;
        self.timeout = 60000;
        assert (hev_socks5_udp_sendmmsg_tcp (&self, messages, 31, &workspace) ==
                -1);
        assert (send_calls == chunk_cancel_call);
        assert (chunk_frames_seen == (unsigned)chunk_cancel_call * 10);
        assert (emitted == ends[chunk_frames_seen]);
        assert (!memcmp (sent, wire, emitted) && !self.timeout);
        cases++;
    }
    chunk_cancel_call = 0;

    /* Validation covers every original message before any chunk is sent. */
    chunk_requested = 343;
    for (unsigned mode = 0; mode < 3; mode++) {
        HevSocks5Addr invalid = { .atype = mode == 0 ? 255 : 3 };
        HevSocks5UDPMsg saved = messages[342];
        invalid.domain.len = 249;
        if (mode < 2)
            messages[342].addr = &invalid;
        else
            messages[342].len = 65536;
        chunk_frames_seen = emitted = send_calls = 0;
        self.timeout = 60000;
        assert (hev_socks5_udp_sendmmsg_tcp (&self, messages, 343,
                                             &workspace) == -1);
        assert (!send_calls && !emitted && !chunk_frames_seen);
        assert (self.timeout == 60000);
        messages[342] = saved;
        cases++;
    }
    chunk_active = 0;
    free (messages);
    hev_free (allocation);

    puts (
        "PASS: 9/10/11/21/343-frame sends; complete stream, second-chunk failures, cancellation and prevalidation");
}

/* The public send APIs validate every address before any write. */
static void
send_name_boundaries (void)
{
    const unsigned lengths[] = { 0, 1, 248, 249, 255 };
    HevObjectClass klass = { .iface = get_iface };
    HevSocks5 self = { .base.klass = &klass };
    unsigned char payload[7] = { 1, 2, 3, 4, 5, 6, 7 };
    for (unsigned transport = 0; transport < 2; transport++) {
        self.type = transport ? HEV_SOCKS5_TYPE_UDP_IN_TCP :
                                HEV_SOCKS5_TYPE_UDP_IN_UDP;
        for (unsigned i = 0; i < sizeof (lengths) / sizeof (*lengths); i++) {
            for (unsigned invalid_index = 0; invalid_index < 2;
                 invalid_index++) {
                for (int nul = -1; nul < 3; nul++) {
                    HevSocks5Addr addresses[2] = { 0 }, saved[2];
                    HevSocks5UDPMsg messages[2], original[2];
                    for (unsigned j = 0; j < 2; j++) {
                        HevSocks5Addr *addr = &addresses[j];
                        addr->atype = HEV_SOCKS5_ADDR_TYPE_NAME;
                        addr->domain.len = j == invalid_index ? lengths[i] : 1;
                        memset (addr->domain.addr, 'x', addr->domain.len);
                        messages[j] =
                            (HevSocks5UDPMsg){ addr, payload, j ? 7 : 0 };
                    }
                    if (nul >= 0 && lengths[i]) {
                        unsigned position = nul == 0 ? 0 :
                                            nul == 1 ? lengths[i] / 2 :
                                                       lengths[i] - 1;
                        addresses[invalid_index].domain.addr[position] = 0;
                    }
                    memcpy (saved, addresses, sizeof (saved));
                    memcpy (original, messages, sizeof (original));
                    self.timeout = 60000;
                    name_send_active = !transport;
                    emitted = send_calls = 0;
                    send_result =
                        lengths[i] + 22; /* Two headers and 7B payload. */
                    int valid = lengths[i] && nul < 0 &&
                                (!transport || lengths[i] <= 248);
                    int result = hev_socks5_udp_sendmmsg (&self, messages, 2);
                    assert (result == (valid ? 2 : -1));
                    assert (send_calls == valid && self.timeout == 60000);
                    assert (valid ? emitted == (size_t)send_result : !emitted);
                    assert (!memcmp (saved, addresses, sizeof (saved)) &&
                            !memcmp (original, messages, sizeof (original)));
                    assert (
                        !memcmp (payload, "\1\2\3\4\5\6\7", sizeof (payload)));
                    cases++;
                }
            }
        }
    }
    name_send_active = 0;
    puts (
        "PASS: public UDP/TCP send NAME lengths 0/1/248/249/255; first/later empty or NUL names write nothing; caller storage and terminal state preserved");
}

static void
forward_boundaries (void)
{
    const int types[] = { 1, 3, 4 };
    HevSocks5Class klass = { .base.iface = get_iface, .binder = forward_bind };
    UDPWorkspace workspace;
    void *allocation = udp_workspace_new (&workspace, 4, NULL);
    unsigned long count = 0;
    assert (allocation);
    for (forward_case = 0;
         forward_case < sizeof (forward_cases) / sizeof (*forward_cases);
         forward_case++) {
        for (int expanded = 0; expanded <= 1; expanded++) {
            for (int rotation = 0; rotation < 3; rotation++) {
                for (first_piece = 1; first_piece <= 5; first_piece += 4) {
                    HevSocks5 self = { .base.klass = &klass.base,
                                       .type = HEV_SOCKS5_TYPE_UDP_IN_TCP,
                                       .timeout = 60000 };
                    unsigned char base[4][UDP_BUF_SIZE];
                    UDPBuffer slots[4] = { 0 };
                    UDPBuffers owner = { .slots = slots, .count = 4 };
                    size_t lengths[] = { 7, 0, 23, expanded ? 2048 : 1232 };
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
                    forward_resolve_self =
                        forward_cases[forward_case].stop == 2 ? &self : NULL;
                    assert (hev_socks5_udp_fwd_f (&self, 23, 4, &bind, slots,
                                                  &workspace) ==
                            forward_cases[forward_case].result);
                    forward_resolve_self = NULL;
                    assert (consumed == available);
                    assert (forward_resolved ==
                            (forward_cases[forward_case].stop == 2 ? 1 : 4));
                    assert (forward_accepted ==
                            forward_cases[forward_case].accepted);
                    assert (forward_calls == forward_cases[forward_case].count);
                    assert (forward_bound ==
                            (forward_cases[forward_case].drop != 15 &&
                             forward_cases[forward_case].stop != 2));
                    assert (bind == (forward_bound &&
                                     !forward_cases[forward_case].bind_error &&
                                     forward_cases[forward_case].stop != 3));
                    assert (forward_meter_calls ==
                            (FORWARD_EXPECT_METER ? forward_calls : 0));
                    if (forward_cases[forward_case].result == 1) {
                        assert (!hev_socks5_udp_fwd_f (&self, 23, 4, &bind,
                                                       slots, &workspace));
                        assert (forward_resolved == 4);
                        assert (forward_calls ==
                                forward_cases[forward_case].count);
                    }
                    for (unsigned id = 0; id < 4; id++)
                        assert (!udp_buffer_resize (&slots[id], UDP_BUF_SIZE));
                    assert (self.timeout ==
                            (forward_cases[forward_case].stop ? 0 : 60000));
                    count++;
                }
            }
        }
    }
    printf (
        "PASS: %lu actual forward cases; compact vectors, empty payload, bounded errors, terminal send prefixes, meter route %s\n",
        count, FORWARD_EXPECT_METER ? "checked" : "UDP only");
    hev_free (allocation);
}

static void
forward_receive_boundaries (void)
{
    const struct
    {
        size_t cut;
        int end, timeout;
    } endings[] = { { 0, -1, 0 },    { 0, 0, 60000 },  { 2, 0, 60000 },
                    { 7, 0, 60000 }, { 0, -2, 60000 }, { 2, -2, 60000 },
                    { 7, -2, 60000 } };
    HevSocks5Class klass = { .base.iface = get_iface, .binder = forward_bind };
    UDPWorkspace workspace;
    void *allocation = udp_workspace_new (&workspace, 2, NULL);
    assert (allocation);
    forward_terminal_receive = 1;
    for (unsigned i = 0; i < sizeof (endings) / sizeof (*endings); i++) {
        HevSocks5 self = { .base.klass = &klass.base,
                           .type = HEV_SOCKS5_TYPE_UDP_IN_TCP,
                           .timeout = endings[i].timeout };
        unsigned char base[2][UDP_BUF_SIZE];
        UDPBuffer slots[2] = { 0 };
        UDPBuffers owner = { .slots = slots, .count = 2 };
        int bind = 0;
        available = frame (wire, 1, 7);
        frame (wire + available, 1, 23);
        available += endings[i].cut;
        consumed = 0;
        first_piece = 2;
        end_result = endings[i].end;
        forward_calls = forward_resolved = forward_bound = 0;
        forward_meter_calls = 0;
        for (unsigned id = 0; id < 2; id++)
            slots[id] = (UDPBuffer){ .base = base[id],
                                     .capacity = UDP_BUF_SIZE,
                                     .owner = &owner };
        /* The decoder preserves the completed count (checked above), but
             * terminal state must prevent resolution, binding and sending. */
        assert (hev_socks5_udp_fwd_f (&self, 23, 2, &bind, slots, &workspace) ==
                -1);
        assert (!self.timeout && consumed == available);
        assert (!forward_resolved && !forward_bound && !bind);
        assert (!forward_calls && !forward_meter_calls);
        for (unsigned id = 0; id < 2; id++)
            assert (!udp_buffer_resize (&slots[id], UDP_BUF_SIZE));
        cases++;
    }
    forward_terminal_receive = 0;
    puts (
        "PASS: terminal received prefixes stop before resolution, bind or send");
    hev_free (allocation);
}

static int
backward_receive_send (HevSocks5 *self)
{
    unsigned char data[4][UDP_BUF_SIZE];
    UDPBuffer slots[4] = { 0 };
    UDPBuffers owner = { .slots = slots, .count = 4 };
    UDPWorkspace workspace;
    void *allocation = udp_workspace_new (&workspace, 4, NULL);
    int result;
    assert (allocation);
    for (unsigned i = 0; i < 4; i++) {
        slots[i] = (UDPBuffer){ .base = data[i],
                                .capacity = UDP_BUF_SIZE,
                                .owner = &owner };
    }
    backward_receive_index = 0;
    result = hev_socks5_udp_fwd_b (self, 23, 4, slots, &workspace);
    assert (backward_receive_index == 4);
    hev_free (allocation);
    return result;
}

static void
backward_boundaries (void)
{
    HevObjectClass klass = { .iface = get_iface };
    HevSocks5 self = { .base.klass = &klass,
                       .type = HEV_SOCKS5_TYPE_UDP_IN_UDP };
    size_t expected = 0;
    backward_active = 1;
    for (unsigned i = 0; i < 4; i++) {
        memset (backward_payloads[i], i, sizeof (backward_payloads[i]));
        expected += 10 + backward_lengths[i];
    }
    for (backward_case = 0;
         backward_case < sizeof (backward_cases) / sizeof (*backward_cases);
         backward_case++) {
        self.timeout = backward_cases[backward_case].stop < 0 ? 0 : 60000;
        backward_calls = backward_accepted = forward_meter_calls = 0;
        assert (backward_receive_send (&self) ==
                backward_cases[backward_case].result);
        assert (backward_calls == backward_cases[backward_case].count);
        assert (backward_accepted == backward_cases[backward_case].accepted);
        assert (forward_meter_calls ==
                (FORWARD_EXPECT_METER ? backward_calls : 0));
        assert (self.timeout ==
                (backward_cases[backward_case].stop ? 0 : 60000));
        cases++;
    }
    /* The backward loop must never append another TCP frame after any short
     * or failed write, including a write that completed earlier whole frames. */
    self.type = HEV_SOCKS5_TYPE_UDP_IN_TCP;
    for (send_result = -2; send_result <= (ssize_t)expected; send_result++) {
        int result;
        self.timeout = 60000;
        send_calls = 0;
        result = backward_receive_send (&self);
        assert (send_calls == 1 && emitted == expected);
        assert (result == (send_result == (ssize_t)expected ? 1 : -1));
        assert (self.timeout == (result == 1 ? 60000 : 0));
        cases++;
    }
    backward_active = 0;
    printf (
        "PASS: backward UDP send prefixes, empty payloads, bounded errors, cancellation, TCP partial-write termination, meter route %s\n",
        FORWARD_EXPECT_METER ? "checked" : "UDP only");
}

typedef struct
{
    HevSocks5 *self;
    HevTask *waiter;
    int control;
} WaitEnd;

static void
end_wait (void *data)
{
    WaitEnd *end = data;
    if (end->control >= 0) {
        /* Read readiness wakes the task without an explicit task wakeup. */
        assert (!shutdown (end->control, SHUT_WR));
    } else {
        hev_socks5_set_timeout (end->self, 0);
        hev_task_wakeup (end->waiter);
    }
}

static int
yield_case (unsigned mode, HevSocks5 *self)
{
    UDPBuffers buffers = { .next_cleanup =
                               udp_buffer_now () + 60 * UDP_NSEC_PER_SEC };
    if (mode == 2)
        return udp_buffers_yield (HEV_TASK_WAITIO, self, &buffers);
    return task_io_yielder (mode ? HEV_TASK_YIELD : HEV_TASK_WAITIO, self);
}

static void
yielder_boundaries (void *data)
{
    HevSocks5 self = { .type = HEV_SOCKS5_TYPE_UDP_IN_TCP, .timeout = 1 };
    (void)data;
    /* Exercise the real generic yielder and timer, not a mocked -1 result. */
    assert (task_io_yielder (HEV_TASK_WAITIO, &self) == -1);
    assert (!self.timeout);
    cases++;
    /* Direct WAITIO/YIELD and the maintenance wrapper's separate sleep path. */
    for (unsigned mode = 0; mode < 3; mode++) {
        assert (yield_case (mode, &self) == -1);
        cases++;
        for (int control = 0; control <= 1; control++) {
            for (int finite = 0; finite <= 1; finite++) {
                int pair[2];
                HevTask *ender = hev_task_new (-1);
                WaitEnd end = { &self, hev_task_self (), -1 };
                assert (ender);
                self.type = control ? HEV_SOCKS5_TYPE_UDP_IN_UDP :
                                      HEV_SOCKS5_TYPE_UDP_IN_TCP;
                self.timeout = finite ? 60000 : -1;
                if (control) {
                    assert (!hev_task_io_socket_socketpair (
                        AF_UNIX, SOCK_STREAM, 0, pair));
                    self.fd = pair[1];
                    end.control = pair[0];
                    assert (!hev_task_add_fd (end.waiter, self.fd, POLLIN));
                }
                /* The new task runs only after the real yielder suspends us.
                 * Finite cancellation wakes sleep with positive time left. */
                hev_task_run (ender, end_wait, &end);
                assert (yield_case (mode, &self) == -1);
                assert (!self.timeout);
                if (control) {
                    assert (!hev_task_del_fd (end.waiter, self.fd));
                    close (pair[0]);
                    close (pair[1]);
                }
                cases++;
            }
        }
    }
    puts (
        "PASS: real direct/maintenance yielder timeout, wake cancellation and control-close termination");
}

int
main (void)
{
    HevTask *task;
    receive_boundaries ();
    header_boundaries ();
    domain_boundaries ();
    send_boundaries ();
    send_chunk_boundaries ();
    send_name_boundaries ();
    forward_boundaries ();
    forward_receive_boundaries ();
    backward_boundaries ();
    assert (!hev_task_system_init ());
    task = hev_task_new (-1);
    assert (task);
    hev_task_run (task, yielder_boundaries, NULL);
    hev_task_system_run ();
    hev_task_system_fini ();
    printf (
        "PASS: %lu stream boundary cases; exact payload/address, partial-frame prefix and terminal write checks\n",
        cases);
    return 0;
}
