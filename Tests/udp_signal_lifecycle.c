/* Real library main/proxy/worker lifecycle. Hooks control only signal
 * scheduling and the explicitly selected initialization failure. */
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include <hev-task.h>
#include <hev-task-io.h>
#include "hev-main.h"
#include "hev-socks5-worker.h"

enum
{
    FIX_LIVE,
    FIX_NOTIFY_FAIL,
    FIX_PIPE_FAIL,
    FIX_RELOAD_FAIL,
    FIX_IGNORED,
    FIX_MIXED,
    FIX_EINTR,
    FIX_FLOOD
};
static pthread_t fixture_owner, fixture_carrier;
static atomic_int fixture_started, fixture_captured, fixture_release;
static atomic_int fixture_drain, fixture_finished;
static volatile sig_atomic_t fixture_host_reload, fixture_host_pipe;
static int fixture_created, fixture_faults;
static atomic_int fixture_mode, fixture_fds[12];
static _Atomic (HevSocks5Worker *) fixture_borrowed;
static int fixture_workers;
static atomic_int fixture_publications, fixture_notifications;
static atomic_int fixture_gate_armed, fixture_gate_hits;
static atomic_int fixture_eintr_armed, fixture_eintr_hits, fixture_queued;
static _Thread_local atomic_int fixture_in_signal;
static void fixture_worker_start (HevSocks5Worker *);
static HevSocks5Worker *fixture_worker_new (int);
static void fixture_signal_notify (HevSocks5Worker *);
static int fixture_usleep (useconds_t);
static int fixture_sigaction (int, const struct sigaction *,
                              struct sigaction *);
static int fixture_ioctl (int, unsigned long, void *);
static void fixture_set_auth (HevSocks5Worker *, HevSocks5Authenticator *);
static ssize_t fixture_write (int, const void *, size_t);
static ssize_t fixture_read (int, void *, size_t, HevTaskIOYielder, void *);

#define hev_socks5_worker_start fixture_worker_start
#define hev_socks5_worker_new fixture_worker_new
#define hev_socks5_worker_signal_reload fixture_signal_notify
#define hev_socks5_worker_set_auth fixture_set_auth
#define usleep fixture_usleep
#define sigaction(...) fixture_sigaction (__VA_ARGS__)
#include "hev-socks5-proxy.c"
#undef hev_socks5_worker_start
#undef hev_socks5_worker_new
#undef hev_socks5_worker_signal_reload
#undef hev_socks5_worker_set_auth
#undef usleep
#undef sigaction

#define SYNC_SEND WORKER_SYNC_SEND
#define SYNC_WAIT WORKER_SYNC_WAIT
#define SYNC_STOP WORKER_SYNC_STOP
#define SYNC_LOAD WORKER_SYNC_LOAD
#define SYNC_SENT_S WORKER_SYNC_SENT_S
#define SYNC_SENT_R WORKER_SYNC_SENT_R
#define ioctl(...) fixture_ioctl (__VA_ARGS__)
#define write fixture_write
#define hev_task_io_read fixture_read
#include "hev-socks5-worker.c"
#undef write
#undef hev_task_io_read
#undef ioctl
#undef SYNC_SEND
#undef SYNC_WAIT
#undef SYNC_STOP
#undef SYNC_LOAD
#undef SYNC_SENT_S
#undef SYNC_SENT_R

static void
fixture_worker_start (HevSocks5Worker *worker)
{
    if (pthread_equal (pthread_self (), fixture_owner))
        assert (fcntl (worker->event_fds[1], F_GETFL) & O_NONBLOCK);
    hev_socks5_worker_start (worker);
    if (pthread_equal (pthread_self (), fixture_owner))
        atomic_store (&fixture_started, 1);
}

static HevSocks5Worker *
fixture_worker_new (int fd)
{
    HevSocks5Worker *worker = hev_socks5_worker_new (fd);
    assert (worker && fixture_created < 4);
    fixture_fds[fixture_created * 3] = fd;
    fixture_fds[fixture_created * 3 + 1] = worker->event_fds[0];
    fixture_fds[fixture_created * 3 + 2] = worker->event_fds[1];
    fixture_created++;
    return worker;
}

static void
fixture_signal_notify (HevSocks5Worker *worker)
{
    atomic_fetch_add (&fixture_notifications, 1);
    if (fixture_mode != FIX_LIVE) {
        atomic_fetch_add (&fixture_in_signal, 1);
        hev_socks5_worker_signal_reload (worker);
        atomic_fetch_sub (&fixture_in_signal, 1);
        return;
    }
    /* The real handler has already incremented users and borrowed worker. */
    assert (atomic_load (&signal_users) == 1);
    fixture_borrowed = worker;
    atomic_store (&fixture_captured, 1);
    while (!atomic_load (&fixture_release))
        ;
    hev_socks5_worker_signal_reload (worker);
}

static void
fixture_set_auth (HevSocks5Worker *worker, HevSocks5Authenticator *auth)
{
    sigset_t mask;
    /* Native reload work must run in the owner's ordinary event context;
     * SIGUSR1 is implicitly blocked inside the installed signal handler. */
    assert (pthread_equal (pthread_self (), fixture_owner));
    assert (!pthread_sigmask (SIG_SETMASK, NULL, &mask));
    assert (!sigismember (&mask, SIGUSR1));
    hev_socks5_worker_set_auth (worker, auth);
    atomic_fetch_add (&fixture_publications, 1);
}

static ssize_t
fixture_write (int fd, const void *buffer, size_t size)
{
    if (atomic_exchange (&fixture_gate_armed, 0)) {
        assert (!fixture_in_signal && fd == fixture_fds[2]);
        assert (atomic_load (&worker_list[0].worker->tsync) & WORKER_SYNC_WAIT);
        atomic_fetch_add (&fixture_gate_hits, 1);
        assert (!pthread_kill (pthread_self (), SIGUSR1));
    }
    if (fixture_in_signal && atomic_exchange (&fixture_eintr_armed, 0)) {
        atomic_fetch_add (&fixture_eintr_hits, 1);
        errno = EINTR;
        return -1;
    }
    if (fd == fixture_fds[2])
        assert (atomic_fetch_add (&fixture_queued, 1) < 2);
    ssize_t result = write (fd, buffer, size);
    if (fd == fixture_fds[2] && result < 0)
        atomic_fetch_sub (&fixture_queued, 1);
    return result;
}

static ssize_t
fixture_read (int fd, void *buffer, size_t size, HevTaskIOYielder yielder,
              void *data)
{
    ssize_t result = hev_task_io_read (fd, buffer, size, yielder, data);
    if (fd == fixture_fds[1] && result == 1)
        assert (atomic_fetch_sub (&fixture_queued, 1) > 0);
    return result;
}

static void
fixture_wait_reload (int target)
{
    while (atomic_load (&fixture_publications) < target ||
           atomic_load (&signal_reload) ||
           (atomic_load (&worker_list[0].worker->tsync) & WORKER_SYNC_SENT_R))
        usleep (100);
}

static void *
fixture_flood_thread (void *unused)
{
    (void)unused;
    /* Resolve this test-only TLS slot before any signal can use it. */
    atomic_store (&fixture_in_signal, 0);
    for (int i = 0; i < 512; i++) {
        errno = EDOM;
        assert (!pthread_kill (pthread_self (), SIGUSR1));
        assert (errno == EDOM);
    }
    return NULL;
}

static void *
fixture_reload_thread (void *unused)
{
    (void)unused;
    atomic_store (&fixture_in_signal, 0);
    while (!atomic_load (&fixture_started))
        usleep (100);
    fixture_wait_reload (fixture_workers);
    for (int i = 0; i < 4; i++) {
        int target = atomic_load (&fixture_publications) + fixture_workers;
        if (fixture_mode == FIX_MIXED) {
            atomic_store (&fixture_gate_armed, 1);
            hev_socks5_worker_reload (worker_list[0].worker);
            assert (atomic_load (&fixture_gate_hits) == i + 1);
        } else {
            if (fixture_mode == FIX_EINTR)
                atomic_store (&fixture_eintr_armed, 1);
            errno = EDOM;
            assert (!pthread_kill (pthread_self (), SIGUSR1));
            assert (errno == EDOM);
            if (fixture_mode == FIX_EINTR)
                assert (atomic_load (&fixture_eintr_hits) == i + 1);
        }
        fixture_wait_reload (target);
    }
    if (fixture_mode == FIX_FLOOD) {
        pthread_t senders[2];
        for (int i = 0; i < 2; i++)
            assert (!pthread_create (&senders[i], NULL, fixture_flood_thread,
                                     NULL));
        for (int i = 0; i < 2; i++)
            assert (!pthread_join (senders[i], NULL));
        int target = atomic_load (&fixture_publications) + fixture_workers;
        assert (!pthread_kill (pthread_self (), SIGUSR1));
        fixture_wait_reload (target);
        assert (atomic_load (&fixture_notifications) == 1029);
    }
    assert (atomic_load (&fixture_publications) >= 5 * fixture_workers);
    hev_socks5_server_quit ();
    return NULL;
}

static int
fixture_usleep (useconds_t duration)
{
    if (pthread_equal (pthread_self (), fixture_owner) &&
        !atomic_load (&signal_worker) && atomic_load (&signal_users))
        atomic_store (&fixture_drain, 1);
    return usleep (duration);
}

static int
fixture_sigaction (int number, const struct sigaction *action,
                   struct sigaction *previous)
{
    if (action && ((fixture_mode == FIX_PIPE_FAIL && number == SIGPIPE &&
                    action->sa_handler == SIG_IGN) ||
                   (fixture_mode == FIX_RELOAD_FAIL && number == SIGUSR1 &&
                    action->sa_handler == reload_signal_handler))) {
        fixture_faults++;
        errno = EINVAL;
        return -1;
    }
    return sigaction (number, action, previous);
}

static int
fixture_ioctl (int fd, unsigned long request, void *argument)
{
    if (fixture_mode == FIX_NOTIFY_FAIL && worker_list &&
        worker_list[0].worker && fd == worker_list[0].worker->event_fds[1]) {
        fixture_faults++;
        errno = EIO;
        return -1;
    }
    return ioctl (fd, request, argument);
}

static void
fixture_host_handler (int number, siginfo_t *info, void *context)
{
    (void)info;
    (void)context;
    if (number == SIGUSR1)
        fixture_host_reload++;
    else if (number == SIGPIPE)
        fixture_host_pipe++;
}

static void
fixture_check_action (int number, const struct sigaction *expected)
{
    struct sigaction actual;
    assert (!sigaction (number, NULL, &actual));
    assert (actual.sa_sigaction == expected->sa_sigaction);
    assert (actual.sa_flags == expected->sa_flags);
    for (int signal = 1; signal < NSIG; signal++)
        assert (sigismember (&actual.sa_mask, signal) ==
                sigismember (&expected->sa_mask, signal));
}

static void *
fixture_signal_thread (void *data)
{
    (void)data;
    atomic_store (&fixture_in_signal, 0);
    while (!atomic_load (&fixture_started))
        usleep (100);
    errno = EDOM;
    assert (!pthread_kill (pthread_self (), SIGUSR1));
    assert (errno == EDOM);
    return NULL;
}

static void *
fixture_stop_thread (void *data)
{
    (void)data;
    while (!atomic_load (&fixture_captured))
        usleep (100);
    hev_socks5_server_quit ();
    while (!atomic_load (&fixture_drain) && !atomic_load (&fixture_finished))
        usleep (100);
    if (atomic_load (&fixture_drain)) {
        assert (worker_list && fixture_borrowed == worker_list[0].worker);
        assert (atomic_load (&signal_users) == 1);
        for (int i = 0; i < fixture_created * 3; i++)
            assert (fcntl (fixture_fds[i], F_GETFD) >= 0);
    }
    atomic_store (&fixture_release, 1);
    return NULL;
}

static void
fixture_deadline (int number)
{
    const char message[] = "signal lifetime: DEADLINE\n";
    (void)number;
    if (write (STDERR_FILENO, message, sizeof (message) - 1) < 0)
        _exit (91);
    _exit (90);
}

static void
fixture_case (int mode, int workers)
{
    unsigned char config[512];
    pthread_t controller;
    struct sigaction action = { 0 }, previous_reload, previous_pipe;
    fixture_mode = mode;
    fixture_workers = workers;
    atomic_store (&fixture_publications, 0);
    atomic_store (&fixture_notifications, 0);
    atomic_store (&fixture_gate_armed, 0);
    atomic_store (&fixture_gate_hits, 0);
    atomic_store (&fixture_eintr_armed, 0);
    atomic_store (&fixture_eintr_hits, 0);
    atomic_store (&fixture_queued, 0);
    fixture_created = fixture_faults = 0;
    fixture_borrowed = NULL;
    fixture_host_reload = fixture_host_pipe = 0;
    atomic_store (&fixture_started, 0);
    atomic_store (&fixture_captured, 0);
    atomic_store (&fixture_release, 0);
    atomic_store (&fixture_drain, 0);
    atomic_store (&fixture_finished, 0);
    action.sa_sigaction = fixture_host_handler;
    action.sa_flags = SA_RESTART | SA_SIGINFO;
    assert (!sigemptyset (&action.sa_mask));
    assert (!sigaddset (&action.sa_mask, SIGUSR2));
    if (mode == FIX_IGNORED) {
        action.sa_handler = SIG_IGN;
        action.sa_flags = SA_RESTART;
    }
    assert (!sigaction (SIGUSR1, &action, NULL));
    assert (!sigaction (SIGUSR1, NULL, &previous_reload));
    action.sa_sigaction = fixture_host_handler;
    action.sa_flags = SA_RESTART | SA_SIGINFO;
    assert (!sigaddset (&action.sa_mask, SIGTERM));
    assert (!sigaction (SIGPIPE, &action, NULL));
    assert (!sigaction (SIGPIPE, NULL, &previous_pipe));
    int length = snprintf ((char *)config, sizeof (config),
                           "main:\n  workers: %d\n  port: 0\n"
                           "  listen-address: '127.0.0.1'\n  udp-port: 0\n"
                           "misc:\n  log-level: error\n"
                           "auth:\n  username: u\n  password: p\n",
                           workers);
    assert (length > 0 && (size_t)length < sizeof (config));
    alarm (8);
    if (mode == FIX_LIVE) {
        assert (!pthread_create (&fixture_carrier, NULL, fixture_signal_thread,
                                 NULL));
        assert (!pthread_create (&controller, NULL, fixture_stop_thread, NULL));
    } else if (mode >= FIX_IGNORED) {
        assert (!pthread_create (&fixture_carrier, NULL, fixture_reload_thread,
                                 NULL));
    }
    int result = hev_socks5_server_main_from_str (config, length);
    assert (worker_list == NULL);
    atomic_store (&fixture_finished, 1);
    if (mode == FIX_LIVE) {
        assert (!pthread_join (controller, NULL));
        assert (!pthread_join (fixture_carrier, NULL));
        assert (result == 0 && atomic_load (&fixture_drain));
        assert (atomic_load (&fixture_captured));
    } else if (mode >= FIX_IGNORED) {
        assert (!pthread_join (fixture_carrier, NULL));
        assert (!result && atomic_load (&fixture_notifications) >= 4);
    } else {
        assert (result == -1 && fixture_faults == 1);
    }
    assert (fixture_created == workers);
    assert (!signal_installed && !atomic_load (&signal_worker));
    assert (!atomic_load (&signal_users) && !atomic_load (&signal_reload));
    assert (!(atomic_load (&tsync) & (SYNC_SEND | SYNC_WAIT | SYNC_STOP)));
    for (int i = 0; i < fixture_created * 3; i++) {
        errno = 0;
        assert (fcntl (fixture_fds[i], F_GETFD) == -1 && errno == EBADF);
    }
    fixture_check_action (SIGUSR1, &previous_reload);
    fixture_check_action (SIGPIPE, &previous_pipe);
    assert (!fixture_host_reload && !fixture_host_pipe);
    assert (!raise (SIGUSR1) && !raise (SIGPIPE));
    assert (fixture_host_reload == (mode != FIX_IGNORED) &&
            fixture_host_pipe == 1);
    alarm (0);
    printf ("signal lifetime: PASS mode=%d workers=%d faults=%d closed=%d\n",
            mode, workers, fixture_faults, fixture_created * 3);
}

int
main (void)
{
    struct sigaction action = { 0 };
    action.sa_handler = fixture_deadline;
    assert (!sigemptyset (&action.sa_mask));
    assert (!sigaction (SIGALRM, &action, NULL));
    fixture_owner = pthread_self ();
#ifdef SIGNAL_LIFECYCLE_CASE
    _Static_assert (SIGNAL_LIFECYCLE_CASE >= FIX_LIVE &&
                        SIGNAL_LIFECYCLE_CASE <= FIX_FLOOD,
                    "Invalid signal lifecycle case");
    fixture_case (SIGNAL_LIFECYCLE_CASE, 4);
#else
    for (int workers = 1; workers <= 4; workers *= 2) {
        fixture_case (FIX_LIVE, workers);
        for (int mode = FIX_NOTIFY_FAIL; mode <= FIX_RELOAD_FAIL; mode++) {
            fixture_case (mode, workers);
            fixture_case (FIX_LIVE, workers);
        }
        for (int mode = FIX_IGNORED; mode <= FIX_FLOOD; mode++)
            fixture_case (mode, workers);
    }
    puts ("signal lifetime: PASS 33/33 actual main invocations");
#endif
    return 0;
}
