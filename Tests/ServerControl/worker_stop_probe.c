/* Compile the actual worker body; substitute only its cooperative yield boundary. */
#include <stdio.h>
#define hev_task_yield worker_probe_yield
#include "hev-socks5-worker.c"
#undef hev_task_yield

static HevSocks5Worker *observed;
static int yields;
static int stop_while_yielding;

void
worker_probe_yield (HevTaskYieldType type)
{
    yields++;
    if (stop_while_yielding)
        WRITE_ONCE (observed->run, 0);
}

int
main (void)
{
    HevSocks5Worker worker = { 0 };
    int failures = 0;
    int result;
    observed = &worker;

    result = task_io_yielder (HEV_TASK_WAITIO, &worker);
    if (result != -1 || yields != 0) {
        puts ("FAIL: already-stopped worker entered a wait after its stop wakeup");
        failures++;
    } else {
        puts ("PASS: already-stopped worker returns without yielding");
    }

    yields = 0;
    WRITE_ONCE (worker.run, 1);
    result = task_io_yielder (HEV_TASK_WAITIO, &worker);
    if (result != 0 || yields != 1) {
        puts ("FAIL: healthy worker yield changed");
        failures++;
    } else {
        puts ("PASS: healthy worker yields once and continues");
    }

    yields = 0;
    stop_while_yielding = 1;
    result = task_io_yielder (HEV_TASK_WAITIO, &worker);
    if (result != -1 || yields != 1) {
        puts ("FAIL: Stop during suspension was not observed");
        failures++;
    } else {
        puts ("PASS: Stop delivered while yielding still ends the wait");
    }
    printf ("SUMMARY: three worker-yield postconditions; %d failed\n", failures);
    return failures ? 1 : 0;
}
