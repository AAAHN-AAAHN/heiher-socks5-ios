/* Consume actual Swift-generated YAML with the pinned engine's actual parser. */
#include "hev-config.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>

static void require (int condition, const char *message)
{
    if (!condition) {
        fprintf (stderr, "FAIL: %s\n", message);
        exit (1);
    }
}

int main (int argc, char **argv)
{
    require (argc == 3, "two Swift-generated fixtures are required");
    require (hev_config_init_from_file (argv[1]) == 0, "default YAML parses");
    require (hev_config_get_workers () == 4, "default workers");
    require (strcmp (hev_config_get_listen_address (), "::") == 0, "default listen address");
    require (strcmp (hev_config_get_listen_port (), "1080") == 0, "default TCP port");
    require (hev_config_get_udp_listen_port () == 1080, "default UDP port");
    require (hev_config_get_listen_ipv6_only () == 0, "default IPv6-only flag");
    require (strcmp (hev_config_get_bind_address (AF_INET), "0.0.0.0") == 0, "default IPv4 bind");
    require (strcmp (hev_config_get_bind_address (AF_INET6), "::") == 0, "default IPv6 bind");
    require (hev_config_init_from_file (argv[2]) == 0, "quoted YAML parses");
    require (hev_config_get_workers () == 2, "configured workers");
    require (strcmp (hev_config_get_listen_address (), "127.0.0.1") == 0, "configured listen address");
    require (strcmp (hev_config_get_listen_port (), "23456") == 0, "configured TCP port");
    require (strcmp (hev_config_get_udp_listen_address (), "127.0.0.1") == 0, "configured UDP address");
    require (hev_config_get_udp_listen_port () == 0, "zero UDP port");
    require (hev_config_get_listen_ipv6_only () == 1, "configured IPv6-only flag");
    require (strcmp (hev_config_get_bind_interface (), "test'if") == 0, "literal interface quote");
    require (strcmp (hev_config_get_auth_username (), "user'# []{}:") == 0, "literal username syntax");
    require (strcmp (hev_config_get_auth_password (), "safe'@&*:") == 0, "literal password syntax");
    puts ("PASS: real engine parses Swift defaults and quoted values without YAML structure injection");
    return 0;
}
