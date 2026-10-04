/* Real initialization; only allocation and credential-read outcomes are injectable. */
#include <assert.h>
#include <arpa/inet.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>
#include <hev-socks5-authenticator.h>
#include "hev-main.h"
#include "hev-socks5-user-mark.h"

static int fail_auth, fail_user, fail_read, auth_calls, user_calls;

static HevSocks5Authenticator *
new_auth (void)
{
    auth_calls++;
    return fail_auth ? NULL : hev_socks5_authenticator_new ();
}

static HevSocks5UserMark *
new_user (const char *name, unsigned int nlen, const char *pass,
          unsigned int plen, unsigned int mark)
{
    user_calls++;
    return fail_user ? NULL :
                       hev_socks5_user_mark_new (name, nlen, pass, plen, mark);
}

static ssize_t
read_line (char **line, size_t *length, FILE *file)
{
    if (fail_read) {
        errno = ENOMEM;
        return -1;
    }
    return getline (line, length, file);
}

#define hev_socks5_authenticator_new new_auth
#define hev_socks5_user_mark_new new_user
#define getline read_line
#include "hev-socks5-proxy.c"
#undef getline
#undef hev_socks5_authenticator_new
#undef hev_socks5_user_mark_new

int
main (int argc, char **argv)
{
    const char *auth[] = { "",
                           "auth:\n  username: 'user'\n  password: 'pass'\n",
                           "auth:\n  username: 'user'\n  password: 'pass'\n",
                           "auth:\n  username: ''\n  password: 'pass'\n",
                           "auth:\n  username: 'user'\n  password: ''\n",
                           "auth:\n  file: '/dev/null/missing-auth-file'\n",
                           "auth:\n  file: '/dev/null'\n",
                           "auth:\n  username: 'user'\n  password: 'pass'\n" };
    const int expected[] = { 0, -1, -1, -1, -1, -1, -1, 0 };
    struct sockaddr_in address = { .sin_family = AF_INET };
    char config[512];
    int workers, port, i;

    assert (argc == 3);
    workers = atoi (argv[1]);
    port = atoi (argv[2]);
    address.sin_addr.s_addr = htonl (INADDR_LOOPBACK);
    address.sin_port = htons (port);
    for (i = 0; i < 8; i++) {
        int result, fd;
        fail_auth = i <= 1;
        fail_user = i == 2;
        fail_read = i == 6;
        auth_calls = user_calls = 0;
        snprintf (config, sizeof (config),
                  "main:\n  workers: %d\n  listen-address: '127.0.0.1'\n"
                  "  port: %d\n  udp-port: 0\n%s",
                  workers, port, auth[i]);
        /* Keep success cases bounded without replacing initialization or cleanup. */
        hev_socks5_server_prepare ();
        hev_socks5_server_quit ();
        result = hev_socks5_server_main_from_str ((const unsigned char *)config,
                                                  strlen (config));
        if (result != expected[i]) {
            fprintf (stderr, "case %d: result %d, expected %d\n", i, result,
                     expected[i]);
            return 1;
        }
        if (i == 0)
            assert (!auth_calls && !user_calls);
        if (i == 1)
            assert (auth_calls == 1 && !user_calls);
        if (i == 2)
            assert (auth_calls == 1 && user_calls == 1);
        fd = socket (AF_INET, SOCK_STREAM, 0);
        assert (fd >= 0);
        assert (bind (fd, (struct sockaddr *)&address, sizeof (address)) == 0);
        close (fd);
    }
    puts (
        "PASS: eight authentication startup cases; failure closes the listener and releases workers");
    return 0;
}
