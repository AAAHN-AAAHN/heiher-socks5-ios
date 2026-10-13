/* Actual UDP encoder, OS sends and peer counters. Linux traces, but does not
 * substitute, sendmmsg to prove GSO use separately from ordinary UDP fallback.
 */
#define _GNU_SOURCE
#include "hev-socks5-client-udp.h"
#include "hev-socks5-meter.h"
#include "hev-socks5-misc.h"
#include <arpa/inet.h>
#include <assert.h>
#include <errno.h>
#include <hev-task-system.h>
#include <netinet/udp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <unistd.h>

static size_t accepted_bytes;
static unsigned gso_groups;

#if defined(__linux__) && defined(UDP_SEGMENT)
int __real_sendmmsg(int fd, struct mmsghdr *messages, unsigned num, int flags);
int __wrap_sendmmsg(int fd, struct mmsghdr *messages, unsigned num, int flags) {
  int result = __real_sendmmsg(fd, messages, num, flags);
  int saved = errno;
  for (int i = 0; i < result; i++) {
    struct msghdr *msg = &messages[i].msg_hdr;
    accepted_bytes += messages[i].msg_len;
    for (struct cmsghdr *cm = CMSG_FIRSTHDR(msg); cm; cm = CMSG_NXTHDR(msg, cm))
      if (cm->cmsg_level == SOL_UDP && cm->cmsg_type == UDP_SEGMENT)
        gso_groups++;
  }
  errno = saved;
  return result;
}
#endif

typedef struct {
  const char *address;
  uint64_t in, out;
  unsigned found;
} Peer;

static void read_peer(uint64_t id, const char *address, uint64_t in,
                      uint64_t out, void *context) {
  Peer *peer = context;
  if (!strcmp(address, peer->address)) {
    assert(id && !peer->found++);
    peer->in = in;
    peer->out = out;
  }
}

static void exercise(HevSocks5ClientUDP *client, int receiver,
                     const char *peer_address, unsigned count, unsigned length,
                     int mixed, int gso_supported) {
  HevSocks5Addr address;
  assert(hev_socks5_addr_from_ipv4(
             &address, (const unsigned char[]){127, 0, 0, 1}, htons(1234)) > 0);
  HevSocks5UDPMsg *messages = calloc(count, sizeof(*messages));
  unsigned char *data = calloc(count, (size_t)length + 1);
  unsigned char wire[65536];
  uint64_t before_in, before_out, after_in, after_out, expected = 0;
  Peer before = {.address = peer_address}, after = {.address = peer_address};
  assert(messages && data);
  for (unsigned i = 0; i < count; i++) {
    messages[i].addr = &address;
    messages[i].buf = data + i * ((size_t)length + 1);
    messages[i].len = length + (mixed ? i % 2 : 0);
    memset(messages[i].buf, 1 + i % 254, messages[i].len);
    expected += 10 + messages[i].len;
  }
  hev_meter_totals(&before_in, &before_out);
  hev_meter_rows(read_peer, &before);
  accepted_bytes = gso_groups = 0;
  assert(hev_socks5_udp_sendmmsg(client, messages, count) == (int)count);
  for (unsigned i = 0; i < count; i++) {
    ssize_t received = recv(receiver, wire, sizeof(wire), 0);
    assert(received == (ssize_t)(10 + messages[i].len));
    assert(!wire[0] && !wire[1] && !wire[2]);
    assert(!memcmp(wire + 3, &address, 7));
    assert(!memcmp(wire + 10, messages[i].buf, messages[i].len));
  }
  assert(recv(receiver, wire, sizeof(wire), MSG_DONTWAIT) == -1 &&
         (errno == EAGAIN || errno == EWOULDBLOCK));
  hev_meter_totals(&after_in, &after_out);
  hev_meter_rows(read_peer, &after);
  assert(after_in - before_in == expected && after_out == before_out);
  assert(after.found == 1 && after.in - before.in == expected &&
         after.out == before.out);
#if defined(__linux__) && defined(UDP_SEGMENT)
  assert(accepted_bytes == expected);
  if (count > 1 && !mixed && length < 2000 && gso_supported)
    assert(gso_groups > 0);
  else
    assert(!gso_groups);
#else
  (void)gso_supported;
#endif
  printf("PASS: peer=%s datagrams=%u payload=%u mixed=%d bytes=%llu GSO=%u\n",
         peer_address, count, length, mixed, (unsigned long long)expected,
         gso_groups);
  free(messages);
  free(data);
}

int main(void) {
  assert(!hev_task_system_init());
  assert(!hev_meter_prepare() && !hev_meter_worker_enter());
  for (int family_index = 0; family_index < 2; family_index++) {
    int family = family_index ? AF_INET6 : AF_INET;
    int reader = socket(family, SOCK_DGRAM, 0);
    int writer = socket(family, SOCK_DGRAM, 0);
    int capacity = 1024 * 1024, gso_supported = 0;
    assert(reader >= 0 && writer >= 0);
    struct sockaddr_storage storage = {0};
    socklen_t size;
    if (family == AF_INET) {
      struct sockaddr_in value = {.sin_family = AF_INET,
                                  .sin_addr.s_addr = htonl(INADDR_LOOPBACK)};
      memcpy(&storage, &value, sizeof(value));
      size = sizeof(value);
    } else {
      struct sockaddr_in6 value = {.sin6_family = AF_INET6,
                                   .sin6_addr = IN6ADDR_LOOPBACK_INIT};
      memcpy(&storage, &value, sizeof(value));
      size = sizeof(value);
    }
    assert(!bind(reader, (struct sockaddr *)&storage, size));
    assert(!getsockname(reader, (struct sockaddr *)&storage, &size));
    assert(!connect(writer, (struct sockaddr *)&storage, size));
    struct timeval timeout = {.tv_sec = 2};
    assert(!setsockopt(reader, SOL_SOCKET, SO_RCVTIMEO, &timeout,
                       sizeof(timeout)));
    assert(!setsockopt(reader, SOL_SOCKET, SO_RCVBUF, &capacity,
                       sizeof(capacity)));
#if defined(__linux__) && defined(UDP_SEGMENT)
    /* Probe a separate fd; a persistent segmentation setting must not alter
     * the tested sender's single-datagram control case. */
    int probe = socket(AF_INET, SOCK_DGRAM, 0), segment = 1024;
    assert(probe >= 0);
    gso_supported =
        !setsockopt(probe, SOL_UDP, UDP_SEGMENT, &segment, sizeof(segment));
    close(probe);
#endif
    HevSocks5ClientUDP *client =
        hev_socks5_client_udp_new(HEV_SOCKS5_TYPE_UDP_IN_UDP);
    assert(client);
    client->fd = writer;
    HEV_SOCKS5(client)->timeout = 60000;
    HEV_SOCKS5(client)->io_udp_peer = hev_meter_fd(writer);
    HEV_SOCKS5(client)->udp_associated = 1;
    const char *peer = family_index ? "::1" : "127.0.0.1";
    exercise(client, reader, peer, 1, 100, 0, gso_supported);
    exercise(client, reader, peer, 2, 100, 0, gso_supported);
    exercise(client, reader, peer, 2, 100, 1, gso_supported);
    exercise(client, reader, peer, 2, 0, 0, gso_supported);
    exercise(client, reader, peer, 65, 1000, 0, gso_supported);
    exercise(client, reader, peer, 2, 48001, 0, gso_supported);
    client->fd = -1;
    hev_object_unref(HEV_OBJECT(client));
    close(writer);
    close(reader);
  }
  hev_meter_worker_leave();
  hev_task_system_fini();
  puts("PASS: 12 real UDP/GSO sends, packet order, OS bytes and peer totals");
  return 0;
}
