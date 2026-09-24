/* Exercise the actual patched translation unit; replace only OS I/O boundaries. */
#define recv audit_control_recv
#define hev_socks5_task_io_yielder audit_yield
#define connect audit_connect
#define getpeername audit_getpeername
#define hev_task_io_socket_recvmmsg audit_recv
#define hev_task_io_socket_sendmmsg audit_send
#include "hev-socks5-udp.c"
#undef recv
#undef hev_socks5_task_io_yielder
#undef connect
#undef getpeername
#undef hev_task_io_socket_recvmmsg
#undef hev_task_io_socket_sendmmsg

#include <assert.h>
#include <stdint.h>
#include <stdio.h>

static int foreign_batches;
static int retry_yields;
static int empty_after_foreign;
static int cancel_yield;

static int family = AF_INET;
static int receive_error;
static int connect_error;
static int connect_calls;
static int send_calls;
static struct sockaddr_in6 peer;

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

ssize_t
audit_control_recv (int fd, void *buf, size_t length, int flags)
{
    (void)fd;
    (void)buf;
    (void)length;
    (void)flags;
    errno = EAGAIN;
    return -1;
}

int
audit_yield (HevTaskYieldType type, void *data)
{
    (void)data;
    assert (type == HEV_TASK_YIELD);
    retry_yields++;
    if (cancel_yield) {
        errno = ECANCELED;
        return -1;
    }
    return 0;
}

int
audit_getpeername (int fd, struct sockaddr *addr, socklen_t *length)
{
    struct sockaddr_in6 expected = { 0 };
    assert (fd == 0 || fd == 10);
    assert (*length >= sizeof (expected));
    expected.sin6_family = AF_INET6;
    expected.sin6_port = htons (fd == 10 ? 5300 : 33000);
#if defined(__APPLE__)
    expected.sin6_len = sizeof (expected);
#endif
    if (family == AF_INET) {
        expected.sin6_addr.s6_addr[10] = 0xff;
        expected.sin6_addr.s6_addr[11] = 0xff;
        expected.sin6_addr.s6_addr[12] = 127;
    }
    expected.sin6_addr.s6_addr[15] = 1;
    memcpy (addr, &expected, sizeof (expected));
    *length = sizeof (expected);
    return 0;
}

int
audit_connect (int fd, const struct sockaddr *addr, socklen_t length)
{
    assert (fd == 10 && length == sizeof (peer));
    memcpy (&peer, addr, sizeof (peer));
    assert (peer.sin6_family == AF_INET6);
    connect_calls++;
    if (connect_error) {
        errno = EACCES;
        return -1;
    }
    return 0;
}

int
audit_recv (int fd, void *messages, unsigned int num, int flags,
            HevTaskIOYielder yielder, void *data)
{
    struct mmsghdr *vec = messages;
    struct sockaddr_in v4 = { 0 };
    struct sockaddr_in6 v6 = { 0 };
    unsigned int i;
    const unsigned char packet[] = { 0, 0, 0, 1, 127, 0, 0, 1, 0, 53, 42 };

    (void)flags;
    (void)yielder;
    (void)data;
    assert (num > 0);
    v4.sin_family = AF_INET;
    v4.sin_port = htons (5300);
    v4.sin_addr.s_addr = htonl (0x7f000001);
    v6.sin6_family = AF_INET6;
    v6.sin6_port = htons (5300);
    v6.sin6_addr.s6_addr[15] = 1;
#if defined(__APPLE__)
    v4.sin_len = sizeof (v4);
    v6.sin6_len = sizeof (v6);
#endif
    for (i = 0; i < num; i++) {
        if (fd == 11)
            assert (vec[i].msg_hdr.msg_namelen == sizeof (v6));
    }
    if (receive_error || (empty_after_foreign && !foreign_batches)) {
        errno = EAGAIN;
        return -1;
    }
    if (foreign_batches) {
        foreign_batches--;
        v4.sin_addr.s_addr = htonl (0x7f000002);
        v6.sin6_addr.s6_addr[15] = 2;
    }
    if (vec[0].msg_hdr.msg_name) {
        assert (vec[0].msg_hdr.msg_namelen == sizeof (v6));
        if (family == AF_INET) {
            memcpy (vec[0].msg_hdr.msg_name, &v4, sizeof (v4));
            vec[0].msg_hdr.msg_namelen = sizeof (v4);
        } else {
            memcpy (vec[0].msg_hdr.msg_name, &v6, sizeof (v6));
            vec[0].msg_hdr.msg_namelen = sizeof (v6);
        }
    }
    assert (vec[0].msg_hdr.msg_iov[0].iov_len >= sizeof (packet));
    memcpy (vec[0].msg_hdr.msg_iov[0].iov_base, packet, sizeof (packet));
    vec[0].msg_len = sizeof (packet);
    return 1;
}

int
audit_send (int fd, void *messages, unsigned int num, int flags,
            HevTaskIOYielder yielder, void *data)
{
    struct mmsghdr *vec = messages;
    HevSocks5Addr *addr = vec[0].msg_hdr.msg_iov[1].iov_base;
    const unsigned char ipv4[] = { 127, 0, 0, 1 };
    const unsigned char zero[3] = { 0 };

    (void)flags;
    (void)yielder;
    (void)data;
    assert (fd == 10 && num == 1);
    assert (!memcmp (vec[0].msg_hdr.msg_iov[0].iov_base, zero, 3));
    assert (vec[0].msg_hdr.msg_iov[2].iov_len == 11);
    if (family == AF_INET) {
        assert (addr->atype == HEV_SOCKS5_ADDR_TYPE_IPV4);
        assert (addr->ipv4.port == htons (5300));
        assert (!memcmp (addr->ipv4.addr, ipv4, sizeof (ipv4)));
    } else {
        const unsigned char ipv6[16] = { [15] = 1 };
        assert (addr->atype == HEV_SOCKS5_ADDR_TYPE_IPV6);
        assert (addr->ipv6.port == htons (5300));
        assert (!memcmp (addr->ipv6.addr, ipv6, sizeof (ipv6)));
    }
    send_calls++;
    return num;
}

static void
addresses (void)
{
    struct
    {
        uint64_t before;
        struct sockaddr_in6 addr;
        uint64_t after;
    } guarded;
    struct sockaddr_in6 expected;
    struct sockaddr_in v4;
    uint32_t i;

    for (i = 0; i <= UINT16_MAX; i++) {
        memset (&guarded, 0xa5, sizeof (guarded));
        memset (&v4, 0, sizeof (v4));
        v4.sin_family = AF_INET;
        v4.sin_port = htons (i);
        v4.sin_addr.s_addr = htonl (0xc0000000U | i);
#if defined(__APPLE__)
        v4.sin_len = sizeof (v4);
#endif
        memcpy (&guarded.addr, &v4, sizeof (v4));
        hev_socks5_udp_addr_normalize (&guarded.addr);
        assert (guarded.before == UINT64_C (0xa5a5a5a5a5a5a5a5));
        assert (guarded.after == UINT64_C (0xa5a5a5a5a5a5a5a5));
        assert (guarded.addr.sin6_family == AF_INET6);
        assert (guarded.addr.sin6_port == v4.sin_port);
        assert (IN6_IS_ADDR_V4MAPPED (&guarded.addr.sin6_addr));
        assert (!memcmp (&guarded.addr.sin6_addr.s6_addr[12], &v4.sin_addr, 4));
        assert (!guarded.addr.sin6_flowinfo && !guarded.addr.sin6_scope_id);
#if defined(__APPLE__)
        assert (guarded.addr.sin6_len == sizeof (guarded.addr));
#endif
        expected = guarded.addr;
        hev_socks5_udp_addr_normalize (&guarded.addr);
        assert (!memcmp (&expected, &guarded.addr, sizeof (expected)));
        guarded.addr.sin6_addr.s6_addr[0] = 0xfe;
        guarded.addr.sin6_addr.s6_addr[1] = 0x80;
        guarded.addr.sin6_flowinfo = i;
        guarded.addr.sin6_scope_id = i;
        expected = guarded.addr;
        hev_socks5_udp_addr_normalize (&guarded.addr);
        assert (!memcmp (&expected, &guarded.addr, sizeof (expected)));
    }
    puts (
        "PASS: 65536 port values; mapping, canaries, idempotence and IPv6 preservation");
}

int
main (void)
{
    HevObjectClass klass = { .iface = get_iface };
    HevSocks5 self = { .base.klass = &klass,
                       .type = HEV_SOCKS5_TYPE_UDP_IN_UDP };
    unsigned char buffers[10][64];
    HevSocks5UDPMsg msgs[10];
    struct sockaddr_in6 addrs[10];
    struct iovec iov[10];
    struct mmsghdr vec[10] = { 0 };
    int i, pass;

    addresses ();
    for (pass = 0; pass < 2; pass++) {
        self.udp_associated = 0;
        family = pass ? AF_INET6 : AF_INET;
        for (i = 0; i < 10; i++) {
            msgs[i].buf = buffers[i];
            msgs[i].len = sizeof (buffers[i]);
        }
        receive_error = 1;
        assert (hev_socks5_udp_recvmmsg_udp (&self, msgs, 10, 1) == -1);
        assert (!self.udp_associated && connect_calls == pass * 2);
        receive_error = 0;
        connect_error = 1;
        assert (hev_socks5_udp_recvmmsg_udp (&self, msgs, 10, 1) == -1);
        assert (!self.udp_associated && errno == EACCES);
        connect_error = 0;
        assert (hev_socks5_udp_recvmmsg_udp (&self, msgs, 10, 1) == 1);
        assert (self.udp_associated && msgs[0].len == 1);
        assert (peer.sin6_port == htons (5300));
        assert (!!IN6_IS_ADDR_V4MAPPED (&peer.sin6_addr) == !pass);
    }
    puts (
        "PASS: actual first-peer receive path; EAGAIN/connect failure preserve state");
    for (pass = 0; pass < 2; pass++) {
        family = pass ? AF_INET6 : AF_INET;
        for (i = 0; i < 3; i++) {
            int before = connect_calls;
            int result;

            self.udp_associated = 0;
            msgs[0].buf = buffers[0];
            msgs[0].len = sizeof (buffers[0]);
            foreign_batches = 2;
            retry_yields = 0;
            empty_after_foreign = i == 1;
            cancel_yield = i == 2;
            result = hev_socks5_udp_recvmmsg_udp (&self, msgs, 1, 1);
            if (i == 0) {
                assert (result == 1 && retry_yields == 2);
                assert (connect_calls == before + 1 && msgs[0].len == 1);
            } else if (i == 1) {
                assert (result == -1 && errno == EAGAIN && retry_yields == 2);
                assert (connect_calls == before && !self.udp_associated);
            } else {
                assert (result == -1 && errno == ECANCELED && retry_yields == 1);
                assert (connect_calls == before && !self.udp_associated);
            }
        }
    }
    foreign_batches = empty_after_foreign = cancel_yield = 0;
    puts (
        "PASS: rejected batches yield and drain; only real empty queues return EAGAIN; cancellation wins");
    for (i = 0; i < 10; i++) {
        iov[i].iov_base = buffers[i];
        iov[i].iov_len = sizeof (buffers[i]);
        vec[i].msg_hdr.msg_name = &addrs[i];
        vec[i].msg_hdr.msg_iov = &iov[i];
        vec[i].msg_hdr.msg_iovlen = 1;
    }
    for (pass = 0; pass < 20; pass++) {
        family = pass % 2 ? AF_INET6 : AF_INET;
        for (i = 0; i < 10; i++)
            vec[i].msg_hdr.msg_namelen = sizeof (struct sockaddr_in);
        receive_error = 1;
        assert (hev_socks5_udp_fwd_b (&self, 11, vec, 10) == 0);
        receive_error = 0;
        assert (hev_socks5_udp_fwd_b (&self, 11, vec, 10) == 1);
    }
    assert (send_calls == 20);
    puts (
        "PASS: actual reply path; all 10 capacities reset, mixed families serialized correctly");
    return 0;
}
