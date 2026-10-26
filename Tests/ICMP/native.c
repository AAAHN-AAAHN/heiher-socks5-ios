#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <arpa/inet.h>

#include "hev-main.h"
#include "hev-icmp-engine.h"

typedef struct
{
    atomic_int sent;
    atomic_int replies;
    atomic_int errors;
    atomic_int last_error;
    uint64_t id;
    size_t size;
    const unsigned char *payload;
    int original_source;
} Client;

static atomic_ulong tx, rx;
static atomic_int callbacks_after_free;
static pthread_t server;
static const char *config =
    "main:\n  workers: 2\n  port: 0\n  listen-address: '::1'\n";

static pthread_mutex_t barrier = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t barrier_changed = PTHREAD_COND_INITIALIZER;
static int barrier_entered, barrier_release;
static atomic_int free_finished;

static uint32_t
sum_bytes (const void *data, size_t size, uint32_t sum)
{
    const unsigned char *p = data;
    for (size_t i = 0; i < size; i++)
        sum += (uint32_t)p[i] << ((i & 1) ? 0 : 8);
    return sum;
}

static uint16_t
checksum_v6 (const struct sockaddr_storage *source,
             const struct sockaddr_storage *destination,
             const unsigned char *echo, size_t len)
{
    const struct sockaddr_in6 *a = (const void *)source;
    const struct sockaddr_in6 *b = (const void *)destination;
    uint32_t sum = len + 58;
    sum = sum_bytes (&a->sin6_addr, 16, sum);
    sum = sum_bytes (&b->sin6_addr, 16, sum);
    sum = sum_bytes (echo, len, sum);
    while (sum >> 16)
        sum = (sum & 65535) + (sum >> 16);
    return ~sum;
}

static void
observe (const struct sockaddr *peer, socklen_t len, size_t bytes, int writing,
         void *context)
{
    (void)context;
    assert (peer &&
            (peer->sa_family == AF_INET || peer->sa_family == AF_INET6));
    assert (len >= sizeof (struct sockaddr));
    assert (bytes > 0);
    atomic_fetch_add (writing ? &tx : &rx, bytes);
    errno = EDOM; /* Observer must not change a syscall's reported error. */
}

static void
callback (const HevSocks5IcmpResult *r, void *context)
{
    Client *c = context;
    if (c->id == UINT64_MAX)
        atomic_fetch_add (&callbacks_after_free, 1);
    assert (r->request_id == c->id);
    if (r->event == HEV_SOCKS5_ICMP_SENT) {
        assert (!r->error && r->echo_len == c->size);
        atomic_fetch_add (&c->sent, 1);
    } else if (r->event == HEV_SOCKS5_ICMP_REPLY) {
        assert (!r->error && r->echo && r->echo_len == c->size);
        assert (r->source_len && r->destination_len);
        if (c->original_source) {
            struct in6_addr expected;
            inet_pton (AF_INET6, "2001:db8::5", &expected);
            assert (r->destination.ss_family == AF_INET6);
            assert (!memcmp (
                &((const struct sockaddr_in6 *)&r->destination)->sin6_addr,
                &expected, sizeof (expected)));
        }
        assert (r->echo[0] == (r->source.ss_family == AF_INET ? 0 : 129));
        assert (!r->echo[1]);
        assert (r->echo[4] == (unsigned char)(c->id >> 24));
        assert (r->echo[5] == (unsigned char)(c->id >> 16));
        assert (r->echo[6] == (unsigned char)(c->id >> 8));
        assert (r->echo[7] == (unsigned char)c->id);
        if (c->payload)
            assert (!memcmp (r->echo + 8, c->payload, c->size - 8));
        if (r->source.ss_family == AF_INET)
            assert (!hev_icmp_checksum (r->echo, r->echo_len));
        else
            assert (!checksum_v6 (&r->source, &r->destination, r->echo,
                                  r->echo_len));
        atomic_fetch_add (&c->replies, 1);
    } else {
        assert (r->event == HEV_SOCKS5_ICMP_ERROR && r->error);
        atomic_store (&c->last_error, r->error);
        atomic_fetch_add (&c->errors, 1);
    }
}

static void
gated_callback (const HevSocks5IcmpResult *r, void *context)
{
    if (r->event == HEV_SOCKS5_ICMP_SENT) {
        /* Test-only scheduling barrier models a callback in progress while
         * another thread cancels/frees; production callbacks never wait. */
        pthread_mutex_lock (&barrier);
        barrier_entered = 1;
        pthread_cond_broadcast (&barrier_changed);
        while (!barrier_release)
            pthread_cond_wait (&barrier_changed, &barrier);
        pthread_mutex_unlock (&barrier);
    }
    callback (r, context);
}

static void *
free_client (void *client)
{
    hev_socks5_server_icmp_client_free (client);
    atomic_store (&free_finished, 1);
    return NULL;
}

static void *
run_server (void *unused)
{
    (void)unused;
    assert (!hev_socks5_server_main_from_str ((const void *)config,
                                              strlen (config)));
    return NULL;
}

static uint64_t
start (void)
{
    uint64_t generation = 0;
    unsigned int i;
    assert (!pthread_create (&server, NULL, run_server, NULL));
    for (i = 0; i < 5000 && !generation; i++) {
        generation = hev_socks5_server_icmp_generation ();
        usleep (1000);
    }
    assert (generation);
    return generation;
}

static void
stop (void)
{
    hev_socks5_server_quit ();
    assert (!hev_socks5_server_icmp_generation ());
    assert (!pthread_join (server, NULL));
}

static void
wait_result (Client *c)
{
    unsigned int i;
    for (i = 0;
         i < 3000 && !atomic_load (&c->replies) && !atomic_load (&c->errors);
         i++)
        usleep (1000);
    if (!atomic_load (&c->replies))
        fprintf (stderr, "No reply: sent=%d error=%d\n", atomic_load (&c->sent),
                 atomic_load (&c->last_error));
    assert (atomic_load (&c->sent) == 1);
    assert (atomic_load (&c->replies) == 1);
    assert (!atomic_load (&c->errors));
}

static void
checksum_vectors (void)
{
    struct sockaddr_in dst = { .sin_family = AF_INET };
    struct sockaddr_in6 dst6 = { .sin6_family = AF_INET6 };
    unsigned char echo[8] = { 8, 0, 0, 0, 0x12, 0x34, 0, 0 };
    unsigned int i;
    inet_pton (AF_INET, "127.0.0.1", &dst.sin_addr);
    inet_pton (AF_INET6, "::1", &dst6.sin6_addr);
    const unsigned char known[8] = { 8, 0, 0, 0, 0, 0, 0, 0 };
    assert (hev_icmp_checksum (known, sizeof (known)) == 0xf7ff);
    for (i = 0; i < 65536; i++) {
        HevIcmpRequest *r;
        hev_icmp_echo (echo, AF_INET, 0x12340000U | i);
        assert (echo[0] == 8 && !echo[1]);
        assert (echo[4] == 0x12 && echo[5] == 0x34);
        assert (echo[6] == (i >> 8) && echo[7] == (i & 255));
        assert (!hev_icmp_checksum (echo, sizeof (echo)));
        r = hev_icmp_request_new (NULL, 0, (void *)&dst, sizeof (dst), echo, 8,
                                  1000, NULL);
        assert (r && !memcmp (r->original, echo + 4, 4));
        free (r);
    }
    hev_icmp_echo (echo, AF_INET6, 0x1234ffff);
    HevIcmpRequest *r = hev_icmp_request_new (
        NULL, 0, (void *)&dst6, sizeof (dst6), echo, 8, 1000, NULL);
    assert (r && r->len == 8 && r->echo[0] == 128 && !r->echo[1]);
    free (r);
    puts ("PASS all 65,536 IPv4 sequence checksums and ICMPv6 Echo8 format");
}

static void
received_echo (uint64_t generation)
{
    struct sockaddr_storage source = { 0 }, destination = { 0 };
    struct sockaddr_in6 *a = (void *)&source, *b = (void *)&destination;
    Client c = { .id = 0x12345678, .size = 9, .original_source = 1 };
    unsigned char echo[9] = { 128, 0, 0, 0, 0x12, 0x34, 0x56, 0x78, 0xab };
    HevSocks5IcmpClient *client =
        hev_socks5_server_icmp_client_new (generation, callback, &c);
    uint16_t checksum;
    a->sin6_family = b->sin6_family = AF_INET6;
    inet_pton (AF_INET6, "2001:db8::5", &a->sin6_addr);
    inet_pton (AF_INET6, "::1", &b->sin6_addr);
    checksum = checksum_v6 (&source, &destination, echo, sizeof (echo));
    echo[2] = checksum >> 8;
    echo[3] = checksum;
    c.payload = echo + 8;
    assert (client);
    assert (!hev_socks5_server_icmp_submit (client, c.id, (void *)a,
                                            sizeof (*a), (void *)b, sizeof (*b),
                                            echo, sizeof (echo), 1000));
    wait_result (&c);
    hev_socks5_server_icmp_client_free (client);
    puts (
        "PASS already-received IPv6 Echo, original return address, odd payload and restored checksum");
}

static void
cancel_and_bound (size_t length)
{
    struct sockaddr_in dst = { .sin_family = AF_INET };
    Client a = { .id = 1, .size = 8 }, b = { .id = 2, .size = length };
    HevSocks5IcmpClient *first, *queued;
    pthread_t freeing;
    unsigned char *echo = calloc (1, length);
    unsigned int accepted = 0;
    uint64_t generation;
    unsigned long before;
    uint16_t checksum;
    int res;
    assert (echo);
    echo[0] = 8;
    echo[7] = 2;
    checksum = hev_icmp_checksum (echo, length);
    echo[2] = checksum >> 8;
    echo[3] = checksum;
    inet_pton (AF_INET, "127.0.0.1", &dst.sin_addr);
    generation = start ();
    first = hev_socks5_server_icmp_client_new (generation, gated_callback, &a);
    queued = hev_socks5_server_icmp_client_new (generation, callback, &b);
    assert (first && queued);
    pthread_mutex_lock (&barrier);
    barrier_entered = barrier_release = 0;
    pthread_mutex_unlock (&barrier);
    before = atomic_load (&tx);
    assert (!hev_socks5_server_icmp_ping (first, a.id, (void *)&dst,
                                          sizeof (dst), 1000));
    pthread_mutex_lock (&barrier);
    while (!barrier_entered)
        pthread_cond_wait (&barrier_changed, &barrier);
    pthread_mutex_unlock (&barrier);
    do {
        res = hev_socks5_server_icmp_submit (queued, b.id, NULL, 0,
                                             (void *)&dst, sizeof (dst), echo,
                                             length, 1000);
        if (!res)
            accepted++;
    } while (!res && accepted <= HEV_ICMP_REQUEST_LIMIT);
    assert (res == -EAGAIN && accepted > 0);
    assert (accepted + 1 <= HEV_ICMP_REQUEST_LIMIT);
    assert ((size_t)accepted * length + 8 <= HEV_ICMP_BYTE_LIMIT);
    if (length == 8)
        assert (accepted + 1 == HEV_ICMP_REQUEST_LIMIT);
    else
        assert ((size_t)(accepted + 1) * length + 8 > HEV_ICMP_BYTE_LIMIT);
    hev_socks5_server_icmp_cancel (queued);
    hev_socks5_server_icmp_client_free (queued);
    b.id = UINT64_MAX;
    atomic_store (&free_finished, 0);
    assert (!pthread_create (&freeing, NULL, free_client, first));
    usleep (10000);
    assert (!atomic_load (&free_finished));
    pthread_mutex_lock (&barrier);
    barrier_release = 1;
    pthread_cond_broadcast (&barrier_changed);
    pthread_mutex_unlock (&barrier);
    assert (!pthread_join (freeing, NULL));
    a.id = UINT64_MAX;
    stop ();
    assert (atomic_load (&tx) - before == 8);
    assert (!atomic_load (&callbacks_after_free));
    free (echo);
    printf (
        "PASS deterministic cancel before send, callback quiescence, %s bound\n",
        length == 8 ? "request count" : "payload bytes");
}

#ifdef ICMP_TEST_IO
extern void run_engine_checks (void);
extern atomic_int icmp_test_suppress, icmp_test_send_error;
extern atomic_int icmp_test_truncate, icmp_test_wrong_id;
extern atomic_int icmp_test_open_error, icmp_test_short_send;
extern atomic_int icmp_test_opened, icmp_test_live, icmp_test_defer;

static void
fault_case (int fault)
{
    struct sockaddr_in dst = { .sin_family = AF_INET };
    Client c = { .id = 0x12345678, .size = fault == 3 ? 64 : 8 };
    unsigned char echo[64] = { 8, 0, 0, 0, 0x12, 0x34, 0x56, 0x78 };
    HevSocks5IcmpClient *client;
    uint16_t checksum = hev_icmp_checksum (echo, c.size);
    uint64_t generation = start ();
    unsigned long before_tx = atomic_load (&tx), before_rx = atomic_load (&rx);
    echo[2] = checksum >> 8;
    echo[3] = checksum;
    inet_pton (AF_INET, "127.0.0.1", &dst.sin_addr);
    int send_error = fault == 0 ? EACCES :
                     fault == 6 ? EAGAIN :
                     fault == 7 ? EBUSY :
                                  0;
    atomic_store (&icmp_test_send_error, send_error);
    atomic_store (&icmp_test_suppress, fault == 1);
    atomic_store (&icmp_test_wrong_id, fault == 2);
    atomic_store (&icmp_test_truncate, fault == 3);
    atomic_store (&icmp_test_open_error, fault == 4);
    atomic_store (&icmp_test_short_send, fault == 5);
    client = hev_socks5_server_icmp_client_new (generation, callback, &c);
    assert (client);
    assert (!hev_socks5_server_icmp_submit (client, c.id, NULL, 0, (void *)&dst,
                                            sizeof (dst), echo, c.size, 20));
    for (unsigned int i = 0; i < 2000 && !atomic_load (&c.errors); i++)
        usleep (1000);
    assert (atomic_load (&c.errors) == 1 && !atomic_load (&c.replies));
    assert (atomic_load (&c.sent) == (fault > 0 && fault < 4));
    assert (atomic_load (&c.last_error) == (send_error ? send_error :
                                            fault == 4 ? EACCES :
                                            fault == 5 ? EIO :
                                                         ETIMEDOUT));
    assert (atomic_load (&tx) - before_tx == (fault > 0 && fault < 4 ? c.size :
                                              fault == 5             ? 4 :
                                                                       0));
    assert (atomic_load (&rx) - before_rx == (fault == 2 ? 8 :
                                              fault == 3 ? 12 :
                                                           0));
    hev_socks5_server_icmp_client_free (client);
    stop ();
    assert (!atomic_load (&icmp_test_live));
    atomic_store (&icmp_test_send_error, 0);
    atomic_store (&icmp_test_suppress, 0);
    atomic_store (&icmp_test_wrong_id, 0);
    atomic_store (&icmp_test_truncate, 0);
    atomic_store (&icmp_test_open_error, 0);
    atomic_store (&icmp_test_short_send, 0);
    printf (
        "PASS injected failure %d: precise terminal event and actual consumed/accepted bytes\n",
        fault);
}
#endif

int
main (void)
{
    struct sockaddr_in dst = { .sin_family = AF_INET };
    struct sockaddr_in6 dst6 = { .sin6_family = AF_INET6, .sin6_scope_id = 1 };
    uint64_t generation, next;
    Client c[4] = { 0 };
    HevSocks5IcmpClient *client[4];
    unsigned char *echo = malloc (65508);
    unsigned long before_tx, before_rx;
    int i;
    assert (echo);
#ifdef ICMP_TEST_IO
    atomic_store (&icmp_test_defer, 1);
#endif
    checksum_vectors ();
    inet_pton (AF_INET, "127.0.0.1", &dst.sin_addr);
    inet_pton (AF_INET6, "::1", &dst6.sin6_addr);
    assert (!hev_socks5_server_icmp_generation ());
    assert (!hev_socks5_server_icmp_client_new (123, callback, &c[0]));
    assert (!hev_socks5_server_icmp_set_io_observer (observe, NULL));
    generation = start ();
    assert (hev_socks5_server_icmp_set_io_observer (NULL, NULL) == -EBUSY);
    for (i = 0; i < 4; i++) {
        c[i].id = 0x12345678; /* Intentionally identical across clients. */
        c[i].size = i < 2 ? 8 : i == 2 ? 65508 : 60000;
        client[i] =
            hev_socks5_server_icmp_client_new (generation, callback, &c[i]);
        assert (client[i]);
    }
    before_tx = atomic_load (&tx);
    before_rx = atomic_load (&rx);
    assert (!hev_socks5_server_icmp_ping (client[0], c[0].id, (void *)&dst,
                                          sizeof (dst), 1000));
    assert (!hev_socks5_server_icmp_ping (client[1], c[1].id, (void *)&dst6,
                                          sizeof (dst6), 1000));
    for (i = 2; i < 4; i++) {
        uint16_t checksum;
        size_t j;
        memset (echo, 0, 8);
        echo[0] = i == 2 ? 8 : 128;
        echo[4] = 0x12;
        echo[5] = 0x34;
        echo[6] = 0x56;
        echo[7] = 0x78;
        for (j = 8; j < c[i].size; j++)
            echo[j] = j * 37 + 11;
        if (i == 2) {
            checksum = hev_icmp_checksum (echo, c[i].size);
            echo[2] = checksum >> 8;
            echo[3] = checksum;
        }
        c[i].payload = echo + 8;
        assert (!hev_socks5_server_icmp_submit (
            client[i], c[i].id, NULL, 0, i == 2 ? (void *)&dst : (void *)&dst6,
            i == 2 ? sizeof (dst) : sizeof (dst6), echo, c[i].size, 1000));
        wait_result (&c[i]);
    }
    wait_result (&c[0]);
    wait_result (&c[1]);
    assert (atomic_load (&tx) - before_tx == 8 + 8 + 65508 + 60000);
    assert (atomic_load (&rx) - before_rx >= 8 + 8 + 65508 + 60000);
#ifdef ICMP_TEST_IO
    puts (
        "PASS simulated IPv4/IPv6 socket responses, large payload, multiple clients, kernel ID rewrite, exact send bytes");
    assert (atomic_load (&icmp_test_opened) == 2);
    puts (
        "PASS server retains a deferred queue head and completes it without a false error");
#else
    puts (
        "PASS real IPv4/IPv6 loopback, large payload, multiple clients, ID restore, exact send bytes");
#endif
    received_echo (generation);
    memset (echo, 0, 8);
    echo[0] = 3;
    assert (hev_socks5_server_icmp_submit (client[0], c[0].id, NULL, 0,
                                           (void *)&dst, sizeof (dst), echo, 8,
                                           1000) == -EPROTONOSUPPORT);
    assert (hev_socks5_server_icmp_ping (client[0], c[0].id, (void *)&dst,
                                         sizeof (dst), 0) == -EINVAL);
    for (i = 0; i < 3; i++) {
        hev_socks5_server_icmp_client_free (client[i]);
        c[i].id = UINT64_MAX;
    }
    stop ();
    next = start ();
    assert (next != generation);
    assert (hev_socks5_server_icmp_ping (client[3], c[3].id, (void *)&dst,
                                         sizeof (dst), 1000) == -ENOTCONN);
    hev_socks5_server_icmp_client_free (client[3]);
    stop ();
    assert (!atomic_load (&callbacks_after_free));
    cancel_and_bound (8);
    cancel_and_bound (65508);
#ifdef ICMP_TEST_IO
    for (i = 0; i < 8; i++)
        fault_case (i);
    run_engine_checks ();
#endif
    assert (!hev_socks5_server_icmp_set_io_observer (NULL, NULL));
    free (echo);
    puts (
        "PASS invalid input, no late callback after free, stop/restart and stale generation");
    return 0;
}
