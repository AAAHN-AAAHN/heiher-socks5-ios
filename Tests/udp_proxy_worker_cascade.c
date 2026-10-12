/* Exercise the actual native proxy/main lifecycle with an early worker-0 stop.
 * The start boundary controls only that one stop. Sibling pthreads, Hev tasks,
 * sockets, the proxy's stop cascade and fini/join all execute normally.
 * Port zero lets the OS allocate real listeners without a reserve/rebind race.
 */
#include <assert.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#include "hev-main.h"
#include "hev-socks5-worker.h"

static pthread_t fixture_main_thread;
static atomic_int fixture_starts;
static atomic_int fixture_early_stops;
static int fixture_joins;

static void fixture_worker_start (HevSocks5Worker *worker);
static int fixture_thread_join (pthread_t thread, void **result);

#define hev_socks5_worker_start fixture_worker_start
#define pthread_join fixture_thread_join
#include "hev-socks5-proxy.c"
#undef pthread_join
#undef hev_socks5_worker_start

static void
fixture_worker_start (HevSocks5Worker *worker)
{
    atomic_fetch_add (&fixture_starts, 1);
    hev_socks5_worker_start (worker);
    if (pthread_equal (pthread_self (), fixture_main_thread)) {
        atomic_fetch_add (&fixture_early_stops, 1);
        hev_socks5_worker_stop (worker);
    }
}

static int
fixture_thread_join (pthread_t thread, void **result)
{
    int status = pthread_join (thread, result);
    assert (status == 0);
    fixture_joins++;
    return status;
}

static void
fixture_deadline (int signum)
{
    static const char message[] =
        "proxy worker cascade: FAIL native main/fini deadline (3 seconds)\n";
    (void)signum;
    (void)write (STDERR_FILENO, message, sizeof (message) - 1);
    _exit (1);
}

static void
fixture_case (int workers)
{
    unsigned char config[256];
    int length, result;

    atomic_store (&fixture_starts, 0);
    atomic_store (&fixture_early_stops, 0);
    fixture_joins = 0;
    length = snprintf ((char *)config, sizeof (config),
                       "main:\n  workers: %d\n  port: 0\n"
                       "  listen-address: '127.0.0.1'\n  udp-port: 0\n"
                       "misc:\n  log-level: error\n",
                       workers);
    assert (length > 0 && (size_t)length < sizeof (config));
    fprintf (stderr, "proxy worker cascade: START workers=%d\n", workers);
    alarm (3);
    result = hev_socks5_server_main_from_str (config, length);
    alarm (0);
    assert (result == 0);
    assert (atomic_load (&fixture_starts) == workers);
    assert (atomic_load (&fixture_early_stops) == 1);
    assert (fixture_joins == workers - 1);
    assert (worker_list == NULL);
    printf ("proxy worker cascade: PASS workers=%d starts=%d joins=%d\n",
            workers, atomic_load (&fixture_starts), fixture_joins);
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
    fixture_case (2);
    fixture_case (4);
    puts ("proxy worker cascade: PASS 2/2 cases");
    return 0;
}
