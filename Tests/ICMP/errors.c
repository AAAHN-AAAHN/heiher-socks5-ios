/* Deterministic packet/error-queue inputs around the actual production
 * engine. This runs on Linux and Darwin; it does not claim real socket I/O. */
#define _GNU_SOURCE
#ifdef __APPLE__
#define __APPLE_USE_RFC_3542
#endif
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#ifdef __linux__
#include <linux/errqueue.h>
#endif

#include "hev-task.h"
#include "hev-task-system.h"
#include "hev-icmp-engine.h"

typedef struct
{
    unsigned char data[512];
    size_t len;
    int queued, flags, origin, error, type, code;
    uint32_t info;
    struct sockaddr_storage peer, target, local;
    socklen_t address_len;
    unsigned int interface;
    unsigned int quote_len;
    int unknown_peer;
} Packet;

typedef struct
{
    int fd, other, family;
    Packet packets[160];
    size_t count;
} Endpoint;

typedef struct
{
    int active, terminals, error, origin, type, code;
    uint32_t info;
    struct sockaddr_storage peer, local;
    socklen_t peer_len, local_len;
} Result;

static Endpoint endpoints[2];
static unsigned long received, sent, unknown;
static unsigned int read_calls, send_calls;
static int send_failure, fail_once, inject_on_failure;
static Packet raced_error;

static Endpoint *
find_endpoint (int fd)
{
    for (unsigned int i = 0; i < 2; i++)
        if (endpoints[i].fd == fd)
            return &endpoints[i];
    abort ();
}

static int
fixture_socket (int family, int type, int protocol)
{
    int pair[2], index = family == AF_INET6;
    Endpoint *ep = &endpoints[index];
    assert (type == SOCK_DGRAM);
    assert (protocol == (index ? IPPROTO_ICMPV6 : IPPROTO_ICMP));
    assert (!ep->family && !socketpair (AF_UNIX, SOCK_DGRAM, 0, pair));
    memset (ep, 0, sizeof (*ep));
    ep->fd = pair[0];
    ep->other = pair[1];
    ep->family = family;
    return ep->fd;
}

static int
fixture_close (int fd)
{
    Endpoint *ep = find_endpoint (fd);
    assert (!close (ep->other));
    memset (ep, 0, sizeof (*ep));
    ep->fd = -1;
    return close (fd);
}

static int
fixture_setsockopt (int fd, int level, int option, const void *value,
                    socklen_t len)
{
    (void)find_endpoint (fd);
    (void)level;
    (void)option;
    (void)value;
    (void)len;
    return 0;
}

static int
fixture_getsockname (int fd, struct sockaddr *address, socklen_t *len)
{
    Endpoint *ep = find_endpoint (fd);
    memset (address, 0, *len);
    address->sa_family = ep->family;
    if (ep->family == AF_INET) {
        ((struct sockaddr_in *)address)->sin_port = htons (0xbeef);
        *len = sizeof (struct sockaddr_in);
    } else {
        ((struct sockaddr_in6 *)address)->sin6_port = htons (0xbeef);
        *len = sizeof (struct sockaddr_in6);
    }
    return 0;
}

static void
enqueue (int index, Packet packet)
{
    Endpoint *ep = &endpoints[index];
    assert (ep->family && ep->count < 160);
    ep->packets[ep->count++] = packet;
}

static ssize_t
fixture_sendto (int fd, const void *bytes, size_t len, int flags,
                const struct sockaddr *target, socklen_t target_len)
{
    Endpoint *ep = find_endpoint (fd);
    const unsigned char *data = bytes;
    (void)flags;
    assert (target->sa_family == ep->family && target_len);
    assert (len >= 8 && data[0] == (ep->family == AF_INET ? 8 : 128));
    send_calls++;
    if (send_failure) {
        int failure = send_failure;
        if (inject_on_failure) {
            enqueue (ep->family == AF_INET6, raced_error);
            inject_on_failure = 0;
        }
        if (fail_once)
            send_failure = 0;
        errno = failure;
        return -1;
    }
    return len;
}

static ssize_t
fixture_recvmsg (int fd, struct msghdr *msg, int flags)
{
    Endpoint *ep = find_endpoint (fd);
    int queued = 0;
    size_t i, copied, used = 0;
    Packet p;
    struct cmsghdr *c;
#ifdef __linux__
    queued = !!(flags & MSG_ERRQUEUE);
#else
    (void)flags;
#endif
    for (i = 0; i < ep->count && ep->packets[i].queued != queued; i++)
        ;
    if (i == ep->count) {
        errno = EAGAIN;
        return -1;
    }
    p = ep->packets[i];
    memmove (ep->packets + i, ep->packets + i + 1,
             (--ep->count - i) * sizeof (p));
    copied = p.len < msg->msg_iov->iov_len ? p.len : msg->msg_iov->iov_len;
    memcpy (msg->msg_iov->iov_base, p.data, copied);
    assert (msg->msg_namelen >= p.address_len);
    memcpy (msg->msg_name, queued ? &p.target : &p.peer, p.address_len);
    msg->msg_namelen = p.address_len;
    msg->msg_flags = p.flags;
    c = CMSG_FIRSTHDR (msg);
    assert (c);
#ifdef __linux__
    if (queued) {
        struct sock_extended_err ee = { 0 };
        ee.ee_origin = p.origin;
        ee.ee_errno = p.error;
        ee.ee_type = p.type;
        ee.ee_code = p.code;
        ee.ee_info = p.info;
#ifdef SO_EE_RFC4884_FLAG_INVALID
        ee.ee_rfc4884.len = p.quote_len;
#endif
        c->cmsg_level = ep->family == AF_INET ? IPPROTO_IP : IPPROTO_IPV6;
        c->cmsg_type = ep->family == AF_INET ? IP_RECVERR : IPV6_RECVERR;
        c->cmsg_len = CMSG_LEN (sizeof (ee) + p.address_len);
        assert (c->cmsg_len <= msg->msg_controllen);
        memcpy (CMSG_DATA (c), &ee, sizeof (ee));
        if (p.unknown_peer)
            memset (CMSG_DATA (c) + sizeof (ee), 0, p.address_len);
        else
            memcpy (CMSG_DATA (c) + sizeof (ee), &p.peer, p.address_len);
        used = CMSG_SPACE (sizeof (ee) + p.address_len);
        msg->msg_flags |= MSG_ERRQUEUE;
        if (p.origin == SO_EE_ORIGIN_LOCAL || !p.local.ss_family) {
            msg->msg_controllen = used;
            return copied;
        }
        assert (used + CMSG_SPACE (sizeof (struct in6_pktinfo)) <=
                msg->msg_controllen);
        c = (void *)((unsigned char *)c + used);
    }
#endif
    if (ep->family == AF_INET) {
#ifdef __APPLE__
        c->cmsg_level = IPPROTO_IP;
        c->cmsg_type = IP_RECVDSTADDR;
        c->cmsg_len = CMSG_LEN (sizeof (struct in_addr));
        memcpy (CMSG_DATA (c), &((struct sockaddr_in *)&p.local)->sin_addr, 4);
        msg->msg_controllen = CMSG_SPACE (sizeof (struct in_addr));
#else
        struct in_pktinfo pi = { 0 };
        pi.ipi_addr = ((struct sockaddr_in *)&p.local)->sin_addr;
        pi.ipi_ifindex = p.interface;
        c->cmsg_level = IPPROTO_IP;
        c->cmsg_type = IP_PKTINFO;
        c->cmsg_len = CMSG_LEN (sizeof (pi));
        memcpy (CMSG_DATA (c), &pi, sizeof (pi));
        msg->msg_controllen = CMSG_SPACE (sizeof (pi));
#endif
    } else {
        struct in6_pktinfo pi = { 0 };
        pi.ipi6_addr = ((struct sockaddr_in6 *)&p.local)->sin6_addr;
        pi.ipi6_ifindex = p.interface;
        c->cmsg_level = IPPROTO_IPV6;
        c->cmsg_type = IPV6_PKTINFO;
        c->cmsg_len = CMSG_LEN (sizeof (pi));
        memcpy (CMSG_DATA (c), &pi, sizeof (pi));
        msg->msg_controllen = CMSG_SPACE (sizeof (pi));
    }
    msg->msg_controllen += used;
    return copied;
}

/* Compile the exact prepared production source. Only the six OS operations
 * above are replaced; parsing, request lookup, lifecycle and limits are real. */
#define socket fixture_socket
#define close fixture_close
#define setsockopt fixture_setsockopt
#define getsockname fixture_getsockname
#define sendto fixture_sendto
#define recvmsg fixture_recvmsg
#include ICMP_ENGINE_SOURCE
#undef socket
#undef close
#undef setsockopt
#undef getsockname
#undef sendto
#undef recvmsg

static void
put16 (unsigned char *p, unsigned int n)
{
    p[0] = n >> 8;
    p[1] = n;
}

static uint16_t
packet_checksum (Packet *p, int index)
{
    uint32_t sum = 0;
    if (index) {
        const unsigned char *a =
            (const void *)&((struct sockaddr_in6 *)&p->peer)->sin6_addr;
        const unsigned char *b =
            (const void *)&((struct sockaddr_in6 *)&p->local)->sin6_addr;
        for (size_t i = 0; i < 16; i += 2)
            sum += ((unsigned int)a[i] << 8) + a[i + 1] +
                   ((unsigned int)b[i] << 8) + b[i + 1];
        sum += p->len + IPPROTO_ICMPV6;
    }
    for (size_t i = 0; i < p->len; i++)
        sum += (unsigned int)p->data[i] << ((i & 1) ? 0 : 8);
    while (sum >> 16)
        sum = (sum & 65535) + (sum >> 16);
    return ~sum;
}

static void
seal_packet (Packet *p, int index)
{
    p->data[2] = p->data[3] = 0;
    put16 (p->data + 2, packet_checksum (p, index));
}

static Packet
error_packet (HevIcmpRequest *r, int queued, int type, int code, uint32_t info,
              int extensions)
{
    Packet p = { 0 };
    int index = r->destination.ss_family == AF_INET6;
    size_t extra = extensions ? 44 : 0;
    unsigned char *ip = p.data + 8;
    p.queued = queued;
    p.target = r->destination;
    p.address_len = r->destination_len;
    p.peer.ss_family = p.local.ss_family = r->destination.ss_family;
    p.interface = 7;
    p.type = type;
    p.code = code;
    p.info = info;
    p.error = (index ? type == 2 : type == 3 && code == 4) ? EMSGSIZE :
                                                             EHOSTUNREACH;
    if (index) {
        inet_pton (AF_INET6, "2001:db8::f",
                   &((struct sockaddr_in6 *)&p.peer)->sin6_addr);
        inet_pton (AF_INET6, "2001:db8::1",
                   &((struct sockaddr_in6 *)&p.local)->sin6_addr);
#ifdef __APPLE__
        ((struct sockaddr_in6 *)&p.peer)->sin6_len =
            sizeof (struct sockaddr_in6);
        ((struct sockaddr_in6 *)&p.local)->sin6_len =
            sizeof (struct sockaddr_in6);
#endif
    } else {
        inet_pton (AF_INET, "192.0.2.254",
                   &((struct sockaddr_in *)&p.peer)->sin_addr);
        inet_pton (AF_INET, "192.0.2.1",
                   &((struct sockaddr_in *)&p.local)->sin_addr);
#ifdef __APPLE__
        ((struct sockaddr_in *)&p.peer)->sin_len = sizeof (struct sockaddr_in);
        ((struct sockaddr_in *)&p.local)->sin_len = sizeof (struct sockaddr_in);
#endif
    }
    if (queued) {
#ifdef __linux__
        p.origin = index ? SO_EE_ORIGIN_ICMP6 : SO_EE_ORIGIN_ICMP;
#endif
        p.len = r->len;
        assert (p.len <= sizeof (p.data));
        memcpy (p.data, r->echo, p.len);
        return p;
    }
    p.data[0] = type;
    p.data[1] = code;
    p.len = 8 + (index ? 40 + extra : 20) + r->len;
    assert (p.len <= sizeof (p.data));
    if (index) {
        ip[0] = 0x60;
        put16 (ip + 4, r->len + extra);
        ip[6] = extensions ? IPPROTO_HOPOPTS : IPPROTO_ICMPV6;
        memcpy (ip + 8, &((struct sockaddr_in6 *)&p.local)->sin6_addr, 16);
        memcpy (ip + 24, &((struct sockaddr_in6 *)&p.target)->sin6_addr, 16);
        if (extensions) {
            ip[40] = IPPROTO_ROUTING;
            ip[48] = IPPROTO_DSTOPTS;
            ip[56] = IPPROTO_FRAGMENT;
            ip[64] = IPPROTO_AH;
            ip[72] = IPPROTO_ICMPV6;
            ip[73] = 1;
        }
        memcpy (ip + 40 + extra, r->echo, r->len);
        if (type == 2 || type == 4) {
            put16 (p.data + 4, info >> 16);
            put16 (p.data + 6, info);
        }
    } else {
        ip[0] = 0x45;
        put16 (ip + 2, 20 + r->len);
        ip[9] = IPPROTO_ICMP;
        memcpy (ip + 12, &((struct sockaddr_in *)&p.local)->sin_addr, 4);
        memcpy (ip + 16, &((struct sockaddr_in *)&p.target)->sin_addr, 4);
        memcpy (ip + 20, r->echo, r->len);
        if (type == 3 && code == 4)
            put16 (p.data + 6, info);
        else if (type == 12)
            p.data[4] = info;
    }
    seal_packet (&p, index);
#ifdef __APPLE__
    if (!index && ((type == 3 && code <= 15) || (type == 11 && code <= 1) ||
                   (type == 12 && code <= 1))) {
        uint16_t host_length = 20 + r->len;
        memcpy (ip + 2, &host_length, 2);
    }
#endif
    return p;
}

static int
fixture_binder (int fd, int family, uint16_t identifier, void *context)
{
    (void)fd;
    (void)family;
    (void)identifier;
    (void)context;
    return 0;
}

static int
fixture_active (void *context)
{
    return ((Result *)context)->active;
}

static void
fixture_observe (const struct sockaddr *peer, socklen_t peer_len, size_t bytes,
                 int writing, void *context)
{
    (void)context;
    assert (bytes);
    if (writing) {
        assert (peer && peer_len);
        sent += bytes;
    } else {
        received += bytes;
        read_calls++;
        if (!peer) {
            assert (!peer_len);
            unknown += bytes;
        } else {
            struct sockaddr_storage expected = { 0 };
            expected.ss_family = peer->sa_family;
            if (peer->sa_family == AF_INET)
                inet_pton (AF_INET, "192.0.2.254",
                           &((struct sockaddr_in *)&expected)->sin_addr);
            else
                inet_pton (AF_INET6, "2001:db8::f",
                           &((struct sockaddr_in6 *)&expected)->sin6_addr);
#ifdef __APPLE__
            if (peer->sa_family == AF_INET)
                ((struct sockaddr_in *)&expected)->sin_len =
                    sizeof (struct sockaddr_in);
            else
                ((struct sockaddr_in6 *)&expected)->sin6_len =
                    sizeof (struct sockaddr_in6);
#endif
            assert (peer_len && !memcmp (peer, &expected, peer_len));
        }
    }
    errno = EDOM;
}

static void
fixture_complete (HevIcmpRequest *r, int error, const struct sockaddr *peer,
                  socklen_t peer_len, const struct sockaddr *local,
                  socklen_t local_len, const unsigned char *echo, size_t len,
                  void *context)
{
    Result *result = r->context;
    (void)context;
    assert (++result->terminals == 1);
    result->local_len = local_len;
    if (local && local_len)
        memcpy (&result->local, local, local_len);
    result->error = error;
    result->peer_len = peer_len;
    if (peer)
        memcpy (&result->peer, peer, peer_len);
    if (error)
        assert (!echo && !len);
#ifdef ICMP_EXPECT_METADATA
    result->origin = r->error_origin;
    result->type = r->icmp_type;
    result->code = r->icmp_code;
    result->info = r->icmp_info;
#endif
}

static HevIcmpRequest *
fixture_request_sized (HevIcmpEngine *e, int index, Result *result, int scoped,
                       size_t size)
{
    struct sockaddr_storage target = { 0 };
    unsigned char echo[256];
    socklen_t len;
    HevIcmpRequest *r;
    assert (size >= 8 && size <= sizeof (echo));
    result->active = 1;
    if (index) {
        struct sockaddr_in6 *a = (void *)&target;
        a->sin6_family = AF_INET6;
        inet_pton (AF_INET6, scoped ? "fe80::2" : "2001:db8::2", &a->sin6_addr);
        a->sin6_scope_id = scoped ? 7 : 0;
        len = sizeof (*a);
    } else {
        struct sockaddr_in *a = (void *)&target;
        a->sin_family = AF_INET;
        inet_pton (AF_INET, "192.0.2.2", &a->sin_addr);
        len = sizeof (*a);
    }
    hev_icmp_echo (echo, target.ss_family, 0x12345678);
    for (size_t i = 8; i < size; i++)
        echo[i] = i;
    if (!index) {
        echo[2] = echo[3] = 0;
        put16 (echo + 2, hev_icmp_checksum (echo, size));
    }
    r = hev_icmp_request_new (NULL, 0, (void *)&target, len, echo, size, 60000,
                              result);
    assert (r && !hev_icmp_engine_send (e, r));
    return r;
}

static HevIcmpRequest *
fixture_request (HevIcmpEngine *e, int index, Result *result, int scoped)
{
    return fixture_request_sized (e, index, result, scoped, 24);
}

static void
quote_lengths_and_budget (HevIcmpEngine *e, int index)
{
    for (unsigned int mode = 0; mode < 3; mode++) {
        Result a = { 0 };
        HevIcmpRequest *r =
            fixture_request_sized (e, index, &a, 0, mode == 2 ? 24 : 200);
        Packet p = error_packet (r, 0, index ? 3 : 11, 0, 0, 0);
        if (!mode) {
            p.len = 8 + (index ? 40 : 20) + 8;
        } else {
            p.data[index ? 4 : 5] = index ? 16 : 32;
            p.len = 8 + 128 + 12;
            memset (p.data + 8 + 128, 0xf1, 12);
        }
        seal_packet (&p, index);
        enqueue (index, p);
        hev_icmp_engine_poll (e, fixture_active);
        assert (a.terminals == 1 && a.error == EHOSTUNREACH);
    }
#if defined(__linux__) && defined(SO_EE_RFC4884_FLAG_INVALID)
    for (unsigned int mode = 0; mode < 2; mode++) {
        Result a = { 0 };
        HevIcmpRequest *r = fixture_request_sized (e, index, &a, 0, 200);
        Packet p = error_packet (r, 1, index ? 3 : 11, 0, 0, 0);
        p.quote_len = mode ? 128 - (index ? 40 : 20) : 0;
        p.len = mode ? p.quote_len + 12 : 8;
        if (index && mode)
            p.info = 0x10000000; /* RFC 4884 length in Time Exceeded's union. */
        if (mode)
            memset (p.data + p.quote_len, 0xf1, 12);
        enqueue (index, p);
        hev_icmp_engine_poll (e, fixture_active);
        assert (a.terminals == 1 && a.error == EHOSTUNREACH);
#ifdef ICMP_EXPECT_METADATA
        assert (!a.info);
#endif
    }
#endif
    Result a = { 0 };
    HevIcmpRequest *r = fixture_request (e, index, &a, 0);
    Packet p = error_packet (r, 0, index ? 3 : 11, 0, 0, 0);
    unsigned int before = read_calls;
    for (unsigned int i = 0; i < 65; i++) {
#ifdef __linux__
        if (i < 32)
            enqueue (index, error_packet (r, 1, index ? 3 : 11, 0, 0, 0));
        else
#endif
            enqueue (index, p);
    }
    assert (hev_icmp_engine_poll (e, fixture_active));
    assert (a.terminals == 1 && read_calls - before == 64);
    assert (!e->requests && endpoints[index].count == 1);
    assert (!hev_icmp_engine_poll (e, fixture_active));
    assert (a.terminals == 1 && read_calls - before == 65);
    assert (!hev_icmp_engine_poll (e, fixture_active));
    assert (hev_icmp_engine_timeout (e) == -1);
}

static void
receive_budget_fairness (HevIcmpEngine *e)
{
    Result results[2] = { 0 };
    HevIcmpRequest *requests[2];
    Packet packets[2];
    unsigned int before = read_calls;
    for (int index = 0; index < 2; index++) {
        requests[index] = fixture_request (e, index, &results[index], 0);
        packets[index] =
            error_packet (requests[index], 0, index ? 3 : 11, 0, 0, 0);
    }
    /* Foreign IPv4 packets exhaust its budget. IPv6 must still run in this
     * cycle, and pending timeouts must still run before the returned yield. */
    Packet foreign = packets[0];
    foreign.data[8 + 20 + 4] ^= 1;
    seal_packet (&foreign, 0);
    for (unsigned int i = 0; i < 65; i++)
        enqueue (0, foreign);
    enqueue (1, packets[1]);
    requests[0]->deadline = 0;
    assert (hev_icmp_engine_poll (e, fixture_active));
    assert (read_calls - before == 65 && endpoints[0].count == 1);
    assert (results[0].terminals == 1 && results[0].error == ETIMEDOUT);
    assert (results[1].terminals == 1 && results[1].error == EHOSTUNREACH);
    assert (!e->requests && !hev_icmp_engine_poll (e, fixture_active));
    assert (read_calls - before == 66);
    assert (!hev_icmp_engine_poll (e, fixture_active));
    assert (hev_icmp_engine_timeout (e) == -1);
    puts (
        "PASS receive budgets preserve both-family/deadline fairness and clear the drain hint at idle");
}

static void
positive_errors (HevIcmpEngine *e, int index, int queued)
{
    int types[4] = { index ? 1 : 3, index ? 2 : 3, index ? 3 : 11,
                     index ? 4 : 12 };
    for (unsigned int i = 0; i < 4; i++) {
        Result a = { 0 }, b = { 0 };
        HevIcmpRequest *r = fixture_request (e, index, &a, 0);
        HevIcmpRequest *other = fixture_request (e, index, &b, 0);
        int code = !index && i == 1 ? 4 : 0;
        uint32_t info = i == 1 ? 1280 : i == 3 ? 4 : 0;
        Packet p = error_packet (r, queued, types[i], code, info, 0);
        unsigned long before = received;
        unsigned int calls = read_calls;
        enqueue (index, p);
        enqueue (index, p);
        hev_icmp_engine_poll (e, fixture_active);
        assert (a.terminals == 1 && a.error && !b.terminals);
        assert (received - before == p.len * 2 && read_calls - calls == 2);
        assert (a.peer_len == p.address_len &&
                !memcmp (&a.peer, &p.peer, p.address_len));
        assert (a.local_len == p.address_len &&
                !memcmp (&a.local, &p.local, p.address_len));
#ifdef ICMP_EXPECT_METADATA
        assert (a.origin == HEV_ICMP_ERROR_RECEIVED && a.type == types[i] &&
                a.code == code && a.info == info);
#endif
        p = error_packet (other, queued, types[i], code, info, 0);
        enqueue (index, p);
        hev_icmp_engine_poll (e, fixture_active);
        assert (b.terminals == 1 && b.error);
    }
}

static void
negative_errors (HevIcmpEngine *e, int index, int queued)
{
    for (unsigned int fault = 0; fault < 7; fault++) {
        Result a = { 0 };
        HevIcmpRequest *r = fixture_request (e, index, &a, 0);
        Packet p = error_packet (r, queued, index ? 3 : 11, 0, 0, 0);
        size_t start = queued ? 0 : 8 + (index ? 40 : 20);
        if (fault == 0)
            p.data[start + 4] ^= 1;
        else if (fault == 1)
            p.data[start + 7] ^= 0x80;
        else if (fault == 2) {
            if (queued)
                ((unsigned char *)&p.target)[index ? 23 : 7] ^= 1;
            else
                p.data[8 + (index ? 39 : 19)] ^= 1;
        } else if (fault == 3)
            p.data[start + 8] ^= 1;
        else if (fault == 4)
            p.len = start + 7;
        else if (fault == 5)
            p.flags = MSG_TRUNC;
        else
            p.flags = MSG_CTRUNC;
        if (!queued)
            seal_packet (&p, index);
        enqueue (index, p);
        hev_icmp_engine_poll (e, fixture_active);
        assert (!a.terminals);
        r->deadline = 0;
        hev_icmp_engine_poll (e, fixture_active);
        assert (a.terminals == 1 && a.error == ETIMEDOUT);
#ifdef ICMP_EXPECT_METADATA
        assert (a.origin == HEV_ICMP_ERROR_TIMEOUT && !a.type && !a.code &&
                !a.info);
#endif
    }
}

static void
parameter_problem_lengths (HevIcmpEngine *e)
{
    for (unsigned int code = 0; code <= 2; code++) {
        Result result = { 0 };
        HevIcmpRequest *r = fixture_request_sized (e, 0, &result, 0, 236);
        Packet p = error_packet (r, 0, 12, code, 0, 0);
        /* The original IP total length is 256. Reading its network bytes
         * as host order on little-endian Darwin yields 1, not 256. */
        enqueue (0, p);
        hev_icmp_engine_poll (e, fixture_active);
        assert (result.terminals == 1 && result.error == EPROTO);
#ifdef ICMP_EXPECT_METADATA
        assert (result.origin == HEV_ICMP_ERROR_RECEIVED && result.type == 12 &&
                result.code == (int)code && !result.info);
#endif
    }
}

static void
scope_extensions_and_lifecycle (HevIcmpEngine *e)
{
    for (unsigned int fault = 0; fault < 4; fault++) {
        Result a = { 0 };
        HevIcmpRequest *r = fixture_request (e, 1, &a, 1);
        Packet p = error_packet (r, 0, 2, 0, 1280, 1);
        if (fault == 1)
            p.interface = 8;
        else if (fault == 2)
            p.data[8 + 41] = 255;
        else if (fault == 3)
            p.data[8 + 64 + 3] = 8;
        seal_packet (&p, 1);
        enqueue (1, p);
        hev_icmp_engine_poll (e, fixture_active);
        if (!fault) {
            assert (a.terminals == 1 && a.error == EMSGSIZE);
        } else {
            assert (!a.terminals);
            a.active = 0;
            hev_icmp_engine_poll (e, fixture_active);
            assert (a.terminals == 1 && a.error == ECANCELED);
        }
    }
    for (unsigned int cancelled = 0; cancelled < 2; cancelled++) {
        Result a = { 0 };
        HevIcmpRequest *r = fixture_request (e, 0, &a, 0);
        Packet p = error_packet (r, 0, 11, 0, 0, 0);
        if (cancelled)
            a.active = 0;
        else
            r->deadline = 0;
        enqueue (0, p);
        unsigned long before = received;
        hev_icmp_engine_poll (e, fixture_active);
        assert (a.terminals == 1 &&
                a.error == (cancelled ? ECANCELED : ETIMEDOUT));
        assert (received - before == p.len);
#ifdef ICMP_EXPECT_METADATA
        assert (a.origin == (cancelled ? HEV_ICMP_ERROR_CANCELLED :
                                         HEV_ICMP_ERROR_TIMEOUT));
        assert (!a.type && !a.code && !a.info && !a.peer_len);
#endif
    }
}

#if defined(__linux__) && defined(ICMP_EXPECT_METADATA)
static void
queue_local_addresses (HevIcmpEngine *e)
{
    for (int index = 0; index < 2; index++) {
        for (unsigned int mode = 0; mode < 3; mode++) {
            Result result = { 0 };
            HevIcmpRequest *r = fixture_request (e, index, &result, 0);
            Packet p = error_packet (r, 1, index ? 3 : 11, 0, 0, 0);
            struct sockaddr_storage expected = p.local;
            socklen_t expected_len = r->destination_len;
            if (mode == 1) {
                /* The logical return recipient has priority over the
                 * socket's local address; it is not an outgoing bind. */
                r->source = r->destination;
                r->source_len = r->destination_len;
                expected = r->source;
            } else if (mode == 2) {
                memset (&p.local, 0, sizeof (p.local));
            }
            enqueue (index, p);
            hev_icmp_engine_poll (e, fixture_active);
            assert (result.terminals == 1 && result.error == EHOSTUNREACH);
            if (mode == 2)
                assert (!result.local_len);
            else
                assert (result.local_len == expected_len &&
                        !memcmp (&result.local, &expected, result.local_len));
        }
    }
}

static void
queue_origin_and_retry (HevIcmpEngine *e)
{
    for (unsigned int mode = 0; mode < 3; mode++) {
        Result a = { 0 };
        HevIcmpRequest *r = fixture_request (e, 0, &a, 0);
        Packet p = error_packet (r, 1, 3, 4, 1280, 0);
        unsigned long before = received, unknown_before = unknown;
        if (mode == 0)
            p.origin = SO_EE_ORIGIN_LOCAL;
        else if (mode == 1)
            p.origin = SO_EE_ORIGIN_NONE;
        else
            p.unknown_peer = 1;
        enqueue (0, p);
        hev_icmp_engine_poll (e, fixture_active);
        if (mode == 1) {
            assert (!a.terminals && received == before);
            a.active = 0;
            hev_icmp_engine_poll (e, fixture_active);
        } else {
            assert (a.terminals == 1 && a.error == EMSGSIZE);
            assert (a.origin == (mode == 0 ? HEV_ICMP_ERROR_LOCAL :
                                             HEV_ICMP_ERROR_RECEIVED));
            assert (received - before == (mode == 0 ? 0 : p.len));
            assert (unknown - unknown_before == (mode == 0 ? 0 : p.len));
        }
    }
    Result a = { 0 }, b = { .active = 1 }, c = { 0 };
    HevIcmpRequest *first = fixture_request (e, 0, &a, 0);
    HevIcmpRequest *waiting = fixture_request (e, 0, &c, 0);
    unsigned char echo[8];
    hev_icmp_echo (echo, AF_INET, 0x12345678);
    HevIcmpRequest *second = hev_icmp_request_new (NULL, 0,
                                                   (void *)&first->destination,
                                                   first->destination_len, echo,
                                                   sizeof (echo), 1000, &b);
    assert (second);
    raced_error = error_packet (first, 1, 11, 0, 0, 0);
    e->next_sequence = UINT16_MAX;
    send_failure = EHOSTUNREACH;
    fail_once = inject_on_failure = 1;
    unsigned long before = sent;
    assert (hev_icmp_engine_send (e, second) == HEV_ICMP_RETRY);
    assert (sent == before);
    hev_icmp_engine_poll (e, fixture_active);
    assert (a.terminals == 1 && !b.terminals && !c.terminals);
    assert (!hev_icmp_engine_send (e, second));
    assert (sent - before == sizeof (echo));
    Packet p = error_packet (second, 1, 11, 0, 0, 0);
    enqueue (0, p);
    hev_icmp_engine_poll (e, fixture_active);
    assert (b.terminals == 1 && b.origin == HEV_ICMP_ERROR_RECEIVED);
    c.active = 0;
    hev_icmp_engine_poll (e, fixture_active);
    assert (c.terminals == 1 && c.error == ECANCELED);
    (void)waiting;

    /* A direct engine caller may advance the socket epoch before retrying
     * its unsent request. A saved old sequence must not enter the new epoch. */
    {
        Result old = { 0 }, held = { .active = 1 }, intervening = { 0 };
        HevIcmpRequest *old_request = fixture_request (e, 0, &old, 0);
        HevIcmpRequest *held_request = hev_icmp_request_new (
            NULL, 0, (void *)&old_request->destination,
            old_request->destination_len, echo, sizeof (echo), 1000, &held);
        assert (held_request);
        raced_error = error_packet (old_request, 1, 11, 0, 0, 0);
        e->next_sequence = UINT16_MAX;
        send_failure = EHOSTUNREACH;
        fail_once = inject_on_failure = 1;
        assert (hev_icmp_engine_send (e, held_request) == HEV_ICMP_RETRY);
        hev_icmp_engine_poll (e, fixture_active);
        assert (old.terminals == 1);
        HevIcmpRequest *other = fixture_request (e, 0, &intervening, 0);
        assert (other->sequence == 1);
        assert (!hev_icmp_engine_send (e, held_request));
        assert (held_request->sequence == 2 && !e->slots[UINT16_MAX]);
        held.active = intervening.active = 0;
        hev_icmp_engine_poll (e, fixture_active);
        assert (held.terminals == 1 && intervening.terminals == 1);
    }

    Result d = { .active = 1 };
    struct sockaddr_in target = { .sin_family = AF_INET };
    inet_pton (AF_INET, "192.0.2.2", &target.sin_addr);
    HevIcmpRequest *failed = hev_icmp_request_new (NULL, 0, (void *)&target,
                                                   sizeof (target), echo,
                                                   sizeof (echo), 1000, &d);
    assert (failed);
    send_failure = EACCES;
    fail_once = 0;
    unsigned int attempts = send_calls;
    assert (hev_icmp_engine_send (e, failed) == HEV_ICMP_RETRY);
    hev_icmp_engine_poll (e, fixture_active);
    assert (hev_icmp_engine_send (e, failed) == -EACCES);
    assert (send_calls - attempts == 1 && !d.terminals);
    free (failed);
    send_failure = 0;
}
#endif

static void
error_tests (void *unused)
{
    (void)unused;
    HevIcmpEngine *e = hev_icmp_engine_new (fixture_binder, fixture_observe,
                                            fixture_complete, NULL);
    assert (e);
    for (int index = 0; index < 2; index++) {
        positive_errors (e, index, 0);
        negative_errors (e, index, 0);
        quote_lengths_and_budget (e, index);
#ifdef __linux__
        positive_errors (e, index, 1);
        negative_errors (e, index, 1);
#endif
    }
    receive_budget_fairness (e);
    parameter_problem_lengths (e);
    scope_extensions_and_lifecycle (e);
#if defined(__linux__) && defined(ICMP_EXPECT_METADATA)
    queue_local_addresses (e);
    queue_origin_and_retry (e);
#endif
    Result stopped = { 0 };
    fixture_request (e, 0, &stopped, 0);
    hev_icmp_engine_free (e);
    assert (stopped.terminals == 1 && stopped.error == ESHUTDOWN);
#ifdef ICMP_EXPECT_METADATA
    assert (stopped.origin == HEV_ICMP_ERROR_SHUTDOWN && !stopped.type);
#endif
    assert (!endpoints[0].family && !endpoints[1].family);
    puts (
        "PASS production error parser: IPv4/IPv6 errors, quotes, metadata, attribution, isolation, duplicate/late/cancel/stop and extension/scope bounds");
#ifdef __linux__
    puts (
        "PASS Linux error queue: network/local/unknown origins, unknown offender and asynchronous send-error retry without replaying permanent local failures");
#endif
}

int
main (void)
{
    endpoints[0].fd = endpoints[1].fd = -1;
    assert (!hev_task_system_init ());
    HevTask *task = hev_task_new (65536);
    assert (task);
    hev_task_run (task, error_tests, NULL);
    hev_task_system_run ();
    hev_task_system_fini ();
    return 0;
}
