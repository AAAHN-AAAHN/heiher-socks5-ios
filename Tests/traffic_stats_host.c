/* Test-only host for querying the server API while native workers run. */
#include <inttypes.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "hev-main.h"

static void *
run_server (void *path)
{
    hev_socks5_server_main_from_file (path);
    return NULL;
}

int
main (int argc, char **argv)
{
    _Atomic uint64_t probe = 0;
    pthread_t worker;
    char command[32];

    if (argc != 2 || pthread_create (&worker, NULL, run_server, argv[1]))
        return 1;
    printf ("LOCK_FREE %d\n", atomic_is_lock_free (&probe));
    fflush (stdout);
    while (fgets (command, sizeof (command), stdin)) {
        uint64_t received, sent;
        if (!strcmp (command, "quit\n"))
            break;
        if (!strcmp (command, "restart\n")) {
            hev_socks5_server_quit ();
            pthread_join (worker, NULL);
            if (pthread_create (&worker, NULL, run_server, argv[1]))
                return 2;
        }
        if (!strcmp (command, "clients\n")) {
            size_t capacity = hev_socks5_server_client_stats (NULL, 0) + 32;
            HevSocks5ClientStats *rows = calloc (capacity, sizeof (*rows));
            if (!rows)
                return 3;
            size_t count = hev_socks5_server_client_stats (rows, capacity);
            if (count > capacity)
                count = capacity;
            printf ("CLIENTS %zu\n", count);
            for (size_t i = 0; i < count; i++)
                printf ("CLIENT %" PRIu64 " %s %" PRIu64 " %" PRIu64 "\n",
                        rows[i].id, rows[i].address, rows[i].received,
                        rows[i].sent);
            free (rows);
            fflush (stdout);
            continue;
        }
        hev_socks5_server_stats (&received, &sent);
        printf ("STATS %" PRIu64 " %" PRIu64 "\n", received, sent);
        fflush (stdout);
    }
    hev_socks5_server_quit ();
    pthread_join (worker, NULL);
    return 0;
}
