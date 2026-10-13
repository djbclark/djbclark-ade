/* LD_PRELOAD shim: rewrite bind(port 0) to a concrete random port.
 *
 * Works around libkrun TSI bug libkrun#818: a listener bound to port 0 lands on
 * a different port in the VMM's netns and is unreachable; fixed-port binds work.
 * Inherited by every child JVM through the environment.
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
