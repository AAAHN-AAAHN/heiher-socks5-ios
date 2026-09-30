/* Real Hev task timer and unchanged production 60s interval. Only the initial
 * demand history is expired test data; no packet arrival triggers cleanup. */
#define _GNU_SOURCE
#include "hev-socks5-udp.c"
#include <assert.h>
#include <stdio.h>
#include <hev-task-system.h>

static void
run (void *data)
{
    unsigned char base[UDP_BUF_SIZE];
    UDPBuffers owner = { 0 };
    UDPBuffer buffer = { .base = base,
                         .capacity = UDP_BUF_SIZE,
                         .owner = &owner };
    HevSocks5 self = { .type = HEV_SOCKS5_TYPE_UDP_IN_TCP, .timeout = 70000 };
    uint64_t begin = udp_buffer_now ();
    uint64_t cleaned = 0, ended;
    (void)data;
    owner.slots = &buffer;
    owner.count = 1;
    assert (udp_buffer_reserve (&buffer, 48001) == 0);
    assert (buffer.capacity == 48500);
    /* Allocated history is zero/expired: it is still kept until a scheduled sweep. */
    assert (owner.next_cleanup >= begin + 60 * UDP_NSEC_PER_SEC);
    for (;;) {
        udp_buffers_cleanup (&owner, udp_buffer_now ());
        if (!buffer.history && !cleaned)
            cleaned = udp_buffer_now ();
        if (udp_buffers_yield (HEV_TASK_WAITIO, &self, &owner) < 0)
            break;
    }
    ended = udp_buffer_now ();
    assert (cleaned >= begin + 60 * UDP_NSEC_PER_SEC);
    assert (cleaned < begin + 70 * UDP_NSEC_PER_SEC);
    assert (ended >= begin + 70 * UDP_NSEC_PER_SEC);
    assert (ended < begin + 80 * UDP_NSEC_PER_SEC);
    assert (!buffer.history && !owner.next_cleanup);
    assert (self.timeout == 70000);
    printf (
        "PASS: real idle cleanup %.6fs, independent 70s communication timeout %.6fs; no I/O/extra task\n",
        (cleaned - begin) / 1e9, (ended - begin) / 1e9);
}

int
main (void)
{
    HevTask *task;
    assert (hev_task_system_init () == 0);
    task = hev_task_new (-1);
    assert (task);
    hev_task_run (task, run, NULL);
    hev_task_system_run ();
    hev_task_unref (task);
    hev_task_system_fini ();
    return 0;
}
