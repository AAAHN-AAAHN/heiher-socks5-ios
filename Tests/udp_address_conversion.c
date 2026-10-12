#define _GNU_SOURCE
/* Actual shared address converter. DNS completion is controlled with full
 * native sockaddr results, including scope. No local interface index or
 * platform-specific acceptance of a numeric zone name is assumed. */
#include <assert.h>
#include <netdb.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <arpa/inet.h>

static int address_dns (const char *, const char *, const struct addrinfo *,
                        struct addrinfo **);
static void address_dns_free (struct addrinfo *);
#define hev_task_dns_getaddrinfo address_dns
#define freeaddrinfo address_dns_free
#include "hev-socks5-misc.c"
#undef hev_task_dns_getaddrinfo
#undef freeaddrinfo

static const struct
{
    const char *name, *numeric;
    int family, dns;
    uint32_t scope;
} names[] = {
    { "fe80::1%1", "fe80::1", AF_INET6, 1, 1 },
    { "fe80::2%7", "fe80::2", AF_INET6, 1, 7 },
    { "resolved-v6.test", "2001:db8::5", AF_INET6, 1, 0 },
    { "resolved-v4.test", "198.51.100.9", AF_INET, 1, 0 },
    { "::1", "::1", AF_INET6, 0, 0 },
    { "127.0.0.1", "127.0.0.1", AF_INET, 0, 0 },
    { "::ffff:192.0.2.9", "::ffff:192.0.2.9", AF_INET6, 0, 0 },
};
static unsigned current_name, dns_calls, dns_frees;
static int requested_family;
static struct addrinfo answer;
static struct sockaddr_in answer_v4;
static struct sockaddr_in6 answer_v6;

static int
address_dns (const char *name, const char *service,
             const struct addrinfo *hints, struct addrinfo **result)
{
    assert (!strcmp (name, names[current_name].name) &&
            names[current_name].dns);
    assert (!service && hints->ai_family == requested_family);
    memset (&answer, 0, sizeof (answer));
    memset (&answer_v4, 0, sizeof (answer_v4));
    memset (&answer_v6, 0, sizeof (answer_v6));
    answer.ai_family = names[current_name].family;
    if (answer.ai_family == AF_INET) {
        answer_v4.sin_family = AF_INET;
        assert (inet_pton (AF_INET, names[current_name].numeric,
                           &answer_v4.sin_addr) == 1);
        answer.ai_addr = (void *)&answer_v4;
        answer.ai_addrlen = sizeof (answer_v4);
    } else {
        answer_v6.sin6_family = AF_INET6;
        answer_v6.sin6_scope_id = names[current_name].scope;
        assert (inet_pton (AF_INET6, names[current_name].numeric,
                           &answer_v6.sin6_addr) == 1);
        answer.ai_addr = (void *)&answer_v6;
        answer.ai_addrlen = sizeof (answer_v6);
    }
    *result = &answer;
    dns_calls++;
    return 0;
}

static void
address_dns_free (struct addrinfo *result)
{
    assert (result == &answer && dns_calls == dns_frees + 1);
    dns_frees++;
}

int
main (void)
{
    const uint16_t ports[] = { 0, 53, 65535 };
    struct
    {
        uint64_t before;
        struct sockaddr_in6 address;
        uint64_t after;
    } target;
    unsigned failures = 0, cases = 0;
    target.before = UINT64_C (0x0123456789abcdef);
    target.after = UINT64_C (0xfedcba9876543210);
    for (int poisoned = 0; poisoned < 2; poisoned++) {
        for (int direct = 0; direct < 2; direct++) {
            for (int configured = 0; configured < 2; configured++) {
                for (unsigned p = 0; p < sizeof (ports) / sizeof (*ports);
                     p++) {
                    memset (&target.address, 0, sizeof (target.address));
                    for (current_name = 0;
                         current_name < sizeof (names) / sizeof (*names);
                         current_name++) {
                        unsigned char wire[64] = { HEV_SOCKS5_ADDR_TYPE_NAME };
                        struct in6_addr expected = { 0 };
                        size_t length = strlen (names[current_name].name);
                        uint16_t port = htons (ports[p]);
                        unsigned before = dns_calls;
                        int family, result, bad;
                        requested_family =
                            configured ? names[current_name].family : AF_UNSPEC;
                        family = requested_family;
                        wire[1] = length;
                        memcpy (wire + 2, names[current_name].name, length);
                        memcpy (wire + 2 + length, &port, 2);
                        if (poisoned)
                            target.address.sin6_scope_id = 31;
                        result =
                            direct ?
                                hev_socks5_name_into_sockaddr6 (
                                    names[current_name].name, ports[p],
                                    &target.address, &family) :
                                hev_socks5_addr_into_sockaddr6 (
                                    (void *)wire, &target.address, &family);
                        assert (!result &&
                                target.address.sin6_family == AF_INET6 &&
                                family == names[current_name].family);
                        assert (target.address.sin6_port == port);
                        assert (dns_calls == before + names[current_name].dns &&
                                dns_frees == dns_calls);
                        if (family == AF_INET) {
                            expected.s6_addr[10] = expected.s6_addr[11] = 0xff;
                            assert (inet_pton (AF_INET,
                                               names[current_name].numeric,
                                               expected.s6_addr + 12) == 1);
                        } else
                            assert (inet_pton (AF_INET6,
                                               names[current_name].numeric,
                                               &expected) == 1);
                        assert (!memcmp (&target.address.sin6_addr, &expected,
                                         sizeof (expected)));
                        bad = target.address.sin6_scope_id !=
                              names[current_name].scope;
                        if (bad)
                            printf (
                                "FAIL: %s direct=%d configured=%d port=%u scope=%u expected=%u\n",
                                names[current_name].name, direct, configured,
                                ports[p], target.address.sin6_scope_id,
                                names[current_name].scope);
                        failures += bad;
                        cases++;
                    }
                }
            }
        }
        for (int type = 1; type <= 4; type += 3) {
            unsigned char wire[19] = { 0 };
            uint16_t port = htons (65535);
            int family = AF_UNSPEC;
            wire[0] = type;
            if (type == HEV_SOCKS5_ADDR_TYPE_IPV4) {
                wire[1] = 127;
                wire[4] = 1;
                memcpy (wire + 5, &port, 2);
            } else {
                wire[16] = 1;
                memcpy (wire + 17, &port, 2);
            }
            /* Reuse a scoped destination for a wire address with no scope. */
            target.address.sin6_scope_id = poisoned ? UINT32_C (0xa5a5a5a5) : 7;
            assert (!hev_socks5_addr_into_sockaddr6 ((void *)wire,
                                                     &target.address, &family));
            assert (target.address.sin6_port == port &&
                    target.address.sin6_family == AF_INET6);
            int bad = target.address.sin6_scope_id != 0;
            if (bad)
                printf ("FAIL: wire type=%d stale scope=%u\n", type,
                        target.address.sin6_scope_id);
            failures += bad;
            cases++;
        }
    }
    /* Rejected inputs must not clear a prior endpoint or change its family. */
    unsigned char invalid[] = { 3,   9,   '1', '2', '7', 0, '0',
                                '.', '0', '.', '1', 0,   53 };
    struct sockaddr_in6 saved = target.address;
    int family = AF_UNSPEC;
    unsigned before = dns_calls;
    assert (hev_socks5_addr_into_sockaddr6 ((void *)invalid, &target.address,
                                            &family) == -1);
    assert (!memcmp (&saved, &target.address, sizeof (saved)) &&
            family == AF_UNSPEC);
    invalid[0] = 255;
    assert (hev_socks5_addr_into_sockaddr6 ((void *)invalid, &target.address,
                                            &family) == -1);
    assert (!memcmp (&saved, &target.address, sizeof (saved)) &&
            family == AF_UNSPEC);
    assert (dns_calls == before && dns_frees == dns_calls);
    assert (target.before == UINT64_C (0x0123456789abcdef) &&
            target.after == UINT64_C (0xfedcba9876543210));
    printf (
        "address conversion: %u/%u failures; NAME/wire scope, configured family, numeric/DNS, port, reused output, malformed input and canaries\n",
        failures, cases);
    return failures ? 1 : 0;
}
