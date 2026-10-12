#define _GNU_SOURCE
/* Exercise both resolver routes in a real initialized task system: serial
 * startup uses libc, while a running task uses asynchronous task DNS. Only
 * resolver results are controlled; numeric sockaddr results are real libc. */
#include <hev-task-dns.h>
#include <hev-task-system.h>
#include <hev-task.h>
#include <netdb.h>

static int audit_sync_getaddrinfo (const char *, const char *,
                                   const struct addrinfo *, struct addrinfo **);
static int audit_task_getaddrinfo (const char *, const char *,
                                   const struct addrinfo *, struct addrinfo **);

#define getaddrinfo audit_sync_getaddrinfo
#define hev_task_dns_getaddrinfo audit_task_getaddrinfo
#include "hev-misc.c"
#undef hev_task_dns_getaddrinfo
#undef getaddrinfo

#include <assert.h>
#include <stdint.h>
#include <stdio.h>

static int dns_error;
static unsigned calls[2];
static struct sockaddr_storage resolved;

static int
audit_getaddrinfo (int in_task, const char *node, const char *service,
                   const struct addrinfo *hints, struct addrinfo **result)
{
    int status;
    assert (!!hev_task_self () == in_task);
    calls[in_task]++;
    *result = NULL;
    if (dns_error)
        return dns_error;
    status = getaddrinfo (node, service, hints, result);
    assert (!status && *result);
    assert ((*result)->ai_addrlen <= sizeof (resolved));
    memset (&resolved, 0, sizeof (resolved));
    memcpy (&resolved, (*result)->ai_addr, (*result)->ai_addrlen);
    return status;
}

static int
audit_sync_getaddrinfo (const char *node, const char *service,
                        const struct addrinfo *hints, struct addrinfo **result)
{
    return audit_getaddrinfo (0, node, service, hints, result);
}

static int
audit_task_getaddrinfo (const char *node, const char *service,
                        const struct addrinfo *hints, struct addrinfo **result)
{
    return audit_getaddrinfo (1, node, service, hints, result);
}

static void
exercise (void *data)
{
    const char *hosts[] = { "127.0.0.1", "192.0.2.123", "::1", "2001:db8::1234",
                            "fe80::1%1" };
    struct
    {
        uint64_t before;
        struct sockaddr_in6 address;
        uint64_t after;
    } target;
    unsigned failures = 0, successes = 0;

    assert (!!hev_task_self () == !!data);
    target.before = UINT64_C (0x1122334455667788);
    target.after = UINT64_C (0x8877665544332211);
    for (dns_error = -15; dns_error <= 15; dns_error++) {
        struct sockaddr_in6 previous;
        if (!dns_error)
            continue;
        memset (&target.address, 0xa5, sizeof (target.address));
        previous = target.address;
        assert (hev_netaddr_resolve (&target.address, "127.0.0.1", "61234") ==
                -1);
        assert (!memcmp (&target.address, &previous, sizeof (previous)));
        assert (target.before == UINT64_C (0x1122334455667788));
        assert (target.after == UINT64_C (0x8877665544332211));
        failures++;
    }
    dns_error = 0;
    for (unsigned i = 0; i < sizeof (hosts) / sizeof (*hosts); i++) {
        memset (&target.address, 0, sizeof (target.address));
        assert (!hev_netaddr_resolve (&target.address, hosts[i], "61234"));
        if (resolved.ss_family == AF_INET) {
            struct sockaddr_in source;
            memcpy (&source, &resolved, sizeof (source));
            assert (target.address.sin6_family == AF_INET6);
            assert (target.address.sin6_port == source.sin_port);
            assert (IN6_IS_ADDR_V4MAPPED (&target.address.sin6_addr));
            assert (!memcmp (&target.address.sin6_addr.s6_addr[12],
                             &source.sin_addr, sizeof (source.sin_addr)));
        } else {
            assert (resolved.ss_family == AF_INET6);
            assert (
                !memcmp (&target.address, &resolved, sizeof (target.address)));
        }
        assert (target.before == UINT64_C (0x1122334455667788));
        assert (target.after == UINT64_C (0x8877665544332211));
        successes++;
    }
    printf (
        "PASS: route=%s %u DNS errors leave output untouched; %u real numeric "
        "results preserved; native EAI_AGAIN=%d EAI_MEMORY=%d EAI_NONAME=%d "
        "EAI_SYSTEM=%d\n",
        data ? "task" : "serial", failures, successes, EAI_AGAIN, EAI_MEMORY,
        EAI_NONAME, EAI_SYSTEM);
}

int
main (void)
{
    HevTask *task;

    assert (!hev_task_system_init ());
    exercise (NULL);
    assert (calls[0] == 35 && !calls[1]);
    task = hev_task_new (-1);
    assert (task);
    hev_task_run (task, exercise, task);
    hev_task_system_run ();
    assert (calls[0] == 35 && calls[1] == 35);
    hev_task_system_fini ();
    puts ("PASS: 70 resolver cases; exact serial/task routing preserved");
    return 0;
}
