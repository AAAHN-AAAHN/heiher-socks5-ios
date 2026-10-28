#include "hev-main.h"
#include <arpa/inet.h>
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static struct sockaddr_in peer;

static void *
transferred_writer (void *writer)
{
    hev_socks5_server_io_writer_record (writer, (struct sockaddr *)&peer,
                                        sizeof (peer), 21, 29);
    return NULL;
}

static void *
independent_writer (void *unused)
{
    void *writer = hev_socks5_server_io_writer_new ();
    (void)unused;
    assert (writer);
    for (int i = 0; i < 10000; ++i)
        hev_socks5_server_io_writer_record (writer, (struct sockaddr *)&peer,
                                            sizeof (peer), 1, 2);
    hev_socks5_server_io_writer_free (writer);
    return NULL;
}

int
main (void)
{
    uint64_t received, sent;
    HevSocks5EndpointStats rows[8];
    struct sockaddr_in6 mapped = { 0 }, scoped = { 0 };
    pthread_t thread, other;
    void *writer;
    size_t count;
    int found = 0;

    peer.sin_family = AF_INET;
    assert (inet_pton (AF_INET, "192.0.2.9", &peer.sin_addr) == 1);
    writer = hev_socks5_server_io_writer_new ();
    assert (writer); /* No server or TLS initialization has occurred. */
    errno = EAGAIN;
    hev_socks5_server_io_writer_record (writer, (struct sockaddr *)&peer,
                                        sizeof (peer), 13, 17);
    assert (errno == EAGAIN);
    assert (!pthread_create (&thread, NULL, transferred_writer, writer));
    assert (!pthread_join (thread, NULL));
    hev_socks5_server_io_writer_free (writer);
    writer = hev_socks5_server_io_writer_new ();
    assert (writer);
    hev_socks5_server_io_writer_record (writer, (struct sockaddr *)&peer,
                                        sizeof (peer), 42, 37);
    mapped.sin6_family = AF_INET6;
    assert (inet_pton (AF_INET6, "::ffff:192.0.2.9", &mapped.sin6_addr) == 1);
    hev_socks5_server_io_writer_record (writer, (struct sockaddr *)&mapped,
                                        sizeof (mapped), 7, 11);
    hev_socks5_server_io_writer_record (writer, NULL, 0, 3, 5);
    scoped.sin6_family = AF_INET6;
    assert (inet_pton (AF_INET6, "fe80::9", &scoped.sin6_addr) == 1);
    scoped.sin6_scope_id = 3;
    hev_socks5_server_io_writer_record (writer, (struct sockaddr *)&scoped,
                                        sizeof (scoped), 2, 4);
    scoped.sin6_scope_id = 4;
    hev_socks5_server_io_writer_record (writer, (struct sockaddr *)&scoped,
                                        sizeof (scoped), 6, 8);
    hev_socks5_server_io_writer_record (writer, (struct sockaddr *)&peer,
                                        sizeof (peer), 0, 0);
    hev_socks5_server_io_writer_free (writer);
    hev_socks5_server_io_writer_free (NULL);
    hev_socks5_server_io_writer_record (NULL, NULL, 0, 100, 100);
    hev_socks5_server_endpoint_stats (&received, &sent);
    assert (received == 94 && sent == 111);
    count = hev_socks5_server_endpoint_rows (rows, 8);
    assert (count == 4);
    for (size_t i = 0; i < count; ++i) {
        if (!strcmp (rows[i].address, "192.0.2.9")) {
            assert (rows[i].received == 83 && rows[i].sent == 94);
            found |= 1;
        } else if (!strcmp (rows[i].address, "fe80::9%3")) {
            assert (rows[i].received == 2 && rows[i].sent == 4);
            found |= 2;
        } else if (!strcmp (rows[i].address, "fe80::9%4")) {
            assert (rows[i].received == 6 && rows[i].sent == 8);
            found |= 4;
        } else {
            assert (!strcmp (rows[i].address, "Unattributed"));
            assert (rows[i].received == 3 && rows[i].sent == 5);
            found |= 8;
        }
    }
    assert (found == 15);
    assert (!pthread_create (&thread, NULL, independent_writer, NULL));
    assert (!pthread_create (&other, NULL, independent_writer, NULL));
    assert (!pthread_join (thread, NULL));
    assert (!pthread_join (other, NULL));
    hev_socks5_server_endpoint_stats (&received, &sent);
    assert (received == 20094 && sent == 40111);
    puts (
        "PASS: explicit writers before TLS init, serialized thread migration, retained totals, normalization, scope and concurrent independent writers");
    return 0;
}
