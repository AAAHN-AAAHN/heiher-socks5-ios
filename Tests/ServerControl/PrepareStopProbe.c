/* Test only: preserve legacy cancellation, plus cancellation after prepare. */
#include "hev-main.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    char config[256];
    if (argc != 3) return 2;
    snprintf(config, sizeof(config), "main:\n  workers: %d\n  listen-address: '127.0.0.1'\n  port: %d\n", atoi(argv[1]), atoi(argv[2]));
    for (int mode = 0; mode < 2; mode++) {
        for (int i = 0; i < 25; i++) {
            if (mode) hev_socks5_server_prepare();
            hev_socks5_server_quit();
            if (hev_socks5_server_main_from_str((const unsigned char *)config, strlen(config)) != 0) return 1;
        }
    }
    puts("PASS: 25 legacy and 25 prepared stop-before-start invocations returned");
    return 0;
}
