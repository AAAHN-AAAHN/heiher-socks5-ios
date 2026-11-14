#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdlib.h>
#include <sys/socket.h>

/* Test-only syscall boundaries. Successful bytes still reach real sockets. */
ssize_t
send (int fd, const void *data, size_t length, int flags)
{
    static ssize_t (*real_send) (int, const void *, size_t, int);
    static unsigned int tcp_calls;
    static unsigned int udp_calls;
    int type;
    socklen_t type_length = sizeof (type);

    if (!real_send)
        real_send = dlsym (RTLD_NEXT, "send");
    /* Separate diagnostic mode: a real successful datagram, two dropped
     * attempts, then real successful recovery. No timing-dependent trigger. */
    if (getenv ("UDP_ECHO_SEND_STATE") &&
        getsockopt (fd, SOL_SOCKET, SO_TYPE, &type, &type_length) == 0 &&
        type == SOCK_DGRAM) {
        unsigned int call = ++udp_calls;
        if (call == 2 || call == 3) {
            errno = EMSGSIZE;
            return -1;
        }
    }
    if (getenv ("UDP_ECHO_IO_FAULTS") &&
        getsockopt (fd, SOL_SOCKET, SO_TYPE, &type, &type_length) == 0) {
        unsigned int call = type == SOCK_STREAM ? ++tcp_calls : ++udp_calls;
        if (call == 1) {
            errno = EINTR;
            return -1;
        }
        if (call == 2) {
            errno = EAGAIN;
            return -1;
        }
        if (type == SOCK_STREAM && length > 3)
            length = 3;
        if (type == SOCK_DGRAM && call == 3 && getenv ("UDP_ECHO_DROP_ONCE")) {
            errno = EMSGSIZE;
            return -1;
        }
    }
    return real_send (fd, data, length, flags);
}

ssize_t
recv (int fd, void *data, size_t length, int flags)
{
    static ssize_t (*real_recv) (int, void *, size_t, int);
    static unsigned int calls;
    static unsigned int udp_calls;
    int type;
    socklen_t type_length = sizeof (type);

    if (!real_recv)
        real_recv = dlsym (RTLD_NEXT, "recv");
    if (getenv ("UDP_ECHO_IO_FAULTS") &&
        getsockopt (fd, SOL_SOCKET, SO_TYPE, &type, &type_length) == 0) {
        if (type == SOCK_STREAM) {
            if (++calls == 1) {
                errno = EINTR;
                return -1;
            }
            if (length > 1)
                length = 1;
        } else if (++udp_calls == 1) {
            errno = ECONNREFUSED;
            return -1;
        }
    }
    return real_recv (fd, data, length, flags);
}

int
connect (int fd, const struct sockaddr *address, socklen_t length)
{
    static int (*real_connect) (int, const struct sockaddr *, socklen_t);
    int type;
    socklen_t type_length = sizeof (type);
    int result;

    if (!real_connect)
        real_connect = dlsym (RTLD_NEXT, "connect");
    result = real_connect (fd, address, length);
    if (result == 0 && getenv ("UDP_ECHO_IO_FAULTS") &&
        getsockopt (fd, SOL_SOCKET, SO_TYPE, &type, &type_length) == 0 &&
        type == SOCK_DGRAM) {
        errno = EINTR;
        return -1;
    }
    return result;
}
