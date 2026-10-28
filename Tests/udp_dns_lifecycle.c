/* Real DNS proxy, aide reactor and task-system ownership. Control thread
 * creation, completed replies and EINTR/no-transfer results at their boundaries. */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <netdb.h>
#include <netinet/in.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <hev-task.h>
#include <hev-task-dns.h>
#include <hev-task-system.h>
#include "kern/aide/hev-task-aide.h"

enum
{
    FIXTURE_IDLE,
    FIXTURE_RETRY,
    FIXTURE_ACK,
    FIXTURE_QUEUED,
    FIXTURE_INTR_OWNER_WRITE,
    FIXTURE_INTR_OWNER_READ,
    FIXTURE_INTR_AIDE_READ,
    FIXTURE_INTR_AIDE_WRITE
};
enum
{
    FIXTURE_PEERS = 4,
    FIXTURE_TASKS = 4,
    FIXTURE_LOOPS = 24
};
static pthread_mutex_t fixture_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t fixture_condition = PTHREAD_COND_INITIALIZER;
static _Thread_local int fixture_role;
static atomic_int fixture_mode, fixture_held, fixture_done;
static atomic_int fixture_waiters, fixture_registered, fixture_creates;
static atomic_int fixture_requests, fixture_replies, fixture_lookups;
static atomic_int fixture_injected;
static atomic_int fixture_reply_fd, fixture_request_fd;
static int fixture_release;
static int fixture_create (pthread_t *, const pthread_attr_t *,
                           void *(*)(void *), void *);
static int fixture_mutex_lock (pthread_mutex_t *);
static int fixture_aide_add (HevTaskAideWork *);
static ssize_t fixture_read (int, void *, size_t);
static ssize_t fixture_write (int, const void *, size_t);

#define pthread_create fixture_create
#define pthread_mutex_lock fixture_mutex_lock
#include "kern/aide/hev-task-aide.c"
#undef pthread_mutex_lock
#undef pthread_create

#define hev_task_aide_add fixture_aide_add
#define read fixture_read
#define write fixture_write
#include "lib/dns/hev-task-dns-proxy.c"
#undef write
#undef read
#undef hev_task_aide_add

static void
fixture_hold (void)
{
    assert (!pthread_mutex_lock (&fixture_lock));
    atomic_store (&fixture_held, 1);
    while (!fixture_release)
        assert (!pthread_cond_wait (&fixture_condition, &fixture_lock));
    assert (!pthread_mutex_unlock (&fixture_lock));
}

static void
fixture_resume (void)
{
    assert (!pthread_mutex_lock (&fixture_lock));
    fixture_release = 1;
    assert (!pthread_cond_signal (&fixture_condition));
    assert (!pthread_mutex_unlock (&fixture_lock));
}

static int
fixture_create (pthread_t *id, const pthread_attr_t *attributes,
                void *(*entry) (void *), void *data)
{
    if (!atomic_fetch_add (&fixture_creates, 1) &&
        atomic_load (&fixture_mode) == FIXTURE_RETRY) {
        fixture_hold ();
        return EAGAIN;
    }
    return pthread_create (id, attributes, entry, data);
}

static int
fixture_mutex_lock (pthread_mutex_t *lock)
{
    if (fixture_role == 2)
        atomic_fetch_add (&fixture_waiters, 1);
    return pthread_mutex_lock (lock);
}

static void
fixture_handler (unsigned int events, void *data)
{
    hev_task_dns_server_handler (events, data);
    atomic_fetch_add (&fixture_done, 1);
}

static int
fixture_aide_add (HevTaskAideWork *work)
{
    int result, mode = atomic_load (&fixture_mode);
    if (mode >= FIXTURE_ACK) {
        HevTaskDNSProxy *proxy = work->data;
        atomic_store (&fixture_reply_fd, work->fd);
        atomic_store (&fixture_request_fd, proxy->fd);
        if (mode == FIXTURE_ACK || mode == FIXTURE_QUEUED)
            work->handler = fixture_handler;
    }
    result = hev_task_aide_add (work);
    if (fixture_role == 2 && !result)
        atomic_fetch_add (&fixture_registered, 1);
    return result;
}

static ssize_t
fixture_read (int fd, void *buffer, size_t length)
{
    int mode = atomic_load (&fixture_mode);
    if (((mode == FIXTURE_INTR_OWNER_READ &&
          fd == atomic_load (&fixture_request_fd)) ||
         (mode == FIXTURE_INTR_AIDE_READ &&
          fd == atomic_load (&fixture_reply_fd))) &&
        !atomic_exchange (&fixture_injected, 1)) {
        errno = EINTR;
        return -1;
    }
    return read (fd, buffer, length);
}

static ssize_t
fixture_write (int fd, const void *buffer, size_t length)
{
    int mode = atomic_load (&fixture_mode);
    ssize_t result;
    if (((mode == FIXTURE_INTR_OWNER_WRITE &&
          fd == atomic_load (&fixture_request_fd)) ||
         (mode == FIXTURE_INTR_AIDE_WRITE &&
          fd == atomic_load (&fixture_reply_fd))) &&
        !atomic_exchange (&fixture_injected, 1)) {
        errno = EINTR;
        return -1;
    }
    result = write (fd, buffer, length);
    if (result == 1 && (mode == FIXTURE_ACK || mode == FIXTURE_QUEUED)) {
        if (fd == atomic_load (&fixture_request_fd))
            atomic_fetch_add (&fixture_requests, 1);
        if (fd == atomic_load (&fixture_reply_fd) &&
            !atomic_fetch_add (&fixture_replies, 1))
            fixture_hold ();
    }
    return result;
}

static void
fixture_resolve (void *unused)
{
    struct addrinfo hints = { 0 }, *result = NULL;
    int status;
    (void)unused;
    hints.ai_family = AF_INET6;
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_flags = AI_NUMERICHOST | AI_NUMERICSERV;
    status = hev_task_dns_getaddrinfo ("::1", "61234", &hints, &result);
    if (fixture_role == 1) {
        assert (status == EAI_SYSTEM && errno == EIO && !result);
    } else {
        assert (!status && result && result->ai_family == AF_INET6);
        assert (result->ai_addrlen == sizeof (struct sockaddr_in6));
        freeaddrinfo (result);
    }
}

static void
fixture_run (void (*entry) (void *), int count)
{
    int i;
    assert (!hev_task_system_init ());
    for (i = 0; i < count; i++) {
        HevTask *task = hev_task_new (-1);
        assert (task);
        hev_task_run (task, entry, NULL);
    }
    hev_task_system_run ();
    hev_task_system_fini ();
}

static void *
fixture_retry_owner (void *role)
{
    fixture_role = *(int *)role;
    fixture_run (fixture_resolve, 1);
    return NULL;
}

static void
fixture_retry (void)
{
    pthread_t first, peers[FIXTURE_PEERS];
    int first_role = 1, peer_role = 2, i;
    atomic_store (&fixture_mode, FIXTURE_RETRY);
    assert (!pthread_create (&first, NULL, fixture_retry_owner, &first_role));
    while (!atomic_load (&fixture_held))
        usleep (100);
    for (i = 0; i < FIXTURE_PEERS; i++)
        assert (
            !pthread_create (&peers[i], NULL, fixture_retry_owner, &peer_role));
    while (atomic_load (&fixture_waiters) != FIXTURE_PEERS &&
           atomic_load (&fixture_registered) != FIXTURE_PEERS)
        usleep (100);
    fixture_resume ();
    assert (!pthread_join (first, NULL));
    for (i = 0; i < FIXTURE_PEERS; i++)
        assert (!pthread_join (peers[i], NULL));
    assert (atomic_load (&fixture_creates) == 2);
    assert (atomic_load (&fixture_registered) == FIXTURE_PEERS);
    atomic_store (&fixture_mode, FIXTURE_IDLE);
}

static void
fixture_mixed_lookup (void *unused)
{
    struct addrinfo hints = { 0 };
    struct sockaddr_in6 address = { 0 };
    struct sockaddr invalid = { .sa_family = AF_UNSPEC };
    int i;
    (void)unused;
    address.sin6_family = AF_INET6;
#ifdef __APPLE__
    address.sin6_len = sizeof (address);
#endif
    address.sin6_addr = in6addr_loopback;
    address.sin6_port = htons (61234);
    hints.ai_family = AF_INET6;
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_flags = AI_NUMERICHOST | AI_NUMERICSERV;
    for (i = 0; i < FIXTURE_LOOPS; i++) {
        struct addrinfo *result = NULL;
        char node[64], service[16];
        assert (!hev_task_dns_getaddrinfo ("::1", "61234", &hints, &result));
        assert (result && result->ai_addrlen == sizeof (address));
        assert (!memcmp (result->ai_addr, &address, sizeof (address)));
        freeaddrinfo (result);
        result = NULL;
        assert (hev_task_dns_getaddrinfo ("invalid-numeric-host", "61234",
                                          &hints, &result));
        assert (!result);
        assert (!hev_task_dns_getnameinfo (
            (struct sockaddr *)&address, sizeof (address), node, sizeof (node),
            service, sizeof (service), NI_NUMERICHOST | NI_NUMERICSERV));
        assert (!strcmp (node, "::1") && !strcmp (service, "61234"));
        assert (hev_task_dns_getnameinfo (&invalid, sizeof (invalid), node,
                                          sizeof (node), service,
                                          sizeof (service), NI_NUMERICHOST));
        atomic_fetch_add (&fixture_lookups, 4);
    }
}

static void *
fixture_parallel_owner (void *unused)
{
    (void)unused;
    fixture_run (fixture_mixed_lookup, FIXTURE_TASKS);
    return NULL;
}

static void
fixture_parallel (void)
{
    pthread_t peers[FIXTURE_PEERS];
    int count, i;
    for (count = 1; count <= FIXTURE_PEERS; count *= 2) {
        for (i = 0; i < count; i++)
            assert (!pthread_create (&peers[i], NULL, fixture_parallel_owner,
                                     NULL));
        for (i = 0; i < count; i++)
            assert (!pthread_join (peers[i], NULL));
    }
    assert (atomic_load (&fixture_lookups) ==
            7 * FIXTURE_TASKS * FIXTURE_LOOPS * 4);
}

static void *
fixture_queued_release (void *unused)
{
    (void)unused;
    while (!atomic_load (&fixture_held) || atomic_load (&fixture_requests) != 2)
        usleep (100);
    /* The second request is in the socket before the first callback returns. */
    assert (!atomic_load (&fixture_done));
    fixture_resume ();
    return NULL;
}

static void
fixture_ack (int queued)
{
    pthread_t releaser;
    fixture_release = 0;
    atomic_store (&fixture_held, 0);
    atomic_store (&fixture_done, 0);
    atomic_store (&fixture_requests, 0);
    atomic_store (&fixture_replies, 0);
    atomic_store (&fixture_mode, queued ? FIXTURE_QUEUED : FIXTURE_ACK);
    if (queued)
        assert (
            !pthread_create (&releaser, NULL, fixture_queued_release, NULL));
    fixture_run (fixture_resolve, queued ? 2 : 1);
    if (queued) {
        assert (!pthread_join (releaser, NULL));
    } else {
        while (!atomic_load (&fixture_held))
            usleep (100);
        assert (!atomic_load (&fixture_done));
        /* The receiving task, proxy and its actual allocator are already gone. */
        fixture_resume ();
    }
    while (atomic_load (&fixture_done) != (queued ? 2 : 1))
        usleep (100);
    assert (atomic_load (&fixture_requests) == (queued ? 2 : 1));
    assert (atomic_load (&fixture_replies) == (queued ? 2 : 1));
    atomic_store (&fixture_mode, FIXTURE_IDLE);
}

static void
fixture_interruptions (void)
{
    int mode;
    for (mode = FIXTURE_INTR_OWNER_WRITE; mode <= FIXTURE_INTR_AIDE_WRITE;
         mode++) {
        atomic_store (&fixture_injected, 0);
        atomic_store (&fixture_mode, mode);
        fixture_run (fixture_resolve, 1);
        assert (atomic_load (&fixture_injected));
    }
    atomic_store (&fixture_mode, FIXTURE_IDLE);
}

static void
fixture_deadline (int signal_number)
{
    static const char message[] = "FAIL: native DNS lifecycle deadline\n";
    (void)signal_number;
    (void)write (STDERR_FILENO, message, sizeof (message) - 1);
    _exit (91);
}

int
main (int argc, char **argv)
{
    const char *selected = argc == 2 ? argv[1] : "all";
    assert (argc <= 2);
    assert (!strcmp (selected, "all") || !strcmp (selected, "retry") ||
            !strcmp (selected, "ack") || !strcmp (selected, "queued") ||
            !strcmp (selected, "parallel") || !strcmp (selected, "interrupt"));
    signal (SIGALRM, fixture_deadline);
    alarm (15);
    if (!strcmp (selected, "all") || !strcmp (selected, "retry"))
        fixture_retry ();
    if (!strcmp (selected, "all") || !strcmp (selected, "parallel"))
        fixture_parallel ();
    if (!strcmp (selected, "all") || !strcmp (selected, "ack"))
        fixture_ack (0);
    if (!strcmp (selected, "all") || !strcmp (selected, "queued"))
        fixture_ack (1);
    if (!strcmp (selected, "all") || !strcmp (selected, "interrupt"))
        fixture_interruptions ();
    alarm (0);
    puts (
        "PASS: native DNS initialization, readiness, callback teardown and EINTR");
    return 0;
}
