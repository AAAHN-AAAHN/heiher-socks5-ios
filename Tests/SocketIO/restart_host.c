/* Restart fixture only: observe all four workers' first accept wait.
 * This establishes a running-engine precondition, not early-Stop safety.
 * The native yield, run flag, I/O and Stop implementation remain unchanged. */
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <hev-task.h>

enum
{
    RESTART_WORKERS = 4
};
static pthread_mutex_t ready_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t ready_changed = PTHREAD_COND_INITIALIZER;
static const void *ready_workers[RESTART_WORKERS];
static unsigned ready_count;
static unsigned generation;

void
socket_io_worker_wait (const void *worker, int type)
{
    if (type != HEV_TASK_WAITIO)
        return;
    pthread_mutex_lock (&ready_lock);
    for (unsigned i = 0; i < ready_count; i++) {
        if (ready_workers[i] == worker) {
            pthread_mutex_unlock (&ready_lock);
            return;
        }
    }
    if (ready_count == RESTART_WORKERS) {
        fputs ("Unexpected extra worker in four-worker restart fixture\n",
               stderr);
        abort ();
    }
    ready_workers[ready_count++] = worker;
    pthread_cond_signal (&ready_changed);
    pthread_mutex_unlock (&ready_lock);
}

static int
ready_create (pthread_t *thread, const pthread_attr_t *attributes,
              void *(*entry) (void *), void *data)
{
    struct timespec deadline;
    int result;

    if (clock_gettime (CLOCK_REALTIME, &deadline))
        return errno;
    deadline.tv_sec += 5;
    /* The caller has joined the preceding engine before creating its successor. */
    pthread_mutex_lock (&ready_lock);
    ready_count = 0;
    generation++;
    pthread_mutex_unlock (&ready_lock);
    result = pthread_create (thread, attributes, entry, data);
    if (result)
        return result;
    pthread_mutex_lock (&ready_lock);
    while (ready_count != RESTART_WORKERS && !result)
        result =
            pthread_cond_timedwait (&ready_changed, &ready_lock, &deadline);
    if (result) {
        fprintf (
            stderr,
            "Restart readiness failed: generation=%u workers=%u/4 error=%d deadline=5s\n",
            generation, ready_count, result);
    } else {
        fprintf (
            stderr,
            "Restart readiness: generation=%u workers=4/4 first-WAITIO observed\n",
            generation);
    }
    pthread_mutex_unlock (&ready_lock);
    return result;
}

/* Only this host's outer engine creation is wrapped; native worker creation
 * remains in the original library. stdout keeps the original host protocol. */
#define pthread_create ready_create
#include "meter_host.c"
#undef pthread_create
