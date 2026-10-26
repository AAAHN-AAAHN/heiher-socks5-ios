/* Linux linker wrappers: deterministic kernel responses and failures.
 * These are separate from the mandatory real ICMP loopback execution. */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <netinet/in.h>

#include "hev-icmp-engine.h"

typedef struct
{
    int family;
    int peer;
} Endpoint;
static Endpoint endpoints[4096];
atomic_int icmp_test_suppress;
atomic_int icmp_test_send_error;
atomic_int icmp_test_truncate;
atomic_int icmp_test_wrong_id;
atomic_int icmp_test_open_error;
atomic_int icmp_test_short_send;
atomic_int icmp_test_opened;
atomic_int icmp_test_live;

int __real_socket (int, int, int);
int __real_close (int);
int __real_bind (int, const struct sockaddr *, socklen_t);
int __real_setsockopt (int, int, int, const void *, socklen_t);
int __real_getsockname (int, struct sockaddr *, socklen_t *);
ssize_t __real_sendto (int, const void *, size_t, int, const struct sockaddr *,
                       socklen_t);
ssize_t __real_recvmsg (int, struct msghdr *, int);

static Endpoint *
endpoint (int fd)
{
    return fd >= 0 && fd < 4096 && endpoints[fd].family ? &endpoints[fd] : NULL;
}

int
__wrap_socket (int family, int type, int protocol)
{
    int pair[2];
    if (type != SOCK_DGRAM ||
        (protocol != IPPROTO_ICMP && protocol != IPPROTO_ICMPV6))
        return __real_socket (family, type, protocol);
    if (atomic_load (&icmp_test_open_error)) {
        errno = EACCES;
        return -1;
    }
    if (socketpair (AF_UNIX, SOCK_DGRAM, 0, pair))
        return -1;
    assert (pair[0] < 4096);
    endpoints[pair[0]].family = family;
    endpoints[pair[0]].peer = pair[1];
    atomic_fetch_add (&icmp_test_opened, 1);
    atomic_fetch_add (&icmp_test_live, 1);
    return pair[0];
}

int
__wrap_close (int fd)
{
    Endpoint *e = endpoint (fd);
    if (e) {
        __real_close (e->peer);
        e->family = 0;
        atomic_fetch_sub (&icmp_test_live, 1);
    }
    return __real_close (fd);
}

int
__wrap_bind (int fd, const struct sockaddr *addr, socklen_t len)
{
    return endpoint (fd) ? 0 : __real_bind (fd, addr, len);
}

int
__wrap_setsockopt (int fd, int level, int name, const void *value,
                   socklen_t len)
{
    return endpoint (fd) ? 0 : __real_setsockopt (fd, level, name, value, len);
}

int
__wrap_getsockname (int fd, struct sockaddr *addr, socklen_t *len)
{
    Endpoint *e = endpoint (fd);
    if (!e)
        return __real_getsockname (fd, addr, len);
    memset (addr, 0, *len);
    addr->sa_family = e->family;
    if (e->family == AF_INET) {
        ((struct sockaddr_in *)addr)->sin_port = htons (0xbeef);
        *len = sizeof (struct sockaddr_in);
    } else {
        ((struct sockaddr_in6 *)addr)->sin6_port = htons (0xbeef);
        *len = sizeof (struct sockaddr_in6);
    }
    return 0;
}

ssize_t
__wrap_sendto (int fd, const void *data, size_t len, int flags,
               const struct sockaddr *addr, socklen_t addrlen)
{
    Endpoint *e = endpoint (fd);
    const unsigned char *in = data;
    unsigned char *reply;
    uint16_t checksum;
    if (!e)
        return __real_sendto (fd, data, len, flags, addr, addrlen);
    if (atomic_load (&icmp_test_send_error)) {
        errno = atomic_load (&icmp_test_send_error);
        return -1;
    }
    if (atomic_load (&icmp_test_short_send))
        return 4;
    assert (len >= 8 && in[0] == (e->family == AF_INET ? 8 : 128) && !in[1]);
    assert (in[4] == 0xbe && in[5] == 0xef); /* Kernel-selected identifier. */
    if (e->family == AF_INET)
        assert (!hev_icmp_checksum (in, len));
    if (atomic_load (&icmp_test_suppress))
        return len;
    reply = malloc (len);
    assert (reply);
    memcpy (reply, data, len);
    reply[0] = e->family == AF_INET ? 0 : 129;
    if (atomic_load (&icmp_test_wrong_id))
        reply[4] ^= 1;
    reply[2] = reply[3] = 0;
    checksum = hev_icmp_checksum (reply, len);
    reply[2] = checksum >> 8;
    reply[3] = checksum;
    assert (write (e->peer, reply, len) == (ssize_t)len);
    free (reply);
    return len;
}

ssize_t
__wrap_recvmsg (int fd, struct msghdr *message, int flags)
{
    Endpoint *e = endpoint (fd);
    struct msghdr real;
    struct iovec iov;
    struct cmsghdr *c;
    ssize_t n;
    if (!e)
        return __real_recvmsg (fd, message, flags);
    real = *message;
    real.msg_name = NULL;
    real.msg_namelen = 0;
    real.msg_control = NULL;
    real.msg_controllen = 0;
    iov = *message->msg_iov;
    if (atomic_load (&icmp_test_truncate) && iov.iov_len > 12)
        iov.iov_len = 12;
    real.msg_iov = &iov;
    n = __real_recvmsg (fd, &real, flags);
    if (n < 0)
        return n;
    message->msg_flags = real.msg_flags;
    memset (message->msg_name, 0, message->msg_namelen);
    c = CMSG_FIRSTHDR (message);
    assert (c);
    if (e->family == AF_INET) {
        struct sockaddr_in *peer = message->msg_name;
        struct in_pktinfo pi = { 0 };
        peer->sin_family = AF_INET;
        inet_pton (AF_INET, "127.0.0.1", &peer->sin_addr);
        message->msg_namelen = sizeof (*peer);
        pi.ipi_addr = peer->sin_addr;
        c->cmsg_level = IPPROTO_IP;
        c->cmsg_type = IP_PKTINFO;
        c->cmsg_len = CMSG_LEN (sizeof (pi));
        memcpy (CMSG_DATA (c), &pi, sizeof (pi));
        message->msg_controllen = CMSG_SPACE (sizeof (pi));
    } else {
        struct sockaddr_in6 *peer = message->msg_name;
        struct in6_pktinfo pi = { 0 };
        peer->sin6_family = AF_INET6;
        inet_pton (AF_INET6, "::1", &peer->sin6_addr);
        message->msg_namelen = sizeof (*peer);
        pi.ipi6_addr = peer->sin6_addr;
        c->cmsg_level = IPPROTO_IPV6;
        c->cmsg_type = IPV6_PKTINFO;
        c->cmsg_len = CMSG_LEN (sizeof (pi));
        memcpy (CMSG_DATA (c), &pi, sizeof (pi));
        message->msg_controllen = CMSG_SPACE (sizeof (pi));
    }
    return n;
}
