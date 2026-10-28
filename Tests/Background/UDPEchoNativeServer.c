#include "hev-main.h"
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static const char *configuration;
static pthread_t worker;
static atomic_int result;
static int running;

static void *
serve (void *unused)
{
    (void)unused;
    atomic_store (&result, hev_socks5_server_main_from_file (configuration));
    return NULL;
}

static void
start (void)
{
    HevSocks5ListenerInfo info;
    int ready = 0;

    assert (!running);
    hev_socks5_server_prepare ();
    atomic_store (&result, -999);
    assert (!pthread_create (&worker, NULL, serve, NULL));
    running = 1;
    for (int i = 0; i < 5000; ++i) {
        ready = hev_socks5_server_listener_info (&info);
        if (ready || atomic_load (&result) != -999)
            break;
        usleep (1000);
    }
    assert (ready && info.port);
    printf ("{\"state\":\"ready\",\"address\":\"%s\",\"port\":%u,"
            "\"ipv6_only\":%d}\n",
            info.address, info.port, info.ipv6_only);
    fflush (stdout);
}

static void
stop (void)
{
    HevSocks5ListenerInfo info;

    if (running) {
        hev_socks5_server_quit ();
        assert (!pthread_join (worker, NULL));
        running = 0;
        assert (!atomic_load (&result));
    }
    assert (!hev_socks5_server_listener_info (&info));
    puts ("{\"state\":\"stopped\"}");
    fflush (stdout);
}

int
main (int argc, char **argv)
{
    char command[32];

    assert (argc == 2);
    configuration = argv[1];
    start ();
    while (fgets (command, sizeof (command), stdin)) {
        if (!strcmp (command, "stop\n"))
            stop ();
        else if (!strcmp (command, "start\n"))
            start ();
        else
            assert (!"Unknown test command");
    }
    stop ();
    return 0;
}
