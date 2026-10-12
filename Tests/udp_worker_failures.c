#define _GNU_SOURCE
/* Exercise the actual worker lifecycle and descriptors. Only named allocation,
 * registration and read-error boundaries are injected. EOF comes from a real
 * socket shutdown. Constructor-owned tasks retain their production 64KiB
 * default; the observer uses 8KiB (64KiB under ASan). Normal sessions use 8KiB. */
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <hev-task.h>
#include <hev-task-system.h>
#include <hev-task-io.h>
#include <hev-task-io-socket.h>
#include <hev-memory-allocator.h>
#include "hev-config.h"
#include "hev-socks5-session.h"
#include "hev-socks5-worker.h"

#ifndef __has_feature
#define __has_feature(x) 0
#endif
#if defined(__SANITIZE_ADDRESS__) || __has_feature(address_sanitizer)
#define TEST_STACK_SIZE 65536
#else
#define TEST_STACK_SIZE 8192
#endif

static void *worker_malloc0 (size_t);
static void worker_free (void *);
static int worker_socketpair (int, int, int, int[2]);
static int worker_add (HevTask *, int, unsigned int);
static ssize_t worker_read (int, void *, size_t, HevTaskIOYielder, void *);
static int worker_accept (int, struct sockaddr *, socklen_t *, HevTaskIOYielder,
                          void *);
static HevTask *worker_task_new (int);
static void worker_task_unref (HevTask *);
static void worker_wakeup (HevTask *);
static HevSocks5Session *worker_session_new (int);
static void worker_object_unref (HevObject *);

#define hev_malloc0 worker_malloc0
#define hev_free worker_free
#define socketpair worker_socketpair
#define hev_task_add_fd worker_add
#define hev_task_io_read worker_read
#define hev_task_io_socket_accept worker_accept
#define hev_task_new worker_task_new
#define hev_task_unref worker_task_unref
#define hev_task_wakeup worker_wakeup
#define hev_socks5_session_new worker_session_new
#define hev_object_unref worker_object_unref
#include "hev-socks5-worker.c"
#undef hev_malloc0
#undef hev_free
#undef socketpair
#undef hev_task_add_fd
#undef hev_task_io_read
#undef hev_task_io_socket_accept
#undef hev_task_new
#undef hev_task_unref
#undef hev_task_wakeup
#undef hev_socks5_session_new
#undef hev_object_unref

enum
{
    NORMAL,
    LISTENER_ADD,
    EVENT_ADD,
    EVENT_EOF,
    EVENT_ERROR,
    SESSION_OOM,
    TASK_OOM,
    ACCEPT_ERROR,
    ACCEPT_SETUP,
    WORKER_OOM,
    WORKER_TASK1,
    WORKER_TASK2
};
static const char *names[] = { "normal",     "listener-add", "event-add",
                               "event-eof",  "event-error",  "session-oom",
                               "task-oom",   "accept-error", "accept-setup",
                               "worker-oom", "worker-task1", "worker-task2" };
static int test, listener, event_fds[2] = { -1, -1 };
static int observer_ran, intervention, add_faults, read_calls, accept_calls;
static int accepted[8], accepted_count, accepts_before_observer;
static int failed_accepts_before_observer, accept_after_stop, wakeup_stopped;
static int terminal_read_retries;
static int task_calls, tasks_created, tasks_released, session_calls;
static int sessions_created, sessions_released;
static HevObject *session_objects[8];
static HevSocks5Worker *worker;
static void *worker_allocation;

static int
open_fd (int fd)
{
    return fd >= 0 && fcntl (fd, F_GETFD) >= 0;
}

static void *
worker_malloc0 (size_t size)
{
    if (test == WORKER_OOM) {
        errno = ENOMEM;
        return NULL;
    }
    assert (!worker_allocation);
    worker_allocation = calloc (1, size);
    assert (worker_allocation);
    return worker_allocation;
}

static void
worker_free (void *ptr)
{
    assert (ptr == worker_allocation && ptr);
    worker_allocation = NULL;
    free (ptr);
}

static int
worker_socketpair (int domain, int type, int protocol, int fds[2])
{
    int res = socketpair (domain, type, protocol, fds);
    if (!res) {
        event_fds[0] = fds[0];
        event_fds[1] = fds[1];
    }
    return res;
}

static int
worker_add (HevTask *task, int fd, unsigned int events)
{
    if ((test == LISTENER_ADD && fd == listener) ||
        (test == EVENT_ADD && fd == event_fds[0])) {
        add_faults++;
        errno = ENOMEM;
        return -1;
    }
    return hev_task_add_fd (task, fd, events);
}

static ssize_t
worker_read (int fd, void *buf, size_t len, HevTaskIOYielder yielder,
             void *data)
{
    read_calls++;
    if ((test == EVENT_EOF || test == EVENT_ERROR) && read_calls > 1) {
        /* Preserve a FAIL, then supply a Stop byte only for fixture teardown
         * so a known broken baseline cannot prevent the remaining cases. */
        terminal_read_retries++;
        printf ("%s repeated terminal read: calls=%d FAIL; fixture teardown\n",
                names[test], read_calls);
        *(char *)buf = 's';
        return 1;
    }
    if (test == EVENT_ERROR) {
        errno = EIO;
        return -1;
    }
    return hev_task_io_read (fd, buf, len, yielder, data);
}

static int
worker_accept (int fd, struct sockaddr *addr, socklen_t *len,
               HevTaskIOYielder yielder, void *data)
{
    int res;
    accept_calls++;
    if (!worker->run)
        accept_after_stop++;
    if (test == ACCEPT_ERROR) {
        if (!observer_ran && ++failed_accepts_before_observer > 1) {
            printf ("%s repeated accept error before runnable observer FAIL; "
                    "fixture teardown\n",
                    names[test]);
            return -2;
        }
        errno = EMFILE;
        return -1;
    }
    res = hev_task_io_socket_accept (fd, addr, len, yielder, data);
    if (res >= 0) {
        assert (accepted_count < 8);
        accepted[accepted_count++] = res;
        if (!observer_ran)
            accepts_before_observer++;
        if (test == ACCEPT_SETUP) {
            /* Match the task helper's non-SOCK_NONBLOCK FIONBIO failure
             * contract: it closes its newly accepted descriptor, then -3.
             * The descriptor and close are real; the FIONBIO error is injected. */
            assert (close (res) == 0);
            errno = EIO;
            return -3;
        }
    }
    return res;
}

static HevTask *
worker_task_new (int size)
{
    HevTask *task;
    task_calls++;
    if ((test == WORKER_TASK1 && task_calls == 1) ||
        (test == WORKER_TASK2 && task_calls == 2) ||
        (test == TASK_OOM && task_calls > 2)) {
        errno = ENOMEM;
        return NULL;
    }
    task = hev_task_new (size);
    assert (task);
    tasks_created++;
    return task;
}

static void
worker_task_unref (HevTask *task)
{
    tasks_released++;
    hev_task_unref (task);
}

static void
worker_wakeup (HevTask *task)
{
    if (hev_task_get_state (task) == HEV_TASK_STOPPED) {
        wakeup_stopped++;
        printf ("%s waking STOPPED worker before real wakeup: FAIL\n",
                names[test]);
        fflush (stdout);
        /* The native helper aborts here (preserved by the separate baseline
         * run). Record the violation and allow aggregate fixture teardown. */
        return;
    }
    hev_task_wakeup (task);
}

static HevSocks5Session *
worker_session_new (int fd)
{
    HevSocks5Session *session;
    session_calls++;
    if (test == SESSION_OOM) {
        errno = ENOMEM;
        return NULL;
    }
    session = hev_socks5_session_new (fd);
    assert (session && sessions_created < 8);
    session_objects[sessions_created++] = HEV_OBJECT (session);
    return session;
}

static void
worker_object_unref (HevObject *object)
{
    int i;
    for (i = 0; i < sessions_created; i++) {
        if (session_objects[i] == object) {
            sessions_released++;
            session_objects[i] = NULL;
            break;
        }
    }
    hev_object_unref (object);
}

static void
observe_and_stop (void *data)
{
    (void)data;
    observer_ran = 1;
    if (test == SESSION_OOM || test == TASK_OOM || test == NORMAL ||
        test == ACCEPT_ERROR || test == ACCEPT_SETUP) {
        hev_socks5_worker_stop (worker);
        return;
    }
    /* Give the candidate's own failure exit time to finish. For an unfixed
     * start path, repair only the test's reactor registration so Stop can reap
     * both real tasks; this intervention itself fails the correctness oracle. */
    hev_task_sleep (5);
    if (worker->run) {
        intervention = 1;
        if (test == EVENT_ADD)
            assert (hev_task_add_fd (worker->task_event, event_fds[0],
                                     POLLIN) == 0);
        hev_socks5_worker_stop (worker);
    } else if (hev_task_get_state (worker->task_worker) != HEV_TASK_STOPPED) {
        intervention = 1;
        hev_task_wakeup (worker->task_worker);
    }
}

static int
run_one (int which)
{
    struct sockaddr_in addr = { .sin_family = AF_INET };
    socklen_t len = sizeof (addr);
    HevTask *observer;
    int clients[2] = { -1, -1 }, passed = 1, ownership, i;
    test = which;
    listener = event_fds[0] = event_fds[1] = -1;
    observer_ran = intervention = add_faults = read_calls = accept_calls = 0;
    accepted_count = accepts_before_observer = failed_accepts_before_observer =
        0;
    accept_after_stop = wakeup_stopped = terminal_read_retries = 0;
    task_calls = tasks_created = tasks_released = session_calls = 0;
    sessions_created = sessions_released = 0;
    worker = NULL;
    worker_allocation = NULL;
    memset (accepted, 0, sizeof (accepted));
    memset (session_objects, 0, sizeof (session_objects));
    if (hev_task_system_init ())
        return 2;
    assert (hev_config_init_from_str ((const unsigned char *)"{}", 2) == 0);
    listener = hev_task_io_socket_socket (AF_INET, SOCK_STREAM, 0);
    assert (listener >= 0);
    addr.sin_addr.s_addr = htonl (INADDR_LOOPBACK);
#if defined(__APPLE__)
    addr.sin_len = sizeof (addr);
#endif
    assert (bind (listener, (struct sockaddr *)&addr, len) == 0);
    assert (listen (listener, 8) == 0);
    assert (getsockname (listener, (struct sockaddr *)&addr, &len) == 0);
    if (test == SESSION_OOM || test == TASK_OOM || test == ACCEPT_SETUP) {
        for (i = 0; i < 2; i++) {
            clients[i] = socket (AF_INET, SOCK_STREAM, 0);
            assert (clients[i] >= 0);
            assert (connect (clients[i], (struct sockaddr *)&addr, len) == 0);
        }
    }
    worker = hev_socks5_worker_new (listener);
    if (test >= WORKER_OOM) {
        passed = !worker && !worker_allocation && open_fd (listener) &&
                 !open_fd (event_fds[0]) && !open_fd (event_fds[1]) &&
                 tasks_created == tasks_released;
        assert (close (listener) == 0);
        ownership = passed;
    } else {
        assert (worker);
        if (test == EVENT_EOF)
            assert (shutdown (event_fds[1], SHUT_WR) == 0);
        observer = hev_task_new (TEST_STACK_SIZE);
        assert (observer);
        hev_task_ref (observer);
        hev_socks5_worker_start (worker);
        hev_task_run (observer, observe_and_stop, NULL);
        hev_task_system_run ();
        ownership = open_fd (listener) && open_fd (event_fds[0]) &&
                    open_fd (event_fds[1]);
        passed &= !worker->run && !intervention && !accept_after_stop &&
                  !wakeup_stopped && !terminal_read_retries &&
                  !hev_list_first (&worker->session_set);
        for (i = 0; i < accepted_count; i++)
            passed &= !open_fd (accepted[i]);
        if (test == LISTENER_ADD)
            passed &= add_faults == 1 && !accept_calls;
        if (test == EVENT_ADD)
            passed &= add_faults == 1 && !accept_calls && !read_calls;
        if (test == EVENT_EOF || test == EVENT_ERROR)
            passed &= read_calls == 1 && !accept_calls;
        if (test == SESSION_OOM || test == TASK_OOM)
            passed &= accepts_before_observer == 1 && accepted_count >= 1 &&
                      session_calls == accepted_count &&
                      sessions_created == sessions_released;
        if (test == ACCEPT_ERROR)
            passed &= failed_accepts_before_observer == 1 && !accepted_count &&
                      !session_calls;
        if (test == ACCEPT_SETUP)
            passed &= accepts_before_observer == 1 && accepted_count >= 1 &&
                      !session_calls;
        hev_socks5_worker_destroy (worker);
        passed &= !worker_allocation && !open_fd (listener) &&
                  !open_fd (event_fds[0]) && !open_fd (event_fds[1]) &&
                  tasks_created == tasks_released;
        hev_task_unref (observer);
    }
    passed &= ownership;
    for (i = 0; i < 2; i++) {
        if (clients[i] >= 0) {
            passed &= open_fd (clients[i]);
            assert (close (clients[i]) == 0);
        }
    }
    printf (
        "%s intervention=%d add_faults=%d read=%d accept=%d accepted=%d "
        "before_observer=%d session=%d/%d task=%d/%d worker_heap=%d "
        "ownership=%d after_stop=%d stopped_wakeup=%d observer_stack=%d %s\n",
        names[test], intervention, add_faults, read_calls, accept_calls,
        accepted_count, accepts_before_observer, sessions_created,
        sessions_released, tasks_created, tasks_released,
        worker_allocation != NULL, ownership, accept_after_stop, wakeup_stopped,
        TEST_STACK_SIZE, passed ? "PASS" : "FAIL");
    hev_task_system_fini ();
    return passed ? 0 : 1;
}

int
main (void)
{
    int which, failed = 0;
    for (which = 0; which < 12; which++)
        failed += !!run_one (which);
    printf ("worker failures: %d/12 cases PASS; failures=%d\n", 12 - failed,
            failed);
    return failed ? 1 : 0;
}
