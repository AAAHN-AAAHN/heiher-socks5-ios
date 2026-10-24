/* Exercise the full proxy/main lifecycle with real sockets, worker tasks and
 * pthreads. Only the stated startup failure and completion-order boundaries
 * are controlled. Port zero allocates real independent test listeners. */
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <hev-task.h>
#include <hev-task-system.h>
#include "hev-main.h"
#include "hev-socks5-worker.h"
#include "hev-socks5-user-mark.h"

#include <sys/time.h>

static atomic_int fixture_auth_allocated, fixture_auth_freed;
enum
{
    FIX_AUTH_OFF,
    FIX_AUTH_RELOAD,
    FIX_AUTH_STARTUP_FAILURE
};
static int fixture_auth_mode;
enum
{
    AUTH_OK,
    AUTH_MISSING,
    AUTH_READ,
    AUTH_ALLOC,
    AUTH_USER,
    AUTH_CLOSE,
    AUTH_EMPTY_NAME,
    AUTH_EMPTY_PASS,
};
static int fixture_auth_fault, fixture_auth_lines, fixture_auth_discarded;
static HevSocks5UserMark *fixture_user_new (const char *, unsigned int,
                                            const char *, unsigned int,
                                            unsigned int);
static ssize_t fixture_getline (char **, size_t *, FILE *);
static int fixture_fclose (FILE *);
static char fixture_auth_file[] = "/tmp/hev-auth-lifecycle-XXXXXX";
static pthread_t fixture_controller_thread;
static void *fixture_auth_alloc (size_t, size_t);
static void fixture_auth_free (void *);
static void *fixture_auth_controller (void *);

/* Count actual authenticator ownership without replacing construction,
 * reference operations, lookup, or destruction. */
#define calloc fixture_auth_alloc
#define free fixture_auth_free
#include "hev-socks5-authenticator.c"
#undef calloc
#undef free
#undef LOG_D
#undef LOG_I
#undef LOG_W
#undef LOG_E
#undef LOG_ON
#undef LOG_ON_D
#undef LOG_ON_I
#undef LOG_ON_W
#undef LOG_ON_E

static void *
fixture_auth_alloc (size_t count, size_t size)
{
    void *result;
    if (fixture_auth_fault == AUTH_ALLOC) {
        errno = ENOMEM;
        return NULL;
    }
    result = calloc (count, size);
    if (result)
        atomic_fetch_add (&fixture_auth_allocated, 1);
    return result;
}

static void
fixture_auth_free (void *pointer)
{
    assert (pointer);
    atomic_fetch_add (&fixture_auth_freed, 1);
    free (pointer);
}

enum
{
    FIX_STOP_ALL,
    FIX_STOP_ZERO,
    FIX_STOP_SIBLING,
    FIX_TASK_INIT,
    FIX_EVENT_ADD,
    FIX_LISTENER_ADD,
    FIX_EVENT_EOF,
    FIX_LATE_EXIT,
};
static const char *names[] = { "stop-all",  "stop-zero", "stop-sibling",
                               "task-init", "event-add", "listener-add",
                               "event-eof", "late-exit" };
static pthread_t fixture_main_thread;
static int fixture_mode, fixture_workers, fixture_created, fixture_joins;
static int fixture_descriptors[12];
static atomic_int fixture_starts, fixture_faults, fixture_late, fixture_release;
static HevSocks5Worker *fixture_target;

static HevSocks5Worker *fixture_worker_new (int);
static void fixture_worker_start (HevSocks5Worker *);
static int fixture_task_system_init (void);
static void fixture_task_system_run (void);
static int fixture_thread_join (pthread_t, void **);
static int fixture_add (HevTask *, int, unsigned int);

#define hev_socks5_worker_new fixture_worker_new
#define hev_socks5_worker_start fixture_worker_start
#define hev_task_system_init fixture_task_system_init
#define hev_task_system_run fixture_task_system_run
#define pthread_join fixture_thread_join
#define hev_socks5_user_mark_new fixture_user_new
#define getline fixture_getline
#define fclose fixture_fclose
#include "hev-socks5-proxy.c"
#undef fclose
#undef hev_socks5_user_mark_new
#undef getline
#undef hev_socks5_worker_new
#undef hev_socks5_worker_start
#undef hev_task_system_init
#undef hev_task_system_run
#undef pthread_join

/* Proxy and worker intentionally have independent private synchronization
 * enums. Prefix the latter only while including both real implementations. */
#define SYNC_SEND WORKER_SYNC_SEND
#define SYNC_WAIT WORKER_SYNC_WAIT
#define SYNC_STOP WORKER_SYNC_STOP
#define SYNC_LOAD WORKER_SYNC_LOAD
#define SYNC_SENT_S WORKER_SYNC_SENT_S
#define SYNC_SENT_R WORKER_SYNC_SENT_R
#define hev_task_add_fd fixture_add
#include "hev-socks5-worker.c"
#undef hev_task_add_fd
#undef SYNC_SEND
#undef SYNC_WAIT
#undef SYNC_STOP
#undef SYNC_LOAD
#undef SYNC_SENT_S
#undef SYNC_SENT_R

static HevSocks5UserMark *
fixture_user_new (const char *name, unsigned int nlen, const char *pass,
                  unsigned int plen, unsigned int mark)
{
    if (fixture_auth_fault == AUTH_USER) {
        errno = ENOMEM;
        return NULL;
    }
    return hev_socks5_user_mark_new (name, nlen, pass, plen, mark);
}

static int
fixture_fclose (FILE *file)
{
    int result = fclose (file);
    if (fixture_auth_fault == AUTH_CLOSE) {
        errno = EIO;
        return EOF;
    }
    return result;
}

static ssize_t
fixture_getline (char **line, size_t *length, FILE *file)
{
    if (fixture_auth_fault == AUTH_READ && fixture_auth_lines++) {
        /* A complete first user is followed by a read/allocation failure,
         * not EOF. No partially built snapshot may become current. */
        errno = EIO;
        return -1;
    }
    return getline (line, length, file);
}

static int
fixture_is_main (void)
{
    return pthread_equal (pthread_self (), fixture_main_thread);
}

static HevSocks5Worker *
fixture_worker_new (int fd)
{
    HevSocks5Worker *worker = hev_socks5_worker_new (fd);
    assert (worker && fixture_created < 4);
    fixture_descriptors[fixture_created * 3] = fd;
    fixture_descriptors[fixture_created * 3 + 1] = worker->event_fds[0];
    fixture_descriptors[fixture_created * 3 + 2] = worker->event_fds[1];
    if (++fixture_created == fixture_workers)
        fixture_target = worker;
    if (worker == fixture_target && fixture_mode == FIX_EVENT_EOF) {
        assert (shutdown (worker->event_fds[1], SHUT_WR) == 0);
        atomic_fetch_add (&fixture_faults, 1);
    }
    return worker;
}

static int
fixture_task_system_init (void)
{
    if (fixture_mode == FIX_TASK_INIT && !fixture_is_main () &&
        pthread_equal (pthread_self (),
                       worker_list[fixture_workers - 1].thread)) {
        atomic_fetch_add (&fixture_faults, 1);
        errno = ENOMEM;
        return -1;
    }
    return hev_task_system_init ();
}

static void
fixture_worker_start (HevSocks5Worker *worker)
{
    atomic_fetch_add (&fixture_starts, 1);
    hev_socks5_worker_start (worker);
    if (fixture_auth_mode == FIX_AUTH_RELOAD && fixture_is_main ()) {
        assert (!pthread_create (&fixture_controller_thread, NULL,
                                 fixture_auth_controller, NULL));
    } else if (fixture_mode == FIX_STOP_ZERO && fixture_is_main ()) {
        atomic_fetch_add (&fixture_faults, 1);
        hev_socks5_worker_stop (worker);
    } else if (fixture_mode == FIX_STOP_SIBLING && worker == fixture_target) {
        atomic_fetch_add (&fixture_faults, 1);
        hev_socks5_worker_stop (worker);
    } else if ((fixture_mode == FIX_STOP_ALL ||
                fixture_mode == FIX_LATE_EXIT) &&
               fixture_is_main ()) {
        hev_socks5_server_quit ();
    }
}

static int
fixture_add (HevTask *task, int fd, unsigned int events)
{
    if ((fixture_mode == FIX_EVENT_ADD && fd == fixture_target->event_fds[0]) ||
        (fixture_mode == FIX_LISTENER_ADD && fd == fixture_target->fd)) {
        atomic_fetch_add (&fixture_faults, 1);
        errno = ENOMEM;
        return -1;
    }
    return hev_task_add_fd (task, fd, events);
}

static void
fixture_task_system_run (void)
{
    hev_task_system_run ();
    if (fixture_mode == FIX_LATE_EXIT && !fixture_is_main ()) {
        atomic_fetch_add (&fixture_late, 1);
        /* Keep this sibling alive after its actual task loop exits until
         * proxy_fini has closed the global send gate and reaches join. */
        while (!atomic_load (&fixture_release))
            usleep (100);
    }
}

static int
fixture_thread_join (pthread_t thread, void **result)
{
    if (fixture_mode == FIX_LATE_EXIT) {
        assert (!(atomic_load (&tsync) & SYNC_SEND));
        atomic_store (&fixture_release, 1);
    }
    int status = pthread_join (thread, result);
    assert (status == 0);
    fixture_joins++;
    return status;
}

static int
fixture_auth_client (int worker)
{
    struct sockaddr_in6 address;
    struct timeval timeout = { 2, 0 };
    socklen_t length = sizeof (address);
    unsigned char reply[2];
    const unsigned char method[] = { 5, 1, 2 };
    int client = socket (AF_INET6, SOCK_STREAM, 0);

    assert (client >= 0);
    assert (!setsockopt (client, SOL_SOCKET, SO_RCVTIMEO, &timeout,
                         sizeof (timeout)));
    assert (!getsockname (fixture_descriptors[worker * 3],
                          (struct sockaddr *)&address, &length));
    assert (!connect (client, (struct sockaddr *)&address, length));
    assert (send (client, method, sizeof (method), 0) == sizeof (method));
    assert (recv (client, reply, sizeof (reply), MSG_WAITALL) ==
            sizeof (reply));
    assert (reply[0] == 5 && reply[1] == 2);
    return client;
}

static int
fixture_authenticate (int client, int generation)
{
    unsigned char request[32] = { 1, 1, 'u', 0 }, reply[2];
    int length =
        snprintf ((char *)request + 4, sizeof (request) - 4, "p%d", generation);
    assert (length > 0 && length < (int)sizeof (request) - 4);
    request[3] = length;
    assert (send (client, request, length + 4, 0) == length + 4);
    assert (recv (client, reply, sizeof (reply), MSG_WAITALL) ==
            sizeof (reply));
    assert (reply[0] == 1);
    return reply[1] == 0;
}

static void
fixture_auth_write (int generation)
{
    FILE *file = fopen (fixture_auth_file, "w");
    assert (file);
    assert (fprintf (file, "u p%d\n", generation) > 0);
    assert (!fclose (file));
}

static void *
fixture_auth_controller (void *unused)
{
    const unsigned char associate[] = { 5, 3, 0, 1, 0, 0, 0, 0, 0, 0 };
    unsigned char reply[22];
    int retained[4];
    (void)unused;

    for (int i = 0; i < fixture_workers; i++)
        retained[i] = fixture_auth_client (i);
    assert (atomic_load (&fixture_auth_allocated) == 1);
    assert (!atomic_load (&fixture_auth_freed));
    fixture_auth_write (1);
    /* Dispatch the actual native reload body from this ordinary thread.
     * The separate SIGUSR1/event-path probe covers signal dispatch; this
     * ownership oracle does not add signal frames to small task stacks. */
    hev_socks5_proxy_load ();
    while (atomic_load (&fixture_auth_allocated) != 2)
        usleep (100);
    /* A newly accepted connection may legitimately precede the reload event.
     * Await successful new credentials on each actual worker listener. */
    for (int i = 0; i < fixture_workers; i++) {
        int accepted;
        do {
            int client = fixture_auth_client (i);
            accepted = fixture_authenticate (client, 1);
            assert (!close (client));
            if (!accepted)
                usleep (100);
        } while (!accepted);
    }
    assert (!atomic_load (&fixture_auth_freed));
    for (int i = 0; i < fixture_workers; i++) {
        assert (fixture_authenticate (retained[i], 0));
        assert (send (retained[i], associate, sizeof (associate), 0) ==
                sizeof (associate));
        assert (recv (retained[i], reply, 4, MSG_WAITALL) == 4);
        assert (reply[0] == 5 && !reply[1] && !reply[2]);
        assert (reply[3] == 1 || reply[3] == 4);
        int bytes = reply[3] == 1 ? 6 : 18;
        assert (recv (retained[i], reply + 4, bytes, MSG_WAITALL) == bytes);
    }
    assert (atomic_load (&fixture_auth_freed) == 1);
    for (int generation = 2; generation <= 8; generation++) {
        fixture_auth_write (generation);
        hev_socks5_proxy_load ();
        while (atomic_load (&fixture_auth_freed) != generation)
            usleep (100);
        assert (atomic_load (&fixture_auth_allocated) == generation + 1);
        for (int i = 0; i < fixture_workers; i++) {
            int client = fixture_auth_client (i);
            assert (fixture_authenticate (client, generation));
            assert (!close (client));
        }
    }
    for (int fault = AUTH_MISSING; fault <= AUTH_CLOSE; fault++) {
        int allocated = atomic_load (&fixture_auth_allocated);
        int freed = atomic_load (&fixture_auth_freed);
        fixture_auth_fault = fault;
        fixture_auth_lines = 0;
        if (fault == AUTH_MISSING)
            assert (!unlink (fixture_auth_file));
        assert (hev_socks5_proxy_load () < 0);
        fixture_auth_fault = AUTH_OK;
        fixture_auth_write (8);
        int discarded = atomic_load (&fixture_auth_allocated) - allocated;
        assert (discarded == (fault != AUTH_ALLOC));
        assert (atomic_load (&fixture_auth_freed) - freed == discarded);
        fixture_auth_discarded += discarded;
        for (int i = 0; i < fixture_workers; i++) {
            int client = fixture_auth_client (i);
            assert (fixture_authenticate (client, 8));
            assert (!close (client));
        }
        printf ("proxy auth failure: PASS reload fault=%d workers=%d "
                "discarded=%d prior-credentials=retained\n",
                fault, fixture_workers, discarded);
    }
    fixture_auth_write (9);
    assert (!hev_socks5_proxy_load ());
    for (int i = 0; i < fixture_workers; i++) {
        int accepted;
        do {
            int client = fixture_auth_client (i);
            accepted = fixture_authenticate (client, 9);
            assert (!close (client));
            if (!accepted)
                usleep (100);
        } while (!accepted);
    }
    hev_socks5_server_quit ();
    for (int i = 0; i < fixture_workers; i++) {
        assert (recv (retained[i], reply, 1, 0) == 0);
        assert (!close (retained[i]));
    }
    return NULL;
}

/* TSan mode uses ordinary pthread stacks and the actual publication/load
 * bodies. The default matrix separately exercises real coroutine events. */
static atomic_int fixture_auth_ready, fixture_auth_done;

static void *
fixture_auth_consumer (void *data)
{
    HevSocks5Worker *worker = data;
    hev_socks5_worker_load (worker);
    assert (worker->auth_curr);
    atomic_fetch_add (&fixture_auth_ready, 1);
    while (!atomic_load (&fixture_auth_done))
        hev_socks5_worker_load (worker);
    return NULL;
}

static void
fixture_auth_publication (void)
{
    HevSocks5Worker *workers[4];
    pthread_t consumers[4];
    assert (!hev_task_system_init ());
    for (int i = 0; i < 4; i++) {
        workers[i] = hev_socks5_worker_new (-1);
        assert (workers[i]);
    }
    for (int generation = 0; generation <= 10000; generation++) {
        HevSocks5Authenticator *auth = hev_socks5_authenticator_new ();
        assert (auth);
        for (int i = 0; i < 4; i++)
            hev_socks5_worker_set_auth (workers[i], auth);
        hev_object_unref (HEV_OBJECT (auth));
        if (!generation) {
            for (int i = 0; i < 4; i++)
                assert (!pthread_create (&consumers[i], NULL,
                                         fixture_auth_consumer, workers[i]));
            while (atomic_load (&fixture_auth_ready) != 4)
                usleep (100);
        }
    }
    atomic_store (&fixture_auth_done, 1);
    for (int i = 0; i < 4; i++) {
        assert (!pthread_join (consumers[i], NULL));
        hev_socks5_worker_destroy (workers[i]);
    }
    hev_task_system_fini ();
    assert (atomic_load (&fixture_auth_allocated) == 10001);
    assert (atomic_load (&fixture_auth_freed) == 10001);
    puts ("proxy auth publication: PASS workers=4 publications=40004 "
          "allocated=10001 freed=10001");
}

static void
fixture_deadline (int signum)
{
    static const char message[] =
        "proxy lifecycle: FAIL native main/fini deadline\n";
    (void)signum;
    if (write (STDERR_FILENO, message, sizeof (message) - 1) < 0)
        _exit (2);
    _exit (1);
}

static void
fixture_case (int mode, int workers)
{
    unsigned char config[384];
    int pending_auth = fixture_auth_mode == FIX_AUTH_STARTUP_FAILURE &&
                       workers == 1;
    fixture_auth_discarded = 0;
    fixture_mode = mode;
    fixture_workers = workers;
    fixture_created = fixture_joins = 0;
    fixture_target = NULL;
    atomic_store (&fixture_starts, 0);
    atomic_store (&fixture_faults, 0);
    atomic_store (&fixture_late, 0);
    atomic_store (&fixture_release, 0);
    int length = snprintf ((char *)config, sizeof (config),
                           "main:\n  workers: %d\n  port: 0\n"
                           "  listen-address: '127.0.0.1'\n  udp-port: 0\n"
                           "misc:\n  log-level: error\n",
                           workers);
    assert (length > 0 && (size_t)length < sizeof (config));
    if (fixture_auth_mode) {
        int extra = snprintf ((char *)config + length, sizeof (config) - length,
                              "auth:\n  file: '%s'\n", fixture_auth_file);
        assert (extra > 0 && (size_t)extra < sizeof (config) - length);
        length += extra;
    }
    fprintf (stderr, "proxy lifecycle: START %s workers=%d\n", names[mode],
             workers);
    alarm (fixture_auth_mode ? 15 : 3);
    /* Single-worker legacy prestart Stop bypasses every worker_start, so
     * initial authentication must be destroyed from the pending slot. */
    if (pending_auth)
        hev_socks5_server_quit ();
    int result = hev_socks5_server_main_from_str (config, length);
    if (fixture_auth_mode) {
        if (fixture_auth_mode == FIX_AUTH_RELOAD)
            assert (!pthread_join (fixture_controller_thread, NULL));
        int expected = fixture_auth_mode == FIX_AUTH_RELOAD ?
                           10 + fixture_auth_discarded :
                           1;
        assert (atomic_load (&fixture_auth_allocated) == expected);
        assert (atomic_load (&fixture_auth_freed) == expected);
        printf ("proxy auth: PASS workers=%d mode=%s allocated=%d freed=%d\n",
                workers,
                fixture_auth_mode == FIX_AUTH_RELOAD ?
                    "9-reloads-and-5-failures" :
                    "startup-failure",
                expected, expected);
    }
    alarm (0);
    assert (result == 0 && worker_list == NULL);
    assert (fixture_created == workers && fixture_joins == workers - 1);
    assert (!(atomic_load (&tsync) & (SYNC_SEND | SYNC_WAIT | SYNC_STOP)));
    assert (atomic_load (&fixture_starts) ==
            workers - (mode == FIX_TASK_INIT) - pending_auth);
    assert (atomic_load (&fixture_faults) ==
            (mode != FIX_STOP_ALL && mode != FIX_LATE_EXIT));
    if (mode == FIX_LATE_EXIT)
        assert (atomic_load (&fixture_late) == workers - 1);
    for (int i = 0; i < fixture_created * 3; i++) {
        errno = 0;
        assert (fcntl (fixture_descriptors[i], F_GETFD) == -1 &&
                errno == EBADF);
    }
    printf ("proxy lifecycle: PASS %s workers=%d starts=%d faults=%d joins=%d "
            "closed=%d late=%d pending=0\n",
            names[mode], workers, atomic_load (&fixture_starts),
            atomic_load (&fixture_faults), fixture_joins, fixture_created * 3,
            atomic_load (&fixture_late));
}

static void
fixture_auth_startup_failure (int fault, int workers, int inline_user)
{
    unsigned char config[384];
    fixture_mode = FIX_STOP_ALL;
    fixture_workers = workers;
    fixture_created = fixture_joins = 0;
    fixture_target = NULL;
    fixture_auth_fault = fault;
    fixture_auth_lines = 0;
    atomic_store (&fixture_starts, 0);
    atomic_store (&fixture_auth_allocated, 0);
    atomic_store (&fixture_auth_freed, 0);
    int length = snprintf ((char *)config, sizeof (config),
                           "main:\n  workers: %d\n  port: 0\n"
                           "  listen-address: '127.0.0.1'\n  udp-port: 0\n"
                           "misc:\n  log-level: error\nauth:\n",
                           workers);
    assert (length > 0 && (size_t)length < sizeof (config));
    int extra;
    if (inline_user || fault >= AUTH_EMPTY_NAME) {
        extra = snprintf ((char *)config + length, sizeof (config) - length,
                          "  username: '%s'\n  password: '%s'\n",
                          fault == AUTH_EMPTY_NAME ? "" : "u",
                          fault == AUTH_EMPTY_PASS ? "" : "p");
    } else {
        fixture_auth_write (0);
        if (fault == AUTH_MISSING)
            assert (!unlink (fixture_auth_file));
        extra = snprintf ((char *)config + length, sizeof (config) - length,
                          "  file: '%s'\n", fixture_auth_file);
    }
    assert (extra > 0 && (size_t)extra < sizeof (config) - length);
    alarm (5);
    assert (hev_socks5_server_main_from_str (config, length + extra) < 0);
    alarm (0);
    assert (!worker_list && !atomic_load (&fixture_starts));
    assert (fixture_created == workers && fixture_joins == workers - 1);
    assert (!(atomic_load (&tsync) & (SYNC_SEND | SYNC_WAIT | SYNC_STOP)));
    assert (atomic_load (&fixture_auth_allocated) == (fault != AUTH_ALLOC));
    assert (atomic_load (&fixture_auth_freed) ==
            atomic_load (&fixture_auth_allocated));
    for (int i = 0; i < fixture_created * 3; i++) {
        errno = 0;
        assert (fcntl (fixture_descriptors[i], F_GETFD) == -1 &&
                errno == EBADF);
    }
    fixture_auth_fault = AUTH_OK;
    printf ("proxy auth failure: PASS startup fault=%d workers=%d inline=%d "
            "started=0 refs=balanced descriptors=closed\n",
            fault, workers, inline_user);
}

int
main (int argc, char **argv)
{
    struct sigaction action;
    memset (&action, 0, sizeof (action));
    action.sa_handler = fixture_deadline;
    assert (sigemptyset (&action.sa_mask) == 0);
    assert (sigaction (SIGALRM, &action, NULL) == 0);
    fixture_main_thread = pthread_self ();
    if (argc == 2 && !strcmp (argv[1], "--auth-publication")) {
        alarm (30);
        fixture_auth_publication ();
        alarm (0);
        return 0;
    }
    assert (argc == 1 || argc == 3);
    if (argc == 3) {
        char *end;
        long mode = strtol (argv[1], &end, 10);
        assert (*argv[1] && !*end && mode >= FIX_STOP_ALL &&
                mode <= FIX_LATE_EXIT);
        long workers = strtol (argv[2], &end, 10);
        assert (*argv[2] && !*end &&
                (workers == 1 || workers == 2 || workers == 4));
        assert (workers > 1 || mode <= FIX_STOP_ZERO);
        fixture_case (mode, workers);
        return 0;
    }
    fixture_case (FIX_STOP_ALL, 1);
    fixture_case (FIX_STOP_ZERO, 1);
    for (int workers = 2; workers <= 4; workers *= 2)
        for (int mode = FIX_STOP_ALL; mode <= FIX_LATE_EXIT; mode++)
            fixture_case (mode, workers);
    fixture_auth_mode = FIX_AUTH_RELOAD;
    int auth_fd = mkstemp (fixture_auth_file);
    assert (auth_fd >= 0 && !close (auth_fd));
    for (int workers = 1; workers <= 4; workers *= 2) {
        atomic_store (&fixture_auth_allocated, 0);
        atomic_store (&fixture_auth_freed, 0);
        fixture_auth_write (0);
        fixture_case (FIX_STOP_ALL, workers);
    }
    fixture_auth_mode = FIX_AUTH_STARTUP_FAILURE;
    for (int workers = 1; workers <= 4; workers *= 2) {
        atomic_store (&fixture_auth_allocated, 0);
        atomic_store (&fixture_auth_freed, 0);
        fixture_case (workers == 1 ? FIX_STOP_ALL : FIX_TASK_INIT, workers);
    }
    fixture_auth_mode = FIX_AUTH_OFF;
    for (int workers = 1; workers <= 4; workers *= 2) {
        for (int fault = AUTH_MISSING; fault <= AUTH_EMPTY_PASS; fault++)
            fixture_auth_startup_failure (fault, workers, 0);
        fixture_auth_startup_failure (AUTH_ALLOC, workers, 1);
        fixture_auth_startup_failure (AUTH_USER, workers, 1);
        fixture_case (FIX_STOP_ALL, workers);
    }
    assert (!unlink (fixture_auth_file));
    puts ("proxy lifecycle: PASS 24 original cases, 27 authentication startup "
          "failures, 15 reload failures and 3 recovery starts");
    return 0;
}
