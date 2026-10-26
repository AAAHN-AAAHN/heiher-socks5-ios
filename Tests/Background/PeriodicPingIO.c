/* Controlled native API boundary. Never linked into the application. */
#define _GNU_SOURCE
#include "hev-main.h"
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

struct _HevSocks5IcmpClient {
    uint64_t generation, epoch;
    HevSocks5IcmpCallback callback;
    void *context;
    int active, closing;
};
typedef struct Request Request;
struct Request {
    Request *next;
    HevSocks5IcmpClient *client;
    uint64_t id, epoch;
    struct sockaddr_storage target;
    socklen_t length;
};
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed = PTHREAD_COND_INITIALIZER;
static pthread_once_t worker_once = PTHREAD_ONCE_INIT;
static Request *head, **tail = &head;
static uint64_t generation = 1, serial = 1;
static int mode, opens, closes, calls, sent, events, invalid, queued, peak;
static int cancellations, submission_entered, destinations[256];
static int budget = -1, last_destination = -1;
static double first, last;

static void emit(Request *request, int event, int error) {
    HevSocks5IcmpResult result = { 0 };
    result.request_id = request->id;
    result.event = event;
    result.error = error;
    result.destination = request->target;
    result.destination_len = request->length;
    result.source = request->target;
    result.source_len = request->length;
    request->client->callback(&result, request->client->context);
    pthread_mutex_lock(&lock);
    events++;
    pthread_mutex_unlock(&lock);
}

static void *worker(void *unused) {
    (void)unused;
    for (;;) {
        pthread_mutex_lock(&lock);
        while (!head || mode == 6) pthread_cond_wait(&changed, &lock);
        Request *request = head;
        head = request->next;
        if (!head) tail = &head;
        queued--;
        HevSocks5IcmpClient *client = request->client;
        client->active++;
        int state = mode;
        int destination = request->target.ss_family == AF_INET ?
            ntohl(((struct sockaddr_in *)&request->target)->sin_addr.s_addr) & 255 : 255;
        int error = client->closing || client->epoch != request->epoch ? ECANCELED :
            client->generation != generation || !generation ? ENETDOWN :
            state == 5 ? EIO : state == 3 && destination == 2 ? EHOSTUNREACH : 0;
        if (!error) {
            destinations[destination]++;
            last_destination = request->target.ss_family == AF_INET ?
                (int)(ntohl(((struct sockaddr_in *)&request->target)->sin_addr.s_addr) & 65535) : -1;
            sent++;
            struct timespec now;
            clock_gettime(CLOCK_MONOTONIC, &now);
            double time = now.tv_sec + now.tv_nsec / 1e9;
            if (sent == 1) first = time;
            last = time;
        }
        pthread_mutex_unlock(&lock);
        emit(request, error ? HEV_SOCKS5_ICMP_ERROR : HEV_SOCKS5_ICMP_SENT, error);
        if (!error) {
            if (state == 9) emit(request, HEV_SOCKS5_ICMP_SENT, 0);
            emit(request, state == 8 ? HEV_SOCKS5_ICMP_ERROR : HEV_SOCKS5_ICMP_REPLY,
                 state == 8 ? ETIMEDOUT : 0);
        }
        pthread_mutex_lock(&lock);
        client->active--;
        pthread_cond_broadcast(&changed);
        pthread_mutex_unlock(&lock);
        free(request);
    }
    return NULL;
}

static void start_worker(void) {
    pthread_t thread;
    if (pthread_create(&thread, NULL, worker, NULL) || pthread_detach(thread)) abort();
}

uint64_t hev_socks5_server_icmp_generation(void) {
    pthread_mutex_lock(&lock);
    uint64_t value = generation;
    pthread_mutex_unlock(&lock);
    return value;
}

HevSocks5IcmpClient *hev_socks5_server_icmp_client_new(
    uint64_t expected, HevSocks5IcmpCallback callback, void *context) {
    pthread_mutex_lock(&lock);
    if (!expected || expected != generation || mode == 1) {
        int error = mode == 1 ? EACCES : ENETDOWN;
        pthread_mutex_unlock(&lock);
        errno = error;
        return NULL;
    }
    HevSocks5IcmpClient *client = calloc(1, sizeof(*client));
    if (client) {
        client->generation = expected;
        client->callback = callback;
        client->context = context;
        opens++;
    }
    pthread_mutex_unlock(&lock);
    if (client) pthread_once(&worker_once, start_worker);
    return client;
}

int hev_socks5_server_icmp_ping(HevSocks5IcmpClient *client, uint64_t id,
    const struct sockaddr *target, socklen_t length, uint32_t timeout_ms) {
    pthread_mutex_lock(&lock);
    calls++;
    if (mode == 7) {
        submission_entered++;
        pthread_cond_broadcast(&changed);
        while (mode == 7) pthread_cond_wait(&changed, &lock);
    }
    if (!client || client->closing || client->generation != generation || !generation) {
        pthread_mutex_unlock(&lock);
        return -ENETDOWN;
    }
    if (!target || (target->sa_family != AF_INET && target->sa_family != AF_INET6) ||
        length != (target->sa_family == AF_INET ? sizeof(struct sockaddr_in) : sizeof(struct sockaddr_in6)) ||
        timeout_ms != 1000 || !id) {
        invalid++;
        pthread_mutex_unlock(&lock);
        return -EINVAL;
    }
    if (mode == 2 || mode == 4 || queued == 4096 || budget == 0) {
        int error = mode == 2 ? EHOSTUNREACH : EAGAIN;
        pthread_mutex_unlock(&lock);
        return -error;
    }
    Request *request = calloc(1, sizeof(*request));
    if (!request) { pthread_mutex_unlock(&lock); return -ENOMEM; }
    request->client = client;
    request->id = id;
    request->epoch = client->epoch;
    request->length = length;
    memcpy(&request->target, target, length);
    if (budget > 0) budget--;
    *tail = request;
    tail = &request->next;
    if (++queued > peak) peak = queued;
    pthread_cond_broadcast(&changed);
    pthread_mutex_unlock(&lock);
    return 0;
}

static void discard_queued(HevSocks5IcmpClient *client) {
    Request **slot = &head;
    while (*slot) {
        Request *request = *slot;
        if (request->client == client) {
            *slot = request->next;
            queued--;
            free(request);
        } else slot = &request->next;
    }
    tail = slot;
}

void hev_socks5_server_icmp_cancel(HevSocks5IcmpClient *client) {
    pthread_mutex_lock(&lock);
    client->epoch++;
    cancellations++;
    discard_queued(client);
    pthread_cond_broadcast(&changed);
    pthread_mutex_unlock(&lock);
}

void hev_socks5_server_icmp_client_free(HevSocks5IcmpClient *client) {
    pthread_mutex_lock(&lock);
    client->closing = 1;
    discard_queued(client);
    while (client->active) pthread_cond_wait(&changed, &lock);
    closes++;
    pthread_mutex_unlock(&lock);
    free(client);
}

int ping_probe_value(int key) {
    pthread_mutex_lock(&lock);
    int value = key == 0 ? opens : key == 1 ? closes : key == 2 ? calls :
        key == 3 ? sent : key == 4 ? events : key == 5 ? invalid : key == 6 ? peak :
        key == 7 ? cancellations : key == 8 ? queued : key == 10 ? submission_entered :
        key == 11 ? last_destination :
        key >= 256 && key < 512 ? destinations[key - 256] : -1;
    pthread_mutex_unlock(&lock);
    return value;
}

void ping_probe_mode(int value) {
    pthread_mutex_lock(&lock);
    mode = value;
    pthread_cond_broadcast(&changed);
    pthread_mutex_unlock(&lock);
}

void ping_probe_budget(int value) {
    pthread_mutex_lock(&lock);
    budget = value;
    pthread_mutex_unlock(&lock);
}

void ping_probe_server(int enabled) {
    pthread_mutex_lock(&lock);
    generation = enabled ? ++serial : 0;
    pthread_cond_broadcast(&changed);
    pthread_mutex_unlock(&lock);
}

double ping_probe_span(void) {
    pthread_mutex_lock(&lock);
    double value = last - first;
    pthread_mutex_unlock(&lock);
    return value;
}

/* A regression to direct Swift ICMP I/O must fail instead of passing the mock. */
int socket(int family, int type, int protocol) {
    int (*real_socket)(int, int, int) = dlsym(RTLD_NEXT, "socket");
    if (protocol != IPPROTO_ICMP && protocol != IPPROTO_ICMPV6)
        return real_socket(family, type, protocol);
    pthread_mutex_lock(&lock);
    invalid++;
    pthread_mutex_unlock(&lock);
    errno = EPERM;
    return -1;
}
