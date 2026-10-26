/* Exercise the production engine's full wire sequence space and timeout edge. */
#include <assert.h>
#include <errno.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <unistd.h>
#include <arpa/inet.h>

#include "hev-task.h"
#include "hev-task-system.h"
#include "hev-icmp-engine.h"

extern atomic_int icmp_test_suppress, icmp_test_live;

typedef struct
{
    unsigned int replies;
    unsigned int timeouts;
    size_t writes;
    size_t reads;
} EngineResult;

static int
bind_engine (int fd, int family, uint16_t identifier, void *context)
{
    (void)fd;
    (void)family;
    (void)identifier;
    (void)context;
    return 0;
}

static int
keep_active (void *context)
{
    (void)context;
    return 1;
}

static void
observe_engine (const struct sockaddr *peer, socklen_t peer_len, size_t bytes,
                int writing, void *context)
{
    EngineResult *r = context;
    assert (peer && peer_len && bytes == 8);
    if (writing)
        r->writes += bytes;
    else
        r->reads += bytes;
}

static void
complete_engine (HevIcmpRequest *request, int error,
                 const struct sockaddr *peer, socklen_t peer_len,
                 const struct sockaddr *local, socklen_t local_len,
                 const unsigned char *echo, size_t len, void *context)
{
    EngineResult *r = context;
    assert (request);
    if (error) {
        assert (error == ETIMEDOUT && !echo && !len);
        r->timeouts++;
    } else {
        assert (peer && peer_len && local && local_len && echo && len == 8);
        assert (echo[4] == 0x12 && echo[5] == 0x34 && echo[6] == 0x56 &&
                echo[7] == 0x78);
        r->replies++;
    }
}

static HevIcmpRequest *
request (const struct sockaddr *destination, socklen_t len, uint32_t timeout)
{
    unsigned char echo[8];
    HevIcmpRequest *r;
    hev_icmp_echo (echo, destination->sa_family, 0x12345678);
    r = hev_icmp_request_new (NULL, 0, destination, len, echo, 8, timeout,
                              NULL);
    assert (r);
    return r;
}

static void
engine_task (void *unused)
{
    EngineResult result = { 0 };
    struct sockaddr_in destination = { .sin_family = AF_INET };
    struct sockaddr_in6 scoped = { .sin6_family = AF_INET6,
                                   .sin6_scope_id = 1 };
    HevIcmpEngine *engine = hev_icmp_engine_new (bind_engine, observe_engine,
                                                 complete_engine, &result);
    HevIcmpRequest *pending, *deferred;
    uint64_t deadline;
    (void)unused;
    assert (engine);
    inet_pton (AF_INET, "127.0.0.1", &destination.sin_addr);
    for (unsigned int i = 1; i < UINT16_MAX; i++) {
        pending = request ((void *)&destination, sizeof (destination), 1000);
        assert (!hev_icmp_engine_send (engine, pending));
        hev_icmp_engine_poll (engine, keep_active);
        assert (result.replies == i && !result.timeouts);
    }
    atomic_store (&icmp_test_suppress, 1);
    pending = request ((void *)&destination, sizeof (destination), 1);
    assert (!hev_icmp_engine_send (engine, pending));
    deadline = pending->deadline;
    deferred = request ((void *)&destination, sizeof (destination), 1000);
    assert (hev_icmp_engine_send (engine, deferred) == HEV_ICMP_DEFERRED);
    assert (result.writes == (size_t)UINT16_MAX * 8);
    while (hev_icmp_now () <= deadline)
        usleep (1000);
    hev_icmp_engine_poll (engine, keep_active);
    assert (result.timeouts == 1);
    atomic_store (&icmp_test_suppress, 0);
    assert (!hev_icmp_engine_send (engine, deferred));
    hev_icmp_engine_poll (engine, keep_active);
    assert (result.replies == UINT16_MAX && result.timeouts == 1);
    puts (
        "PASS full 16-bit wire rollover defers without sending and resumes after pending expiry");

    pending = request ((void *)&destination, sizeof (destination), 1);
    assert (!hev_icmp_engine_send (engine, pending));
    deadline = pending->deadline;
    while (hev_icmp_now () <= deadline)
        usleep (1000);
    hev_icmp_engine_poll (engine, keep_active);
    assert (result.replies == UINT16_MAX && result.timeouts == 2);
    assert (result.reads == ((size_t)UINT16_MAX + 1) * 8);
    puts (
        "PASS readable Echo after deadline is consumed and counted but expires instead of replying");

    inet_pton (AF_INET6, "::1", &scoped.sin6_addr);
    pending = request ((void *)&scoped, sizeof (scoped), 1000);
    assert (!((struct sockaddr_in6 *)&pending->destination)->sin6_scope_id);
    assert (!hev_icmp_engine_send (engine, pending));
    hev_icmp_engine_poll (engine, keep_active);
    assert (result.replies == (unsigned int)UINT16_MAX + 1);
    puts (
        "PASS non-link-local IPv6 zone normalization matches the actual peer");
    hev_icmp_engine_free (engine);
    assert (!atomic_load (&icmp_test_live));
}

void
run_engine_checks (void)
{
    HevTask *task;
    assert (!hev_task_system_init ());
    task = hev_task_new (65536);
    assert (task);
    hev_task_run (task, engine_task, NULL);
    hev_task_system_run ();
    hev_task_system_fini ();
}
