#define _GNU_SOURCE
#include <assert.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <sys/socket.h>

static int fail_allocation, short_query;
void *io_malloc (size_t size);
void io_free (void *ptr);
ssize_t io_recv (int fd, void *buf, size_t len, int flags);
int io_getsockopt (int fd, int level, int option, void *value,
                   socklen_t *length);

#define hev_malloc io_malloc
#define hev_free io_free
#define recv io_recv
#define getsockopt io_getsockopt
#include "hev-socks5-udp.c"
#undef hev_malloc
#undef hev_free
#undef recv
#undef getsockopt

#include <stdio.h>

void *
io_malloc (size_t size)
{
    if (fail_allocation)
        return NULL;
    return malloc (size);
}

void
io_free (void *ptr)
{
    free (ptr);
}

ssize_t
io_recv (int fd, void *buf, size_t len, int flags)
{
#if defined(__linux__)
    if (short_query && (flags & MSG_PEEK))
        return 1;
#endif
    return recv (fd, buf, len, flags);
}

int
io_getsockopt (int fd, int level, int option, void *value, socklen_t *length)
{
#if defined(__APPLE__)
    if (short_query && option == SO_NREAD) {
        assert (*length == sizeof (int));
        *(int *)value = 1;
        return 0;
    }
#endif
    return getsockopt (fd, level, option, value, length);
}

static void
family_test (int family)
{
    UDPBuffers owner = { 0 };
    UDPBuffer buffers[3] = { 0 };
    unsigned char base[3][UDP_BUF_SIZE], payload[48001], received[48001];
    struct sockaddr_in6 target = { 0 }, peers[3];
    struct mmsghdr messages[3] = { 0 };
    struct iovec vectors[3];
    HevSocks5 self = { .type = HEV_SOCKS5_TYPE_UDP_IN_TCP, .timeout = 60000 };
    int input = socket (family, SOCK_DGRAM, 0);
    int output = socket (family, SOCK_DGRAM, 0);
    int sendspace = 256 * 1024;
    socklen_t length = sizeof (target);

    assert (input >= 0 && output >= 0);
    assert (setsockopt (output, SOL_SOCKET, SO_SNDBUF, &sendspace,
                        sizeof (sendspace)) == 0);
    if (family == AF_INET6) {
        target.sin6_family = AF_INET6;
        target.sin6_addr = in6addr_loopback;
#if defined(__APPLE__)
        target.sin6_len = sizeof (target);
#endif
        assert (bind (input, (struct sockaddr *)&target, sizeof (target)) == 0);
    } else {
        struct sockaddr_in *v4 = (struct sockaddr_in *)&target;
        v4->sin_family = AF_INET;
        v4->sin_addr.s_addr = htonl (INADDR_LOOPBACK);
#if defined(__APPLE__)
        v4->sin_len = sizeof (*v4);
#endif
        assert (bind (input, (struct sockaddr *)v4, sizeof (*v4)) == 0);
    }
    assert (getsockname (input, (struct sockaddr *)&target, &length) == 0);
    assert (connect (output, (struct sockaddr *)&target, length) == 0);
    assert (fcntl (input, F_SETFL, O_NONBLOCK) == 0);
    owner.slots = buffers;
    owner.count = 3;
    for (int i = 0; i < 3; i++) {
        buffers[i].base = base[i];
        buffers[i].capacity = UDP_BUF_SIZE;
        buffers[i].owner = &owner;
        vectors[i] = (struct iovec){ base[i], sizeof (base[i]) };
        messages[i].msg_hdr.msg_iov = &vectors[i];
        messages[i].msg_hdr.msg_iovlen = 1;
        messages[i].msg_hdr.msg_name = &peers[i];
        messages[i].msg_hdr.msg_namelen = sizeof (peers[i]);
    }
    assert (udp_buffer_datagram_size (input, &buffers[0]) < 0 &&
            errno == EAGAIN);
    for (size_t i = 0; i < sizeof (payload); i++)
        payload[i] = i % 251;
    assert (send (output, payload, 0, 0) == 0);
    assert (send (output, payload, 2048, 0) == 2048);
    assert (send (output, payload, sizeof (payload), 0) == sizeof (payload));
    assert (udp_buffer_datagram_size (input, &buffers[0]) == 0);
    assert (udp_buffer_recvmmsg (&self, input, messages, 3, MSG_DONTWAIT,
                                 buffers) == 3);
    const unsigned int sizes[] = { 0, 2048, 48001 };
    for (int i = 0; i < 3; i++) {
        size_t capacity;
        assert (udp_buffer_round (sizes[i], &capacity) == 0);
        assert (buffers[i].capacity == capacity);
        assert (messages[i].msg_len == sizes[i]);
        assert (!(messages[i].msg_hdr.msg_flags & MSG_TRUNC));
        assert (!memcmp (udp_buffer_data (&buffers[i]), payload, sizes[i]));
    }
    assert (recv (input, received, sizeof (received), 0) < 0 &&
            errno == EAGAIN);
    for (int i = 0; i < 3; i++)
        assert (udp_buffer_resize (&buffers[i], UDP_BUF_SIZE) == 0);

    /* Force only the non-consuming size hint wrong. Real kernel truncation must
     * remain flagged and must not become a recorded successful full demand. */
    short_query = 1;
    assert (send (output, payload, 2048, 0) == 2048);
    assert (udp_buffer_recvmmsg (&self, input, messages, 1, MSG_DONTWAIT,
                                 buffers) == 1);
    assert (messages[0].msg_hdr.msg_flags & MSG_TRUNC);
    assert (!buffers[0].history);
    short_query = 0;

    /* A successful small prefix survives allocation failure of the next slot.
     * The oversized datagram is not consumed as a misleading prefix. */
    fail_allocation = 1;
    assert (send (output, payload, 7, 0) == 7);
    assert (send (output, payload, 2048, 0) == 2048);
    assert (udp_buffer_recvmmsg (&self, input, messages, 2, MSG_DONTWAIT,
                                 buffers) == 1);
    assert (messages[0].msg_len == 7 && !self.timeout);
    assert (recv (input, received, sizeof (received), 0) == 2048);
    assert (!memcmp (received, payload, 2048));
    fail_allocation = 0;
    close (input);
    close (output);
    puts (
        family == AF_INET ?
            "PASS: actual IPv4 length/consume/empty/mixed queue, truncation and allocation failure" :
            "PASS: actual IPv6 length/consume/empty/mixed queue, truncation and allocation failure");
}

int
main (void)
{
    family_test (AF_INET);
    family_test (AF_INET6);
    return 0;
}
