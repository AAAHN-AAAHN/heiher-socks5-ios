/* Exercise the real multi-worker shutdown path, including cancellation before init. */
#include "hev-main.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main (int argc, char **argv)
{
    char config[256];
    int workers = argc > 1 ? atoi (argv[1]) : 4;
    int port = argc > 2 ? atoi (argv[2]) : 39876;
    int i;

    snprintf (config, sizeof (config),
              "main:\n  workers: %d\n  listen-address: '127.0.0.1'\n  port: %d\n",
              workers, port);
    for (i = 0; i < 20; i++) {
        hev_socks5_server_quit ();
        if (hev_socks5_server_main_from_str ((const unsigned char *)config,
                                            strlen (config)) != 0)
            return 1;
    }
    puts ("PASS: 20 real stop-before-start cycles returned without a worker hang");
    return 0;
}
