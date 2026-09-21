/* Native socket diagnosis only; no Hev or app source changes. */
#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

static void probe(int mapped_bind)
{
    int server = socket(AF_INET, SOCK_DGRAM, 0);
    int client = socket(AF_INET6, SOCK_DGRAM, 0);
    int zero = 0;
    struct timeval timeout = {1, 0};
    struct sockaddr_in target = {0}, peer = {0};
    struct sockaddr_in6 destination = {0}, local = {0}, received;
    socklen_t length = sizeof(target), peer_length = sizeof(peer);
    char buffer[64], actual[INET6_ADDRSTRLEN], assumed[INET6_ADDRSTRLEN];
    struct iovec iov = {buffer, sizeof(buffer)};
    struct msghdr message = {0};
    ssize_t result;

    target.sin_family = AF_INET;
    inet_pton(AF_INET, "127.0.0.1", &target.sin_addr);
#ifdef __APPLE__
    target.sin_len = sizeof(target);
#endif
    setsockopt(server, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(client, IPPROTO_IPV6, IPV6_V6ONLY, &zero, sizeof(zero));
    if (bind(server, (struct sockaddr *)&target, sizeof(target)) < 0)
        goto fail;
    getsockname(server, (struct sockaddr *)&target, &length);
    if (mapped_bind) {
        local.sin6_family = AF_INET6;
        inet_pton(AF_INET6, "::ffff:0.0.0.0", &local.sin6_addr);
#ifdef __APPLE__
        local.sin6_len = sizeof(local);
#endif
        if (bind(client, (struct sockaddr *)&local, sizeof(local)) < 0)
            goto fail;
    }
    destination.sin6_family = AF_INET6;
    destination.sin6_port = target.sin_port;
    inet_pton(AF_INET6, "::ffff:127.0.0.1", &destination.sin6_addr);
#ifdef __APPLE__
    destination.sin6_len = sizeof(destination);
#endif
    if (sendto(client, "ping", 4, 0, (struct sockaddr *)&destination, sizeof(destination)) < 0)
        goto fail;
    result = recvfrom(server, buffer, sizeof(buffer), 0, (struct sockaddr *)&peer, &peer_length);
    if (result < 0)
        goto fail;
    if (sendto(server, buffer, result, 0, (struct sockaddr *)&peer, peer_length) < 0)
        goto fail;
    memset(&received, 0xA5, sizeof(received));
    message.msg_name = &received;
    message.msg_namelen = sizeof(received);
    message.msg_iov = &iov;
    message.msg_iovlen = 1;
    result = recvmsg(client, &message, 0);
    if (result < 0)
        goto fail;
    if (((struct sockaddr *)&received)->sa_family == AF_INET)
        inet_ntop(AF_INET, &((struct sockaddr_in *)&received)->sin_addr, actual, sizeof(actual));
    else
        inet_ntop(AF_INET6, &received.sin6_addr, actual, sizeof(actual));
    inet_ntop(AF_INET6, &received.sin6_addr, assumed, sizeof(assumed));
    printf("mapped_bind=%d family=%d AF_INET=%d AF_INET6=%d name_length=%u bytes=%zd actual=%s assumed_ipv6=%s\n",
           mapped_bind, ((struct sockaddr *)&received)->sa_family, AF_INET, AF_INET6,
           (unsigned)message.msg_namelen, result, actual, assumed);
    goto done;
fail:
    printf("mapped_bind=%d error=%d %s\n", mapped_bind, errno, strerror(errno));
done:
    close(server);
    close(client);
}

int main(void)
{
    probe(0);
    probe(1);
    return 0;
}
