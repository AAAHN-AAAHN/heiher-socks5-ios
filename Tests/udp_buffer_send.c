#define _GNU_SOURCE
/* Actual sender, with only syscall outcomes substituted. Darwin's EMSGSIZE
 * repair must retain prefixes and may retry each unsent message only once. */
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <sys/socket.h>

#define hev_task_io_socket_sendmmsg send_fixture
#define getsockopt get_fixture
#define setsockopt set_fixture
#include "hev-socks5-udp.c"
#undef hev_task_io_socket_sendmmsg
#undef getsockopt
#undef setsockopt

#include <stdio.h>

static int script[8], script_count, calls, gets, sets, capacity, refuse;
static unsigned int expected_offset[8];
static struct mmsghdr *origin;

int
send_fixture (int fd, void *messages, unsigned int count, int flags,
              HevTaskIOYielder yielder, void *data)
{
    int result;
    (void)yielder;
    (void)data;
    assert (fd == 19 && count && flags == MSG_WAITALL && calls < script_count);
    assert ((struct mmsghdr *)messages - origin == expected_offset[calls]);
    result = script[calls++];
    if (result < 0) {
        errno = -result;
        return -1;
    }
    assert ((unsigned int)result <= count);
    for (int i = 0; i < result; i++) {
        struct mmsghdr *m = (struct mmsghdr *)messages + i;
        m->msg_len = m->msg_hdr.msg_iov[0].iov_len;
    }
    if ((unsigned int)result < count)
        errno = EMSGSIZE;
    return result;
}

int
get_fixture (int fd, int level, int option, void *value, socklen_t *length)
{
    assert (fd == 19 && level == SOL_SOCKET && option == SO_SNDBUF);
    assert (*length == sizeof (int));
    gets++;
    *(int *)value = capacity;
    return 0;
}

int
set_fixture (int fd, int level, int option, const void *value, socklen_t length)
{
    assert (fd == 19 && level == SOL_SOCKET && option == SO_SNDBUF);
    assert (length == sizeof (int));
    sets++;
    if (refuse == 1) {
        errno = ENOBUFS;
        return -1;
    }
    if (!refuse)
        capacity = *(const int *)value;
    return 0;
}

static void
reset (struct mmsghdr *messages)
{
    origin = messages;
    calls = gets = sets = refuse = 0;
    capacity = 9216;
    memset (expected_offset, 0, sizeof (expected_offset));
    for (int i = 0; i < 2; i++)
        messages[i].msg_len = 0xdead;
}

int
main (void)
{
    HevSocks5 self = { .timeout = 60000 };
    struct iovec iov[2] = { { NULL, 7 }, { NULL, 48001 } };
    struct mmsghdr messages[2] = { 0 };
    for (int i = 0; i < 2; i++) {
        messages[i].msg_hdr.msg_iov = &iov[i];
        messages[i].msg_hdr.msg_iovlen = 1;
    }
    reset (messages);
    script[0] = 2;
    script_count = 1;
    assert (udp_sendmmsg (&self, 19, messages, 2) == 2);
    assert (calls == 1 && !gets && !sets);
    assert (messages[0].msg_len == 7 && messages[1].msg_len == 48001);
    reset (messages);
    script[0] = -EIO;
    assert (udp_sendmmsg (&self, 19, messages, 2) == -1);
    assert (calls == 1 && !gets && !sets);
#if defined(__APPLE__)
    reset (messages);
    script[0] = 1;
    script[1] = 1;
    expected_offset[1] = 1;
    script_count = 2;
    assert (udp_sendmmsg (&self, 19, messages, 2) == 2);
    assert (calls == 2 && gets == 1 && sets == 1 && capacity == 48001);
    assert (messages[0].msg_len == 7 && messages[1].msg_len == 48001);
    for (int failure = 0; failure < 3; failure++) {
        reset (messages);
        script[0] = -EMSGSIZE;
        script[1] = -EMSGSIZE;
        script_count = 2;
        origin = &messages[1];
        refuse = failure;
        assert (udp_sendmmsg (&self, 19, &messages[1], 1) == -1);
        assert (calls == (failure == 1 ? 1 : 2) && gets == 1 && sets == 1);
        assert (messages[1].msg_len == 0xdead);
    }
    reset (messages);
    script[0] = 1;
    script[1] = -EMSGSIZE;
    expected_offset[1] = 1;
    script_count = 2;
    assert (udp_sendmmsg (&self, 19, messages, 2) == 1);
    assert (calls == 2 && gets == 1 && sets == 1);
    assert (messages[0].msg_len == 7 && messages[1].msg_len == 0xdead);
    puts (
        "PASS: Darwin lazy send-space repair, preserved successful prefix, rejected/clamped/repeated failure bounded to one retry");
#else
    reset (messages);
    script[0] = 1;
    script_count = 1;
    assert (udp_sendmmsg (&self, 19, messages, 2) == 1);
    assert (calls == 1 && !gets && !sets);
    puts (
        "PASS: non-Darwin sender preserves original single wrapper call and successful prefix");
#endif
    return 0;
}
