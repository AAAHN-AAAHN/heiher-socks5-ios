/* Statistics-owned meter entry failure must stop the current worker pool
 * without leaving a pending public Stop for the following server call. */
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "hev-main.h"
#include "hev-socks5-worker.h"
#include "core/src/hev-socks5-meter.h"

static pthread_t fixture_main_thread;
static atomic_int fixture_release, fixture_failures;
static int fixture_mode, fixture_workers, fixture_joins;
static int fixture_meter_enter (void);
static void fixture_worker_start (HevSocks5Worker *);
static int fixture_thread_join (pthread_t, void **);

#define hev_meter_worker_enter fixture_meter_enter
#define hev_socks5_worker_start fixture_worker_start
#define pthread_join fixture_thread_join
#include "hev-socks5-proxy.c"
#undef hev_meter_worker_enter
#undef hev_socks5_worker_start
#undef pthread_join

static int
fixture_meter_enter (void)
{
    if (fixture_mode && !pthread_equal (pthread_self (), fixture_main_thread) &&
        pthread_equal (pthread_self (),
                       worker_list[fixture_workers - 1].thread)) {
        if (fixture_mode == 2)
            while (!atomic_load (&fixture_release))
                usleep (100);
        atomic_fetch_add (&fixture_failures, 1);
        errno = ENOMEM;
        return -1;
    }
    return hev_meter_worker_enter ();
}

static void
fixture_worker_start (HevSocks5Worker *worker)
{
    hev_socks5_worker_start (worker);
    if (fixture_mode != 1 &&
        pthread_equal (pthread_self (), fixture_main_thread))
        hev_socks5_server_quit ();
}

static int
fixture_thread_join (pthread_t thread, void **result)
{
    if (fixture_mode == 2) {
        assert (!(atomic_load (&tsync) & SYNC_SEND));
        atomic_store (&fixture_release, 1);
    }
    int status = pthread_join (thread, result);
    assert (status == 0);
    fixture_joins++;
    return status;
}

static void
fixture_deadline (int signum)
{
    static const char message[] =
        "meter pool failure: FAIL 3-second deadline\n";
    (void)signum;
    if (write (STDERR_FILENO, message, sizeof (message) - 1) < 0)
        _exit (2);
    _exit (1);
}

static void
fixture_case (int mode, int workers)
{
    unsigned char config[256];
    fixture_mode = mode;
    fixture_workers = workers;
    fixture_joins = 0;
    atomic_store (&fixture_release, 0);
    atomic_store (&fixture_failures, 0);
    int length = snprintf ((char *)config, sizeof (config),
                           "main:\n  workers: %d\n  port: 0\n"
                           "  listen-address: '127.0.0.1'\n  udp-port: 0\n"
                           "misc:\n  log-level: error\n",
                           workers);
    assert (length > 0 && (size_t)length < sizeof (config));
    fprintf (stderr, "meter pool failure: START mode=%d workers=%d\n", mode,
             workers);
    alarm (3);
    int result = hev_socks5_server_main_from_str (config, length);
    alarm (0);
    assert (result == 0 && worker_list == NULL && fixture_joins == workers - 1);
    assert (atomic_load (&fixture_failures) == (mode != 0));
    assert (!(atomic_load (&tsync) & (SYNC_SEND | SYNC_WAIT | SYNC_STOP)));
    printf (
        "meter pool failure: PASS mode=%d workers=%d failures=%d joins=%d pending=0\n",
        mode, workers, atomic_load (&fixture_failures), fixture_joins);
}

int
main (void)
{
    struct sigaction action;
    memset (&action, 0, sizeof (action));
    action.sa_handler = fixture_deadline;
    assert (sigemptyset (&action.sa_mask) == 0);
    assert (sigaction (SIGALRM, &action, NULL) == 0);
    fixture_main_thread = pthread_self ();
    for (int workers = 2; workers <= 4; workers *= 2) {
        fixture_case (1, workers);
        fixture_case (0, workers);
        fixture_case (2, workers);
        fixture_case (0, workers);
    }
    puts (
        "meter pool failure: PASS 8/8 consecutive calls; each failure followed by a fresh normal invocation");
    return 0;
}
