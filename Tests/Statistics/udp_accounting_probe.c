#define _GNU_SOURCE
/* Execute the composed forwarders and buffer manager; only OS/allocator outcomes
 * are substituted. Registry entries and all aggregate/IP counters are real. */
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <hev-memory-allocator.h>

static void *allocate_fixture (size_t size);
static ssize_t size_fixture (int fd, void *buf, size_t len, int flags);
static int option_get (int, int, int, void *, socklen_t *);
static int option_set (int, int, int, const void *, socklen_t);
static int peer_fixture (int, struct sockaddr *, socklen_t *);
#define hev_malloc allocate_fixture
#define recv size_fixture
#define getsockopt option_get
#define setsockopt option_set
#define getpeername peer_fixture
#define hev_task_io_socket_recvmmsg receive_fixture
#define hev_task_io_socket_sendmmsg send_fixture
#define hev_task_io_socket_sendmsg stream_fixture
#include "hev-socks5-udp.c"
#undef hev_malloc
#undef recv
#undef getsockopt
#undef setsockopt
#undef getpeername
#undef hev_task_io_socket_recvmmsg
#undef hev_task_io_socket_sendmmsg
#undef hev_task_io_socket_sendmsg

#include <stdio.h>

static size_t payloads[3] = { 7, 2048, 48001 };
static unsigned int cursor, truncated, delivered, queries, calls, option_calls;
static size_t consumed, sent_bytes;
static int allocation_budget = -1, fail_receive, send_prefix = 3;
static int send_error = EIO, retry_success, send_capacity = 1, stream_partial;
static uint64_t before_in, before_out, before_ip_in, before_ip_out;
static uint64_t ip_in, ip_out;

static void *
allocate_fixture (size_t size)
{
    if (!allocation_budget)
        return NULL;
    if (allocation_budget > 0)
        allocation_budget--;
    return hev_malloc (size);
}

static int
get_fd (HevSocks5UDP *self)
{
    (void)self;
    return 10;
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
next_size (int fd)
{
    queries++;
    assert (fd == 10 || fd == 11);
    if (cursor == 3 || (fail_receive && cursor == 1)) {
        errno = EAGAIN;
        return -1;
    }
    /* Force a mismatched length query; the final receive must still reject a
     * truncated datagram and count only bytes actually copied on the In side. */
    if (truncated & (1u << cursor))
        return 1;
    return payloads[cursor] + (fd == 10 ? 10 : 0);
}

static ssize_t
size_fixture (int fd, void *buf, size_t len, int flags)
{
    (void)buf;
    if (!(flags & MSG_PEEK)) {
        errno = EAGAIN;
        return -1;
    }
    ssize_t result = next_size (fd);
#if defined(__APPLE__)
    return result > (ssize_t)len ? (ssize_t)len : result;
#else
    assert (!len && (flags & MSG_TRUNC));
    return result;
#endif
}

static int
option_get (int fd, int level, int option, void *value, socklen_t *length)
{
    assert (level == SOL_SOCKET && *length == sizeof (int));
#if defined(__APPLE__)
    if (option == SO_NREAD) {
        ssize_t n = next_size (fd);
        if (n < 0)
            return -1;
        *(int *)value = (int)n;
        return 0;
    }
#endif
    assert (fd == 11 && option == SO_SNDBUF);
    *(int *)value = send_capacity;
    option_calls++;
    return 0;
}

static int
option_set (int fd, int level, int option, const void *value, socklen_t length)
{
    assert (fd == 11 && level == SOL_SOCKET && option == SO_SNDBUF);
    assert (length == sizeof (int));
    send_capacity = *(const int *)value;
    option_calls++;
    return 0;
}

static int
peer_fixture (int fd, struct sockaddr *address, socklen_t *length)
{
    struct sockaddr_in6 peer = { 0 };
    assert (fd == 10 && *length >= sizeof (peer));
    peer.sin6_family = AF_INET6;
    peer.sin6_port = htons (40000);
    peer.sin6_addr.s6_addr[15] = 1;
#if defined(__APPLE__)
    peer.sin6_len = sizeof (peer);
#endif
    memcpy (address, &peer, sizeof (peer));
    *length = sizeof (peer);
    return 0;
}

int
receive_fixture (int fd, void *messages, unsigned int num, int flags,
                 HevTaskIOYielder yielder, void *data)
{
    struct mmsghdr *message = messages;
    struct iovec *iov = message->msg_hdr.msg_iov;
    const unsigned char header[] = { 0, 0, 0, 1, 127, 0, 0, 1, 0, 53 };
    size_t wanted = payloads[cursor] + (fd == 10 ? sizeof (header) : 0);
    size_t copied = wanted < iov->iov_len ? wanted : iov->iov_len;
    (void)yielder;
    (void)data;
    assert (num == 1 && flags == MSG_DONTWAIT && cursor < 3);
    memset (iov->iov_base, 0x5a, copied);
    if (fd == 10) {
        assert (copied >= sizeof (header));
        memcpy (iov->iov_base, header, sizeof (header));
        peer_fixture (10, message->msg_hdr.msg_name,
                      &message->msg_hdr.msg_namelen);
    } else {
        struct sockaddr_in6 addr = { 0 };
        addr.sin6_family = AF_INET6;
        addr.sin6_port = htons (53);
        addr.sin6_addr.s6_addr[15] = 1;
#if defined(__APPLE__)
        addr.sin6_len = sizeof (addr);
#endif
        memcpy (message->msg_hdr.msg_name, &addr, sizeof (addr));
    }
    message->msg_len = copied;
    message->msg_hdr.msg_flags = copied < wanted ? MSG_TRUNC : 0;
    consumed += copied;
    cursor++;
    return 1;
}

int
send_fixture (int fd, void *messages, unsigned int num, int flags,
              HevTaskIOYielder yielder, void *data)
{
    struct mmsghdr *vec = messages;
    unsigned int success;
    (void)yielder;
    (void)data;
    assert ((fd == 10 || fd == 11) && flags == MSG_WAITALL && num);
    if (calls++ && !retry_success) {
        errno = send_error;
        return -1;
    }
    success = retry_success && calls > 1 ?
                  num :
                  (send_prefix < 0 ? 0 : (unsigned int)send_prefix);
    if (success > num)
        success = num;
    for (unsigned int i = 0; i < num; i++) {
        vec[i].msg_len = 0xdeadbeef;
        if (i < success) {
            size_t n = 0;
            for (size_t j = 0; j < vec[i].msg_hdr.msg_iovlen; j++)
                n += vec[i].msg_hdr.msg_iov[j].iov_len;
            vec[i].msg_len = n;
            sent_bytes += n;
            delivered++;
        }
    }
    if (success < num)
        errno = send_error;
    return success ? (int)success : -1;
}

ssize_t
stream_fixture (int fd, const struct msghdr *message, int flags,
                HevTaskIOYielder yielder, void *data)
{
    size_t n = 0;
    (void)yielder;
    (void)data;
    assert (fd == 10 && flags == MSG_WAITALL);
    for (size_t i = 0; i < message->msg_iovlen; i++)
        n += message->msg_iov[i].iov_len;
    calls++;
    return stream_partial ? (ssize_t)(n - 1) : (ssize_t)n;
}

static void
snapshot (uint64_t id, const char *address, uint64_t received, uint64_t sent,
          void *data)
{
    (void)id;
    (void)data;
    if (!strcmp (address, "127.0.0.1")) {
        ip_in = received;
        ip_out = sent;
    }
}

static void *
register_client (void)
{
    struct sockaddr_in address = { 0 };
    socklen_t length = sizeof (address);
    int listener = socket (AF_INET, SOCK_STREAM, 0);
    int client = socket (AF_INET, SOCK_STREAM, 0), peer;
    void *token;
    assert (listener >= 0 && client >= 0);
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl (INADDR_LOOPBACK);
#if defined(__APPLE__)
    address.sin_len = sizeof (address);
#endif
    assert (bind (listener, (struct sockaddr *)&address, length) == 0);
    assert (listen (listener, 1) == 0);
    assert (getsockname (listener, (struct sockaddr *)&address, &length) == 0);
    assert (connect (client, (struct sockaddr *)&address, length) == 0);
    peer = accept (listener, NULL, NULL);
    assert (peer >= 0);
    token = hev_socks5_transfer_client (peer);
    assert (token);
    close (peer);
    close (client);
    close (listener);
    return token;
}

static void
check (void *token, int reverse, unsigned int mask, int prefix, int error,
       int retry, int allocation_failure, int query_failure, int tcp)
{
    unsigned char base[UDP_BUF_SIZE * 3];
    UDPBuffers owner = { 0 };
    UDPBuffer slots[3] = { 0 };
    HevSocks5Class klass = { .base.iface = get_iface };
    HevSocks5 self = { .base.klass = &klass.base,
                       .type = tcp ? HEV_SOCKS5_TYPE_UDP_IN_TCP :
                                     HEV_SOCKS5_TYPE_UDP_IN_UDP,
                       .udp_associated = 1,
                       .timeout = 60000 };
    struct sockaddr_in6 addresses[3];
    struct iovec vectors[3];
    struct mmsghdr messages[3] = { 0 };
    uint64_t incoming, outgoing;
    int bound = 1;
    cursor = delivered = queries = calls = option_calls = 0;
    consumed = sent_bytes = 0;
    truncated = mask;
    send_prefix = prefix;
    send_error = error;
    retry_success = retry;
    stream_partial = tcp;
    send_capacity = 1;
    fail_receive = query_failure;
    allocation_budget = allocation_failure ? 0 : -1;
    owner.slots = slots;
    owner.count = 3;
    owner.client = token;
    for (int i = 0; i < 3; i++) {
        slots[i].base = base + i * UDP_BUF_SIZE;
        slots[i].capacity = UDP_BUF_SIZE;
        slots[i].owner = &owner;
        vectors[i].iov_base = slots[i].base;
        vectors[i].iov_len = UDP_BUF_SIZE;
        messages[i].msg_hdr.msg_name = &addresses[i];
        messages[i].msg_hdr.msg_iov = &vectors[i];
        messages[i].msg_hdr.msg_iovlen = 1;
    }
    hev_socks5_transfer_get (&before_in, &before_out);
    hev_socks5_transfer_clients (snapshot, NULL);
    before_ip_in = ip_in;
    before_ip_out = ip_out;
    /* A standalone successful size query is never a received byte. */
    assert (udp_buffer_datagram_size (reverse ? 11 : 10, slots) > 0);
    hev_socks5_transfer_get (&incoming, &outgoing);
    assert (incoming == before_in && outgoing == before_out);
    if (reverse)
        hev_socks5_udp_fwd_b (&self, 11, messages, 3, slots);
    else
        hev_socks5_udp_fwd_f (&self, 11, base, 3, &bound, slots);
    hev_socks5_transfer_get (&incoming, &outgoing);
    assert (incoming == before_in + (reverse ? consumed : 0));
    assert (outgoing == before_out + (reverse ? 0 : sent_bytes));
    hev_socks5_transfer_clients (snapshot, NULL);
    assert (ip_in == before_ip_in + (reverse ? consumed : 0));
    assert (ip_out == before_ip_out + (reverse ? 0 : sent_bytes));
    if (allocation_failure || tcp)
        assert (!self.timeout);
    if (allocation_failure || query_failure)
        assert (cursor == 1);
#if defined(__APPLE__)
    if (!reverse && retry && prefix == 1)
        assert (option_calls == 2 && delivered == 3 && calls == 2);
#else
    assert (!option_calls);
#endif
    allocation_budget = -1;
    udp_buffers_cleanup (&owner, udp_buffer_now () + 400 * UDP_NSEC_PER_SEC);
    assert (owner.client == token);
    for (int i = 0; i < 3; i++)
        assert (!slots[i].history && slots[i].capacity == UDP_BUF_SIZE);
    uint64_t after_in, after_out;
    hev_socks5_transfer_get (&after_in, &after_out);
    assert (after_in == incoming && after_out == outgoing);
}

int
main (void)
{
    void *token = register_client ();
    int cases = 0;
    for (int reverse = 0; reverse < 2; reverse++) {
        for (int prefix = -1; prefix <= 3; prefix++) {
            check (token, reverse, 0, prefix, EIO, 0, 0, 0, 0);
            cases++;
        }
        check (token, reverse, 0, 3, EIO, 0, 1, 0, 0);
        check (token, reverse, 0, 3, EIO, 0, 0, 1, 0);
        cases += 2;
    }
    for (unsigned int mask = 1; mask < 8; mask++) {
        check (token, 1, mask, -1, EIO, 0, 0, 0, 0);
        cases++;
    }
    check (token, 0, 0, 1, EMSGSIZE, 1, 0, 0, 0);
    check (token, 0, 0, 1, EMSGSIZE, 0, 0, 0, 0);
    check (token, 1, 0, 3, EIO, 0, 0, 0, 1);
    cases += 3;
    printf (
        "PASS: %d composed accounting cases; real Total/IP counters, dynamic "
        "buffers, peek exclusion, rejection/partial/allocation failure, "
        "Darwin send retry, TCP delivery failure and cleanup preservation\n",
        cases);
    return 0;
}
