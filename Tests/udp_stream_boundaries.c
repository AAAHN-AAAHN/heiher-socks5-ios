#define _GNU_SOURCE
/* Actual production codec; only completed stream-I/O results are controlled.
 * No rewritten parser, timer, buffer helper, or application API. */
#define hev_task_io_socket_recv stream_recv
#define hev_task_io_socket_recvmsg stream_recvmsg
#define hev_task_io_socket_sendmsg stream_sendmsg
#include "hev-socks5-udp.c"
#undef hev_task_io_socket_recv
#undef hev_task_io_socket_recvmsg
#undef hev_task_io_socket_sendmsg

#include <assert.h>
#include <stdio.h>

static unsigned char wire[140000], sent[140000];
static size_t available, consumed, first_piece, emitted;
static int end_result, send_calls, body_calls;
static ssize_t send_result;
static unsigned long cases;

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

int
main (void)
{
    receive_boundaries ();
    header_boundaries ();
    send_boundaries ();
    printf (
        "PASS: %lu stream boundary cases; exact payload/address, partial-frame prefix and terminal write checks\n",
        cases);
    return 0;
}
