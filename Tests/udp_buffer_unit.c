#define _GNU_SOURCE
/* Actual production translation unit. Only time, sleep and allocator boundaries
 * are scripted. No production function body or configured interval is replaced. */
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <time.h>

static uint64_t now_ns, suspended_ns, sleep_jump_ns;
static unsigned int clock_calls, alloc_calls, fail_next, wait_calls;
static unsigned int io_remaining;
static size_t live_bytes, peak_bytes;
static void *pointers[16];
static size_t lengths[16];
static unsigned int delays[32];

int audit_clock (clockid_t clock, struct timespec *ts);
#if defined(__APPLE__)
uint64_t audit_clock_ns (clockid_t clock);
#endif
void *audit_malloc (size_t size);
void audit_free (void *ptr);
unsigned int audit_sleep (unsigned int milliseconds);

#define clock_gettime audit_clock
#define clock_gettime_nsec_np audit_clock_ns
#define hev_malloc audit_malloc
#define hev_free audit_free
#define hev_task_sleep audit_sleep
#define hev_socks5_task_io_yielder audit_yielder
#include "hev-socks5-udp.c"
#undef clock_gettime
#undef clock_gettime_nsec_np
#undef hev_malloc
#undef hev_free
#undef hev_task_sleep
#undef hev_socks5_task_io_yielder

#include <stdio.h>

int
audit_clock (clockid_t clock, struct timespec *ts)
{
    uint64_t value = now_ns;
#if defined(__APPLE__) && defined(CLOCK_UPTIME_RAW)
    if (clock == CLOCK_UPTIME_RAW)
        value -= suspended_ns;
    else
        assert (clock == CLOCK_MONOTONIC);
#else
    if (clock == CLOCK_MONOTONIC)
        value -= suspended_ns;
#if defined(CLOCK_BOOTTIME)
    else
        assert (clock == CLOCK_BOOTTIME);
#endif
#endif
    clock_calls++;
    ts->tv_sec = value / UDP_NSEC_PER_SEC;
    ts->tv_nsec = value % UDP_NSEC_PER_SEC;
    return 0;
}

#if defined(__APPLE__)
uint64_t
audit_clock_ns (clockid_t clock)
{
    assert (clock == CLOCK_MONOTONIC_RAW);
    clock_calls++;
    return now_ns;
}
#endif

void *
audit_malloc (size_t size)
{
    size_t i;
    void *ptr;
    alloc_calls++;
    if (fail_next) {
        fail_next = 0;
        return NULL;
    }
    ptr = malloc (size);
    assert (ptr);
    for (i = 0; i < 16 && pointers[i]; i++)
        ;
    assert (i < 16);
    pointers[i] = ptr;
    lengths[i] = size;
    live_bytes += size;
    if (live_bytes > peak_bytes)
        peak_bytes = live_bytes;
    memset (ptr, 0xa5, size);
    return ptr;
}

void
audit_free (void *ptr)
{
    size_t i;
    assert (ptr);
    for (i = 0; i < 16 && pointers[i] != ptr; i++)
        ;
    assert (i < 16);
    pointers[i] = NULL;
    live_bytes -= lengths[i];
    free (ptr);
}

unsigned int
audit_sleep (unsigned int milliseconds)
{
    assert (wait_calls < 32 && milliseconds >= io_remaining);
    delays[wait_calls++] = milliseconds;
    now_ns += (uint64_t)(milliseconds - io_remaining) * 1000000;
    now_ns += sleep_jump_ns;
    suspended_ns += sleep_jump_ns;
    sleep_jump_ns = 0;
    return io_remaining;
}

int
audit_yielder (HevTaskYieldType type, void *self)
{
    (void)self;
    assert (type == HEV_TASK_WAITIO || type == HEV_TASK_YIELD);
    return 0;
}

static void
init (UDPBuffer *buffer, UDPBuffers *owner, void *base)
{
    *owner = (UDPBuffers){ .slots = buffer, .count = 1 };
    *buffer =
        (UDPBuffer){ .base = base, .capacity = UDP_BUF_SIZE, .owner = owner };
}

static void
use (UDPBuffer *buffer, size_t needed)
{
    assert (udp_buffer_reserve (buffer, needed) == 0);
    udp_buffer_used (buffer, needed);
    assert (buffer->capacity >= needed);
}

static void
rounding (void)
{
    const size_t inputs[] = { 0, 1500, 1501, 48000, 48001, 65536, 65537, 70001 };
    const size_t outputs[] = { 1500,  1500,  2000,  48000,
                               48500, 66000, 66000, 70500 };
    size_t capacity;
    for (size_t i = 0; i < sizeof (inputs) / sizeof (inputs[0]); i++) {
        assert (udp_buffer_round (inputs[i], &capacity) == 0);
        assert (capacity == outputs[i]);
    }
    assert (udp_buffer_round (SIZE_MAX, &capacity) == -1 && errno == EOVERFLOW);
    puts (
        "PASS: 500-byte rounding; >65536 helper capacity; arithmetic overflow rejected");
}

static void
timeline_and_failures (void)
{
    unsigned char base[UDP_BUF_SIZE];
    UDPBuffers owner;
    UDPBuffer b;
    uint64_t original_deadline;
    unsigned int allocated, clocks;
    void *old;
    init (&b, &owner, base);
    now_ns = 0;
    use (&b, 48001);
    assert (b.capacity == 48500 && b.history[93] == 300 * UDP_NSEC_PER_SEC);
    original_deadline = owner.next_cleanup;
    assert (original_deadline == 60 * UDP_NSEC_PER_SEC);
    now_ns = 120 * UDP_NSEC_PER_SEC;
    use (&b, 30001);
    assert (owner.next_cleanup == original_deadline);
    assert (b.history[57] == 420 * UDP_NSEC_PER_SEC);
    allocated = alloc_calls;
    clocks = clock_calls;
    for (int i = 0; i < 100000; i++)
        use (&b, 1500);
    assert (alloc_calls == allocated && clock_calls == clocks);
    udp_buffers_cleanup (&owner, 299 * UDP_NSEC_PER_SEC);
    assert (b.capacity == 48500);
    /* Choose an independent sweep phase, as in the user's [5,6)/[7,8) windows. */
    owner.next_cleanup = 317 * UDP_NSEC_PER_SEC;
    udp_buffers_cleanup (&owner, 317 * UDP_NSEC_PER_SEC);
    assert (b.capacity == 30500 && b.history[57] == 420 * UDP_NSEC_PER_SEC);
    udp_buffers_cleanup (&owner, 377 * UDP_NSEC_PER_SEC);
    assert (b.capacity == 30500);
    udp_buffers_cleanup (&owner, 437 * UDP_NSEC_PER_SEC);
    assert (b.capacity == 1500 && !b.history && !owner.next_cleanup);
    assert (udp_buffer_data (&b) == base && live_bytes == 0);

    now_ns = 1000 * UDP_NSEC_PER_SEC;
    use (&b, 2001);
    old = b.history;
    original_deadline = owner.next_cleanup;
    fail_next = 1;
    assert (udp_buffer_reserve (&b, 48001) < 0 && errno == ENOMEM);
    assert (b.history == old && b.capacity == 2500);
    assert (owner.next_cleanup == original_deadline);
    use (&b, 48001);
    now_ns += 120 * UDP_NSEC_PER_SEC;
    use (&b, 30001);
    now_ns += 181 * UDP_NSEC_PER_SEC;
    old = b.history;
    fail_next = 1;
    udp_buffers_cleanup (&owner, now_ns);
    assert (b.history == old && b.capacity == 48500);
    assert (owner.next_cleanup == now_ns + 60 * UDP_NSEC_PER_SEC);
    allocated = alloc_calls;
    udp_buffers_cleanup (&owner, now_ns + 1);
    assert (allocated == alloc_calls);
    now_ns += 60 * UDP_NSEC_PER_SEC;
    udp_buffers_cleanup (&owner, now_ns);
    assert (b.capacity == 30500);
    assert (udp_buffer_resize (&b, 1500) == 0 && live_bytes == 0);
    puts (
        "PASS: exact 300s/60s timeline, small-packet zero timestamp/allocator calls, transactional growth/shrink failure");
}

static uint32_t seed = 1827389;
static uint32_t
random32 (void)
{
    seed = seed * 1664525u + 1013904223u;
    return seed;
}

static void
reference_histories (void)
{
    unsigned char base[UDP_BUF_SIZE];
    uint64_t times[2400];
    size_t sizes[2400];
    unsigned long observations = 0, sweeps = 0;
    for (int history = 0; history < 80; history++) {
        UDPBuffers owner;
        UDPBuffer b;
        init (&b, &owner, base);
        now_ns = UDP_NSEC_PER_SEC;
        for (size_t event = 0; event < 2400; event++) {
            now_ns += (random32 () % 700) * UINT64_C (10000000);
            times[event] = now_ns;
            sizes[event] = random32 () % 100001;
            if (event % 5)
                sizes[event] %= 8001;
            use (&b, sizes[event]);
            observations++;
            if (owner.next_cleanup && now_ns >= owner.next_cleanup) {
                size_t expected = UDP_BUF_SIZE;
                for (size_t j = 0; j <= event; j++) {
                    size_t capacity;
                    if (now_ns - times[j] >= 300 * UDP_NSEC_PER_SEC)
                        continue;
                    assert (udp_buffer_round (sizes[j], &capacity) == 0);
                    if (capacity > expected)
                        expected = capacity;
                }
                udp_buffers_cleanup (&owner, now_ns);
                assert (b.capacity == expected);
                sweeps++;
            }
        }
        udp_buffers_cleanup (&owner, now_ns + 360 * UDP_NSEC_PER_SEC);
        assert (b.capacity == UDP_BUF_SIZE && live_bytes == 0);
    }
    printf (
        "PASS: %lu actual-helper demand updates and %lu sweeps match full packet-history reference\n",
        observations, sweeps);
}

static void
independent_wait (void)
{
    unsigned char base[UDP_BUF_SIZE];
    UDPBuffers owner;
    UDPBuffer b;
    HevSocks5 self = { .type = HEV_SOCKS5_TYPE_UDP_IN_TCP, .timeout = 130000 };
    init (&b, &owner, base);
    now_ns = UDP_NSEC_PER_SEC;
    use (&b, 48001);
    wait_calls = 0;
    io_remaining = 0;
    assert (udp_buffers_yield (HEV_TASK_WAITIO, &self, &owner) == 0);
    udp_buffers_cleanup (&owner, now_ns);
    assert (udp_buffers_yield (HEV_TASK_WAITIO, &self, &owner) == 0);
    udp_buffers_cleanup (&owner, now_ns);
    assert (udp_buffers_yield (HEV_TASK_WAITIO, &self, &owner) == -1);
    assert (wait_calls == 3 && delays[0] == 60000 && delays[1] == 60000 &&
            delays[2] == 10000);
    assert (self.timeout == 130000);
    self.timeout = 0;
    assert (udp_buffers_yield (HEV_TASK_WAITIO, &self, &owner) == -1);
    assert (wait_calls == 3);
    self.timeout = 130000;
    owner.idle_deadline = 0;
    owner.next_cleanup = now_ns + 60 * UDP_NSEC_PER_SEC;
    io_remaining = 45000;
    assert (udp_buffers_yield (HEV_TASK_WAITIO, &self, &owner) == 0);
    assert (!owner.idle_deadline);
    io_remaining = 0;
    self.timeout = -1;
    owner.idle_deadline = UINT64_MAX;
    assert (udp_buffer_resize (&b, 1500) == 0);
    owner.next_cleanup = 0;
    wait_calls = 0;
    assert (udp_buffers_yield (HEV_TASK_WAITIO, &self, &owner) == 0);
    assert (!wait_calls && !owner.idle_deadline);
    puts (
        "PASS: independent maintenance wakes preserve 130s timeout; I/O wake and Stop; no cleanup sleep without extensions");
}

static void
sleep_clock_domains (void)
{
    unsigned char base[UDP_BUF_SIZE];
    UDPBuffers owner;
    UDPBuffer b;
    HevSocks5 self = { .type = HEV_SOCKS5_TYPE_UDP_IN_TCP, .timeout = 60000 };
    init (&b, &owner, base);
    now_ns = 1000 * UDP_NSEC_PER_SEC;
    suspended_ns = 400 * UDP_NSEC_PER_SEC;
    assert (udp_timeout_now () == 600 * UDP_NSEC_PER_SEC);
    use (&b, 48001);
    assert (b.history[93] == 1300 * UDP_NSEC_PER_SEC);
    wait_calls = 0;
    io_remaining = 50000;
    sleep_jump_ns = 120 * UDP_NSEC_PER_SEC;
    assert (udp_buffers_yield (HEV_TASK_WAITIO, &self, &owner) == 0);
    assert (wait_calls == 1 && delays[0] == 60000 && !owner.idle_deadline);
    assert (udp_timeout_now () == 610 * UDP_NSEC_PER_SEC);
    assert (udp_buffer_now () == 1130 * UDP_NSEC_PER_SEC);
    udp_buffers_cleanup (&owner, now_ns);
    assert (b.capacity == 48500);

    /* Maintenance consumes awake time, while retention ages across sleep. */
    self.timeout = 130000;
    io_remaining = 0;
    sleep_jump_ns = 360 * UDP_NSEC_PER_SEC;
    wait_calls = 0;
    assert (udp_buffers_yield (HEV_TASK_WAITIO, &self, &owner) == 0);
    assert (wait_calls == 1 && delays[0] == 60000);
    assert (owner.idle_deadline == 740 * UDP_NSEC_PER_SEC);
    udp_buffers_cleanup (&owner, now_ns);
    assert (b.capacity == 1500 && !owner.next_cleanup && !live_bytes);
    assert (udp_buffers_yield (HEV_TASK_WAITIO, &self, &owner) == -1);
    assert (wait_calls == 2 && delays[1] == 70000);
    suspended_ns = 0;
    puts (
        "PASS: distinct sleep/awake clocks preserve I/O and idle deadlines without extending buffer retention");
}

int
main (void)
{
    rounding ();
    timeline_and_failures ();
    reference_histories ();
    independent_wait ();
    sleep_clock_domains ();
    assert (live_bytes == 0);
    printf (
        "PASS: all policy allocation ownership released; test peak=%zu bytes\n",
        peak_bytes);
    return 0;
}
