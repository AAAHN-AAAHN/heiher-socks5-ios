#define _GNU_SOURCE
/* Include the actual setup implementations. DNS completion is controlled at its
 * API boundary while real Hev tasks suspend/resume; sockets and bind/connect are
 * real. This portable gate complements the native DNS-aide integration probe. */
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <netdb.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <hev-task.h>
#include <hev-task-system.h>
#include <hev-task-io.h>
#include <hev-task-io-socket.h>
#include <hev-task-dns.h>
#include "hev-config.h"
#include "hev-socks5-session.h"
#include "hev-socks5-misc.h"

static int setup_dns (const char *, const char *, const struct addrinfo *,
                      struct addrinfo **);
static int setup_socket (int);
static int setup_bind (int, const struct sockaddr *, socklen_t);
static int setup_connect (int, const struct sockaddr *, socklen_t,
                          HevTaskIOYielder, void *);
static void *setup_tcp_iface (void);
static unsigned int setup_io_calls;

#define hev_task_dns_getaddrinfo setup_dns
#include "hev-socks5-misc.c"
#ifdef hev_meter_recv
#include "hev-socks5-meter.h"
#endif
#define hev_socks5_socket setup_socket
#define hev_socks5_tcp_iface setup_tcp_iface
#define hev_task_io_socket_connect setup_connect
#define hev_task_io_socket_recv(...) \
    (setup_io_calls++, hev_task_io_socket_recv (__VA_ARGS__))
#define hev_task_io_socket_send(...) \
    (setup_io_calls++, hev_task_io_socket_send (__VA_ARGS__))
#include "hev-socks5-server.c"
#undef hev_task_io_socket_recv
#undef hev_task_io_socket_send
#undef hev_socks5_socket
#undef hev_socks5_tcp_iface
#undef hev_task_io_socket_connect
#undef task_io_yielder
/* The native server and its core intentionally have separate logger APIs. */
#undef LOG_D
#undef LOG_I
#undef LOG_W
#undef LOG_E
#undef LOG_ON
#undef LOG_ON_D
#undef LOG_ON_I
#undef LOG_ON_W
#undef LOG_ON_E
#include "hev-misc.c"
#undef hev_task_dns_getaddrinfo
#define bind setup_bind
#include "hev-socks5-session.c"
#undef bind
#include "hev-socks5-worker.c"

static atomic_int iface_calls;
static HevSocks5Session *session;
static HevTask *owner;
static int pending, released, completed, started, returned, stage, cancel_case;
static int stopped, sockets_after_stop, binds_after_stop, connects_after_stop;
static int control, client, result, created[2], created_count, failures;
static unsigned char request[32];
static size_t request_length;

static void *
setup_tcp_iface (void)
{
    atomic_fetch_add (&iface_calls, 1);
    return hev_socks5_tcp_iface ();
}

static int
setup_dns (const char *name, const char *service, const struct addrinfo *hints,
           struct addrinfo **address)
{
    assert (!strcmp (name, "localhost") && !pending);
    pending = 1;
    while (!released)
        hev_task_yield (HEV_TASK_WAITIO);
    completed = 1;
    /* Numeric loopback keeps the permanent fixture independent of DNS/network
     * configuration. Only the resolver API is substituted, not caller checks. */
    return getaddrinfo ("::1", service, hints, address);
}

static int
setup_socket (int type)
{
    int fd = hev_socks5_socket (type);
    sockets_after_stop += stopped;
    assert (fd >= 0 && created_count < 2);
    created[created_count++] = fd;
    return fd;
}

static int
setup_bind (int fd, const struct sockaddr *addr, socklen_t size)
{
    binds_after_stop += stopped;
    return bind (fd, addr, size);
}

static int
setup_connect (int fd, const struct sockaddr *addr, socklen_t size,
               HevTaskIOYielder yielder, void *data)
{
    connects_after_stop += stopped;
    return hev_task_io_socket_connect (fd, addr, size, yielder, data);
}

static void *
class_reader (void *unused)
{
    HevObject object = { .klass = hev_socks5_session_class () };
    HevSocks5ServerClass *server_class =
        HEV_SOCKS5_SERVER_CLASS (hev_socks5_server_class ());
    HevSocks5TCPIface *tcp =
        HEV_OBJECT_GET_IFACE (&object, HEV_SOCKS5_TCP_TYPE);
    HevSocks5UDPIface *udp =
        HEV_OBJECT_GET_IFACE (&object, HEV_SOCKS5_UDP_TYPE);
    (void)unused;
    assert (tcp && tcp->splicer && udp && udp->splicer && udp->get_fd);
    assert (tcp->splicer == server_class->tcp.splicer &&
            udp->splicer == server_class->udp.splicer &&
            udp->get_fd == server_class->udp.get_fd);
    return NULL;
}

static void
class_setup (void)
{
    pthread_t readers[4];
    int fd = socket (AF_INET6, SOCK_STREAM, 0);
    HevSocks5Worker *worker;
    assert (fd >= 0 && !hev_task_system_init ());
    worker = hev_socks5_worker_new (fd);
    assert (worker);
    /* Must precede any explicit class lookup: worker_new owns initialization
     * before proxy startup can publish the worker to another thread. */
    if (atomic_load (&iface_calls) != 1) {
        failures++;
        puts ("FAIL: worker_new did not initialize session interfaces");
        /* Keep the negative run safe enough to test the other boundaries. */
        hev_socks5_session_class ();
    } else {
        puts ("PASS: worker_new initializes session interfaces before readers");
    }
    for (int i = 0; i < 4; i++)
        assert (!pthread_create (&readers[i], NULL, class_reader, NULL));
    for (int i = 0; i < 4; i++)
        assert (!pthread_join (readers[i], NULL));
    hev_socks5_worker_destroy (worker);
    hev_task_system_fini ();
}

static int
listener (struct sockaddr_in6 *address)
{
    socklen_t size = sizeof (*address);
    int fd = socket (AF_INET6, SOCK_STREAM, 0);
    assert (fd >= 0);
    memset (address, 0, size);
    address->sin6_family = AF_INET6;
    address->sin6_addr = in6addr_loopback;
    assert (!bind (fd, (struct sockaddr *)address, size));
    assert (!listen (fd, 1));
    assert (!getsockname (fd, (struct sockaddr *)address, &size));
    return fd;
}

static void
handshake_owner (void *unused)
{
    (void)unused;
    started = 1;
    assert (!hev_task_add_fd (hev_task_self (), control, POLLIN | POLLOUT));
    if (stage == 5) {
        /* A terminal session must not be rearmed by handshake entry. */
        stopped = 1;
        hev_socks5_set_timeout (HEV_SOCKS5 (session), 0);
    }
    result = hev_socks5_server_handshake (HEV_SOCKS5_SERVER (session));
    assert (stage >= 4 || completed);
    returned = 1;
    hev_object_unref (HEV_OBJECT (session));
    session = NULL;
}

static void
handshake_coordinator (void *unused)
{
    (void)unused;
    for (int i = 0; !(stage == 4 ? started : pending); i++) {
        assert (i < 1000);
        hev_task_sleep (1);
    }
    assert (!returned);
    if (cancel_case) {
        stopped = 1;
        hev_socks5_session_terminate (session);
    }
    if (stage == 4) {
        /* Make auth readable at the same cancellation wake. The yielder must
         * reject cancellation before the recv helper retries the ready data. */
        assert (send (client, request, request_length, 0) == request_length);
        hev_task_wakeup (owner);
    } else {
        hev_task_sleep (1);
        assert (!returned && !completed);
        released = 1;
        hev_task_wakeup (owner);
    }
}

static void
handshake_setup (int where, int cancel)
{
    static const char *configs[] = {
        "main:\n  workers: 1\n  listen-address: '::1'\n  port: 1080\n",
        "main:\n  workers: 1\n  listen-address: '::1'\n  port: 1080\n  udp-listen-address: localhost\n",
        "main:\n  workers: 1\n  listen-address: '::1'\n  port: 1080\n  udp-public-address-v6: localhost\n",
        "main:\n  workers: 1\n  listen-address: '::1'\n  port: 1080\n  bind-address-v6: localhost\n"
    };
    struct sockaddr_in6 address, target;
    unsigned char response[64];
    size_t bytes = 0, expected;
    HevTask *coordinator;
    const char *config = configs[where < 4 ? where : 0];
    int acceptor, destination = -1, flags, bad;
    stage = where;
    cancel_case = cancel;
    pending = released = completed = started = returned = stopped = 0;
    sockets_after_stop = binds_after_stop = connects_after_stop =
        created_count = 0;
    setup_io_calls = 0;
    assert (!hev_config_init_from_str ((const unsigned char *)config,
                                       strlen (config)));
    assert (!hev_task_system_init ());
    acceptor = listener (&address);
    client = socket (AF_INET6, SOCK_STREAM, 0);
    assert (client >= 0 &&
            !connect (client, (struct sockaddr *)&address, sizeof (address)));
    control = accept (acceptor, NULL, NULL);
    flags = fcntl (control, F_GETFL);
    assert (control >= 0 && flags >= 0);
    assert (!fcntl (control, F_SETFL, flags | O_NONBLOCK));
    close (acceptor);
    memset (request, 0, sizeof (request));
    memcpy (request, (unsigned char[]){ 5, 1, 0, 5, 3, 0, 4 }, 7);
    request_length = 25;
    if (where == 0) {
        request[6] = HEV_SOCKS5_ADDR_TYPE_NAME;
        request[7] = 9;
        memcpy (request + 8, "localhost", 9);
        request_length = 19;
    } else if (where == 3) {
        destination = listener (&target);
        request[4] = HEV_SOCKS5_REQ_CMD_CONNECT;
        memcpy (request + 7, &target.sin6_addr, 16);
        memcpy (request + 23, &target.sin6_port, 2);
    }
    if (where != 4)
        assert (send (client, request, request_length, 0) == request_length);
    session = hev_socks5_session_new (control);
    owner = hev_task_new (-1);
    coordinator = where == 5 ? NULL : hev_task_new (-1);
    assert (session && owner && (where == 5 || coordinator));
    session->task = owner;
    hev_task_run (owner, handshake_owner, NULL);
    if (coordinator)
        hev_task_run (coordinator, handshake_coordinator, NULL);
    hev_task_system_run ();
    assert (returned);
    /* TCP may split any write; accumulate until destructor EOF/reset. */
    while (bytes < sizeof (response)) {
        ssize_t count =
            recv (client, response + bytes, sizeof (response) - bytes, 0);
        if (count > 0)
            bytes += count;
        else if (!count || (count < 0 && errno == ECONNRESET))
            break;
        else
            assert (errno == EINTR);
    }
    expected = cancel ? (where >= 4 ? 0 : 2) : 24;
    bad = bytes != expected || (cancel ? result >= 0 : result != 0) ||
          sockets_after_stop || binds_after_stop || connects_after_stop ||
          (where == 5 && (setup_io_calls || pending || created_count));
    if (bytes >= 2)
        assert (response[0] == 5 && response[1] == 0);
    if (!cancel)
        assert (bytes >= 4 && response[2] == 5 && response[3] == 0);
    for (int i = 0; i < created_count; i++)
        assert (fcntl (created[i], F_GETFD) == -1 && errno == EBADF);
    assert (fcntl (control, F_GETFD) == -1 && errno == EBADF);
    printf (
        "%s: setup stage=%d cancel=%d result=%d response=%zu "
        "after-stop socket/bind/connect=%d/%d/%d io-calls=%u; descriptors closed\n",
        bad ? "FAIL" : "PASS", where, cancel, result, bytes, sockets_after_stop,
        binds_after_stop, connects_after_stop, setup_io_calls);
    failures += bad;
    close (client);
    if (destination >= 0)
        close (destination);
    hev_task_system_fini ();
}

typedef struct
{
    HevSocks5 *self;
    HevTask *waiter;
    int cancel;
} YieldEnd;

static void
yield_end (void *data)
{
    YieldEnd *end = data;
    if (end->cancel)
        hev_socks5_set_timeout (end->self, 0);
    hev_task_wakeup (end->waiter);
}

static void
yield_setup (void *unused)
{
    HevSocks5 self = { .timeout = 0 };
    int before = failures;
    (void)unused;
    failures += hev_socks5_task_io_yielder (HEV_TASK_YIELD, &self) != -1;
    self.timeout = 1;
    failures += hev_socks5_task_io_yielder (HEV_TASK_WAITIO, &self) != -1;
    failures += self.timeout != 0;
    for (int type = HEV_TASK_YIELD; type <= HEV_TASK_WAITIO; type++) {
        for (int finite = 0; finite <= 1; finite++) {
            for (int cancel = 0; cancel <= 1; cancel++) {
                YieldEnd end = { &self, hev_task_self (), cancel };
                HevTask *ender = hev_task_new (-1);
                assert (ender);
                self.timeout = finite ? 1000 : -1;
                hev_task_run (ender, yield_end, &end);
                failures += hev_socks5_task_io_yielder (type, &self) !=
                            (cancel ? -1 : 0);
                failures += cancel ? self.timeout != 0 :
                                     self.timeout != (finite ? 1000 : -1);
            }
        }
    }
    printf ("%s: generic yield/wait finite/infinite cancellation and expiry\n",
            failures == before ? "PASS" : "FAIL");
}

int
main (void)
{
    HevTask *task;
    signal (SIGPIPE, SIG_IGN);
    alarm (15);
    class_setup ();
    for (int where = 0; where < 5; where++)
        for (int cancel = 0; cancel <= 1; cancel++)
            handshake_setup (where, cancel);
    handshake_setup (5, 1);
    assert (!hev_task_system_init ());
    task = hev_task_new (-1);
    assert (task);
    hev_task_run (task, yield_setup, NULL);
    hev_task_system_run ();
    /* The scheduler consumes each started task's initial reference on exit. */
    hev_task_system_fini ();
    alarm (0);
    printf ("session setup: %d failures\n", failures);
    return failures ? 1 : 0;
}
