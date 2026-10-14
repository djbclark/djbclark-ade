/* LD_PRELOAD shim: rewrite bind(port 0) to a concrete random port.
 *
 * Works around libkrun TSI bug libkrun#818: a listener bound to port 0 lands on
 * a different port in the VMM's netns and is unreachable; fixed-port binds work.
 * Inherited by every child JVM through the environment.
 *
 * Also works around a second TSI bug: shutdown(2) on a listening socket either fails with ENOTCONN
 * or, while another thread is blocked in accept(), never returns (and so do getsockopt/getpeername then). Java's ServerSocket.close() (and so
 * okhttp's MockWebServer.shutdown()) calls it and hangs the test JVM forever. A shutdown() on a
 * listening socket is made a no-op here; close() still wakes a blocked accept() through the JDK's signal.
 *
 *   gcc -shared -fPIC -O2 -o /tmp/portshim.so loopback-port-shim.c -ldl
 *   LD_PRELOAD=/tmp/portshim.so ./gradlew ...
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <netinet/in.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

typedef int (*bind_fn)(int, const struct sockaddr *, socklen_t);

int bind(int fd, const struct sockaddr *addr, socklen_t len) {
    static bind_fn real;
    if (!real) real = (bind_fn)dlsym(RTLD_NEXT, "bind");
    if (!addr) return real(fd, addr, len);

    int zero = 0;
    if (addr->sa_family == AF_INET && len >= sizeof(struct sockaddr_in))
        zero = ((const struct sockaddr_in *)addr)->sin_port == 0;
    else if (addr->sa_family == AF_INET6 && len >= sizeof(struct sockaddr_in6))
        zero = ((const struct sockaddr_in6 *)addr)->sin6_port == 0;
    if (!zero) return real(fd, addr, len);

    union { struct sockaddr_storage ss; struct sockaddr_in a4; struct sockaddr_in6 a6; } copy;
    if (len > sizeof copy) return real(fd, addr, len);
    __builtin_memcpy(&copy, addr, len);
    unsigned seed = (unsigned)getpid() * 2654435761u ^ (unsigned)time(NULL) ^ (unsigned)fd;
    /* 20000-32000: below the kernel ephemeral range, so no clash with auto-assigned ports */
    for (int i = 0; i < 200; i++) {
        unsigned short port = (unsigned short)(20000 + rand_r(&seed) % 12000);
        if (copy.ss.ss_family == AF_INET) copy.a4.sin_port = htons(port);
        else copy.a6.sin6_port = htons(port);
        int rc = real(fd, (struct sockaddr *)&copy, len);
        if (rc == 0 || errno != EADDRINUSE) return rc;
    }
    return real(fd, addr, len);
}

/* shutdown() on a listener must not reach the kernel, and the shim cannot ask the socket whether it is a
 * listener: under TSI any call that takes the socket lock (getsockopt, getpeername, shutdown) blocks while
 * another thread sits in accept(). So listening fds are recorded in listen() and forgotten in close()/dup2(). */
#define MAXFD 65536
static volatile unsigned char listening[MAXFD];

typedef int (*listen_fn)(int, int);
int listen(int fd, int backlog) {
    static listen_fn real;
    if (!real) real = (listen_fn)dlsym(RTLD_NEXT, "listen");
    int rc = real(fd, backlog);
    if (rc == 0 && fd >= 0 && fd < MAXFD) listening[fd] = 1;
    return rc;
}

typedef int (*close_fn)(int);
int close(int fd) {
    static close_fn real;
    if (!real) real = (close_fn)dlsym(RTLD_NEXT, "close");
    if (fd >= 0 && fd < MAXFD) listening[fd] = 0;
    return real(fd);
}

typedef int (*dup2_fn)(int, int);
int dup2(int oldfd, int newfd) {
    static dup2_fn real;
    if (!real) real = (dup2_fn)dlsym(RTLD_NEXT, "dup2");
    if (newfd >= 0 && newfd < MAXFD) listening[newfd] = 0;
    return real(oldfd, newfd);
}

typedef int (*dup3_fn)(int, int, int);
int dup3(int oldfd, int newfd, int flags) {
    static dup3_fn real;
    if (!real) real = (dup3_fn)dlsym(RTLD_NEXT, "dup3");
    if (newfd >= 0 && newfd < MAXFD) listening[newfd] = 0;
    return real(oldfd, newfd, flags);
}

typedef int (*shutdown_fn)(int, int);
int shutdown(int fd, int how) {
    static shutdown_fn real;
    if (!real) real = (shutdown_fn)dlsym(RTLD_NEXT, "shutdown");
    if (fd >= 0 && fd < MAXFD && listening[fd]) return 0;
    return real(fd, how);
}
