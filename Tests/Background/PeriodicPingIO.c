/* Controlled syscall boundary. This file is never linked into the application. */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static int tracked[4096], mode, opens, closes, calls, sent, reads, invalid;
static int destinations[256];
static double first, last;

int ping_probe_value(int key) {
    pthread_mutex_lock(&lock);
    int value = key == 0 ? opens : key == 1 ? closes : key == 2 ? calls :
        key == 3 ? sent : key == 4 ? reads : key == 5 ? invalid : destinations[key - 256];
    pthread_mutex_unlock(&lock);
    return value;
}
void ping_probe_mode(int value) {
    pthread_mutex_lock(&lock);
    mode = value;
    pthread_mutex_unlock(&lock);
}
double ping_probe_span(void) {
    pthread_mutex_lock(&lock);
    double value = last - first;
    pthread_mutex_unlock(&lock);
    return value;
}
int socket(int family, int type, int protocol) {
    int (*real_socket)(int, int, int) = dlsym(RTLD_NEXT, "socket");
    if (type != SOCK_DGRAM || (protocol != IPPROTO_ICMP && protocol != IPPROTO_ICMPV6))
        return real_socket(family, type, protocol);
    pthread_mutex_lock(&lock);
    if (mode == 1) { pthread_mutex_unlock(&lock); errno = EACCES; return -1; }
    int fd = open("/dev/null", O_RDWR);
    if (fd >= 0 && fd < 4096) { tracked[fd] = family; opens++; }
    pthread_mutex_unlock(&lock);
    return fd;
}
int close(int fd) {
    int (*real_close)(int) = dlsym(RTLD_NEXT, "close");
    pthread_mutex_lock(&lock);
    if (fd >= 0 && fd < 4096 && tracked[fd]) { tracked[fd] = 0; closes++; }
    pthread_mutex_unlock(&lock);
    return real_close(fd);
}
ssize_t recv(int fd, void *buffer, size_t length, int flags) {
    ssize_t (*real_recv)(int, void *, size_t, int) = dlsym(RTLD_NEXT, "recv");
    pthread_mutex_lock(&lock);
    if (fd >= 0 && fd < 4096 && tracked[fd]) {
        reads++;
        int flood = mode == 4;
        pthread_mutex_unlock(&lock);
        if (flood) { if (length) ((char *)buffer)[0] = 0; return length ? 1 : 0; }
        errno = EAGAIN;
        return -1;
    }
    pthread_mutex_unlock(&lock);
    return real_recv(fd, buffer, length, flags);
}
ssize_t sendto(int fd, const void *data, size_t count, int flags, const struct sockaddr *address, socklen_t length) {
    ssize_t (*real_sendto)(int, const void *, size_t, int, const struct sockaddr *, socklen_t) = dlsym(RTLD_NEXT, "sendto");
    pthread_mutex_lock(&lock);
    if (fd < 0 || fd >= 4096 || !tracked[fd]) {
        pthread_mutex_unlock(&lock);
        return real_sendto(fd, data, count, flags, address, length);
    }
    calls++;
    const uint8_t *bytes = data;
    int family = tracked[fd];
    if (count != 8 || bytes[1] != 0 || bytes[0] != (family == AF_INET ? 8 : 128) ||
        address->sa_family != family || !(flags & MSG_DONTWAIT) ||
        length != (family == AF_INET ? sizeof(struct sockaddr_in) : sizeof(struct sockaddr_in6))) invalid++;
    if (count == 8 && family == AF_INET) {
        uint32_t sum = 0;
        for (int i = 0; i < 8; i += 2) sum += bytes[i] * 256u + bytes[i + 1];
        while (sum > 65535) sum = (sum & 65535) + (sum >> 16);
        if (sum != 65535) invalid++;
    }
    int destination = family == AF_INET ? ntohl(((const struct sockaddr_in *)address)->sin_addr.s_addr) & 255 : 255;
    int failure = mode == 2 || (mode == 3 && destination == 2);
    if (!failure) { destinations[destination]++; sent++; }
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    double time = now.tv_sec + now.tv_nsec / 1e9;
    if (calls == 1) first = time;
    last = time;
    int partial = mode == 5;
    pthread_mutex_unlock(&lock);
    if (failure) { errno = EHOSTUNREACH; return -1; }
    return partial ? (ssize_t)count - 1 : (ssize_t)count;
}
