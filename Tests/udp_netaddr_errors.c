#define _GNU_SOURCE
/* Actual native resolver; only its external DNS result is controlled.
 * Error signs cover Linux and Darwin/BSD conventions. Successful cases use
 * real libc numeric address results, including the complete IPv6 sockaddr. */
#define hev_task_dns_getaddrinfo audit_dns_getaddrinfo
#include "hev-misc.c"
#undef hev_task_dns_getaddrinfo

#include <assert.h>
#include <stdint.h>
#include <stdio.h>

static int dns_error;
static struct sockaddr_storage resolved;

int
audit_dns_getaddrinfo (const char *node, const char *service,
                       const struct addrinfo *hints, struct addrinfo **result)
{
    int status;
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

int
main (void)
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
        "PASS: %u DNS errors leave output untouched; %u real numeric results preserved; native EAI_AGAIN=%d EAI_MEMORY=%d EAI_NONAME=%d EAI_SYSTEM=%d\n",
        failures, successes, EAI_AGAIN, EAI_MEMORY, EAI_NONAME, EAI_SYSTEM);
    return 0;
}
