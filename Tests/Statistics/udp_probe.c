/* Count at the actual forwarders; replace only their socket I/O boundaries. */
#define hev_task_io_socket_recvmmsg audit_recv
#define hev_task_io_socket_sendmmsg audit_send
#define getpeername audit_getpeername
#include "hev-socks5-udp.c"
#undef hev_task_io_socket_recvmmsg
#undef hev_task_io_socket_sendmmsg
#undef getpeername

#include <assert.h>
#include <stdio.h>

static int receive_result = 3;
static int send_result = 3;
static int io_error = EAGAIN;
static int bind_error;
static size_t lengths[3] = { 3, 7, 11 };

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

static int
bind_socket (HevSocks5 *self, int fd, const struct sockaddr *addr)
{
    (void)self;
    (void)addr;
    assert (fd == 11);
    return bind_error ? -1 : 0;
}

/* Model the client-facing socket identity used by the inherited peer filter.
 * Forwarders and counter assertions below remain the actual production paths. */
int
audit_getpeername (int fd, struct sockaddr *address, socklen_t *length)
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
audit_recv (int fd, void *messages, unsigned int num, int flags,
            HevTaskIOYielder yielder, void *data)
{
    struct mmsghdr *vec = messages;
    unsigned int i;
    const unsigned char header[] = { 0, 0, 0, 1, 127, 0, 0, 1, 0, 53 };

    (void)flags;
    (void)yielder;
    (void)data;
    assert (num == 3);
    if (receive_result < 0) {
        errno = io_error;
        return -1;
    }
    for (i = 0; i < (unsigned int)receive_result; i++) {
        struct iovec *iov = vec[i].msg_hdr.msg_iov;
        size_t offset = fd == 10 ? sizeof (header) : 0;
        assert (offset + lengths[i] <= iov->iov_len);
        if (fd == 10) {
            memcpy (iov->iov_base, header, sizeof (header));
            audit_getpeername (fd, vec[i].msg_hdr.msg_name,
                              &vec[i].msg_hdr.msg_namelen);
        } else {
            struct sockaddr_in6 addr = { 0 };
            assert (fd == 11);
            addr.sin6_family = AF_INET6;
            addr.sin6_port = htons (53);
            addr.sin6_addr.s6_addr[15] = 1;
#if defined(__APPLE__)
            addr.sin6_len = sizeof (addr);
#endif
            memcpy (vec[i].msg_hdr.msg_name, &addr, sizeof (addr));
        }
        memset ((char *)iov->iov_base + offset, 'x', lengths[i]);
        vec[i].msg_len = offset + lengths[i];
    }
    return receive_result;
}

int
audit_send (int fd, void *messages, unsigned int num, int flags,
            HevTaskIOYielder yielder, void *data)
{
    struct mmsghdr *vec = messages;
    unsigned int i;

    (void)flags;
    (void)yielder;
    (void)data;
    assert (num == (unsigned int)receive_result);
    for (i = 0; i < num; i++) {
        struct msghdr *msg = &vec[i].msg_hdr;
        assert (msg->msg_iovlen == (fd == 11 ? 1 : 3));
        assert (msg->msg_iov[msg->msg_iovlen - 1].iov_len == lengths[i]);
        /* Unsuccessful suffix entries must never contribute to Out. */
        vec[i].msg_len = 0xdeadbeef;
        if (send_result > 0 && i < (unsigned int)send_result)
            vec[i].msg_len = lengths[i] + (fd == 10 ? 22 : 0);
    }
    if (send_result < 0)
        errno = io_error;
    return send_result;
}

int
main (void)
{
    HevSocks5Class klass = { .base.iface = get_iface, .binder = bind_socket };
    HevSocks5 self = { .base.klass = &klass.base,
                       .type = HEV_SOCKS5_TYPE_UDP_IN_UDP,
                       .udp_associated = 1 };
    unsigned char buffer[UDP_BUF_SIZE * 3];
    struct sockaddr_in6 addresses[3];
    struct iovec iov[3];
    struct mmsghdr vec[3] = { 0 };
    uint64_t before_in, before_out, received, sent;
    int n, i, bound;

    for (n = -1; n <= 3; n++) {
        uint64_t expected = 0;
        send_result = n;
        for (i = 0; i < n; i++)
            expected += lengths[i];
        bound = 1;
        hev_socks5_transfer_get (&before_in, &before_out);
        hev_socks5_udp_fwd_f (&self, 11, buffer, 3, &bound);
        hev_socks5_transfer_get (&received, &sent);
        assert (received == before_in && sent == before_out + expected);
    }
    puts (
        "PASS: UDP Out counts only the successful prefix, no headers or stale suffix");

    receive_result = -1;
    hev_socks5_transfer_get (&before_in, &before_out);
    for (i = 0; i < 2; i++) {
        io_error = i ? EIO : EAGAIN;
        hev_socks5_udp_fwd_f (&self, 11, buffer, 3, &bound);
    }
    receive_result = 3;
    bind_error = 1;
    bound = 0;
    hev_socks5_udp_fwd_f (&self, 11, buffer, 3, &bound);
    hev_socks5_transfer_get (&received, &sent);
    assert (received == before_in && sent == before_out);
    puts (
        "PASS: client receives, failed receives and failed binds add no external bytes");

    for (i = 0; i < 3; i++) {
        iov[i].iov_base = buffer + UDP_BUF_SIZE * i;
        iov[i].iov_len = UDP_BUF_SIZE;
        vec[i].msg_hdr.msg_name = &addresses[i];
        vec[i].msg_hdr.msg_iov = &iov[i];
        vec[i].msg_hdr.msg_iovlen = 1;
    }
    for (n = -1; n <= 3; n++) {
        send_result = n;
        hev_socks5_transfer_get (&before_in, &before_out);
        hev_socks5_udp_fwd_b (&self, 11, vec, 3);
        hev_socks5_transfer_get (&received, &sent);
        assert (received == before_in + 21 && sent == before_out);
    }
    puts (
        "PASS: UDP In survives partial or failed client delivery without double counting");
    receive_result = -1;
    hev_socks5_transfer_get (&before_in, &before_out);
    for (i = 0; i < 2; i++) {
        io_error = i ? EIO : EAGAIN;
        hev_socks5_udp_fwd_b (&self, 11, vec, 3);
    }
    receive_result = send_result = 1;
    lengths[0] = 0;
    hev_socks5_udp_fwd_b (&self, 11, vec, 3);
    hev_socks5_transfer_get (&received, &sent);
    assert (received == before_in && sent == before_out);
    puts (
        "PASS: failed receives and zero-byte payloads add no artificial traffic");
    return 0;
}
