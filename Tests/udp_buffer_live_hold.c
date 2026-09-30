#define _GNU_SOURCE
/* Real UDP input and Hev timer: no substituted clock, allocator or intervals.
 * The producer is test-only; production reclamation still has one owner task. */
#include "hev-socks5-udp.c"
#include <assert.h>
#include <stdio.h>
#include <fcntl.h>
#include <hev-task-system.h>

static int input, output;
static unsigned char bytes[48001];
static uint64_t first, second, lowered, cleared;

static void
produce (void *data)
{
    (void)data;
    assert (send (output, bytes, 48001, 0) == 48001);
    assert (hev_task_sleep (120000) == 0);
    assert (send (output, bytes, 30001, 0) == 30001);
}

static void
consume (void *data)
{
    unsigned char base[UDP_BUF_SIZE];
    UDPBuffers owner = { 0 };
    UDPBuffer buffer = { .base = base,
                         .capacity = UDP_BUF_SIZE,
                         .owner = &owner };
    HevSocks5 self = { .type = HEV_SOCKS5_TYPE_UDP_IN_TCP, .timeout = 600000 };
    struct iovec vector = { base, sizeof (base) };
    struct mmsghdr message = { 0 };
    unsigned int count = 0;
    (void)data;
    owner.slots = &buffer;
    owner.count = 1;
    message.msg_hdr.msg_iov = &vector;
    message.msg_hdr.msg_iovlen = 1;
    assert (hev_task_add_fd (hev_task_self (), input, POLLIN) == 0);
    for (;;) {
        int result;
        uint64_t now = udp_buffer_now ();
        size_t before = buffer.capacity;
        udp_buffers_cleanup (&owner, now);
        if (before != buffer.capacity) {
            printf ("reclaim: capacity=%zu elapsed=%.6f seconds\n",
                    buffer.capacity, (now - first) / 1e9);
            fflush (stdout);
            assert (count == 2);
            if (buffer.capacity == 30500) {
                assert (!lowered);
                lowered = now;
            } else {
                assert (buffer.capacity == 1500 && lowered && !cleared);
                cleared = now;
                break;
            }
        }
        result = udp_buffer_recvmmsg (&self, input, &message, 1, MSG_DONTWAIT,
                                      &buffer);
        if (result == 1) {
            size_t wanted = count ? 30001 : 48001;
            size_t capacity;
            assert (count < 2 && message.msg_len == wanted);
            assert (!(message.msg_hdr.msg_flags & MSG_TRUNC));
            assert (!memcmp (udp_buffer_data (&buffer), bytes, wanted));
            assert (buffer.capacity == 48500);
            assert (udp_buffer_round (wanted, &capacity) == 0);
            uint64_t when = buffer.history[udp_buffer_bins (capacity) - 1] -
                            UDP_BUFFER_HOLD_SECONDS * UDP_NSEC_PER_SEC;
            if (!count)
                first = when;
            else
                second = when;
            count++;
        } else {
            assert (result == -1 && errno == EAGAIN);
        }
        assert (
            udp_buffers_yield (result > 0 ? HEV_TASK_YIELD : HEV_TASK_WAITIO,
                               &self, &owner) == 0);
    }
    assert (!buffer.history && !owner.next_cleanup && self.timeout == 600000);
    assert (second >= first + 119 * UDP_NSEC_PER_SEC);
    assert (second < first + 123 * UDP_NSEC_PER_SEC);
    assert (lowered >= first + 300 * UDP_NSEC_PER_SEC);
    assert (lowered < first + 362 * UDP_NSEC_PER_SEC);
    assert (cleared >= second + 300 * UDP_NSEC_PER_SEC);
    assert (cleared < second + 362 * UDP_NSEC_PER_SEC);
    assert (hev_task_del_fd (hev_task_self (), input) == 0);
    printf (
        "PASS: real 48001/30001-byte receives; last demands %.6f seconds apart; "
        "48500 -> 30500 at %.6f and -> 1500 at %.6f seconds; "
        "no packet after the second demand\n",
        (second - first) / 1e9, (lowered - first) / 1e9,
        (cleared - first) / 1e9);
}

int
main (void)
{
    struct sockaddr_in addr = { 0 };
    socklen_t length = sizeof (addr);
    int space = 256 * 1024;
    HevTask *receiver, *sender;
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl (INADDR_LOOPBACK);
#if defined(__APPLE__)
    addr.sin_len = sizeof (addr);
#endif
    input = socket (AF_INET, SOCK_DGRAM, 0);
    output = socket (AF_INET, SOCK_DGRAM, 0);
    assert (input >= 0 && output >= 0);
    assert (bind (input, (struct sockaddr *)&addr, sizeof (addr)) == 0);
    assert (getsockname (input, (struct sockaddr *)&addr, &length) == 0);
    assert (connect (output, (struct sockaddr *)&addr, length) == 0);
    assert (setsockopt (output, SOL_SOCKET, SO_SNDBUF, &space,
                        sizeof (space)) == 0);
    assert (fcntl (input, F_SETFL, O_NONBLOCK) == 0);
    for (size_t i = 0; i < sizeof (bytes); i++)
        bytes[i] = i % 251;
    assert (hev_task_system_init () == 0);
    receiver = hev_task_new (-1);
    sender = hev_task_new (-1);
    assert (receiver && sender);
    hev_task_run (receiver, consume, NULL);
    hev_task_run (sender, produce, NULL);
    hev_task_system_run ();
    hev_task_unref (sender);
    hev_task_unref (receiver);
    hev_task_system_fini ();
    close (input);
    close (output);
    return 0;
}
