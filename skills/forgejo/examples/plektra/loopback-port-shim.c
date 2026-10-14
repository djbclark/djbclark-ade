/* LD_PRELOAD shim: rewrite bind(port 0) to a concrete random port.
 *
 * Works around libkrun TSI bug libkrun#818: a listener bound to port 0 lands on
 * a different port in the VMM's netns and is unreachable; fixed-port binds work.
 * Inherited by every child JVM through the environment.
 *
 * Also works around a second TSI bug: shutdown(2) on a listening socket either fails with ENOTCONN
 * or, while another thread is blocked in accept(), never returns (getpeername blocks too, and getsockopt(SO_ACCEPTCONN) wrongly says 0). Java's ServerSocket.close() (and so
 * okhttp's MockWebServer.shutdown()) calls it and hangs the test JVM forever. A shutdown() on a
 * listening socket is made a no-op here; close() still wakes a blocked accept() through the JDK's signal.
 *
 *   gcc -shared -fPIC -O2 -pthread -o /tmp/portshim.so loopback-port-shim.c -ldl
 *   LD_PRELOAD=/tmp/portshim.so ./gradlew ...
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <netinet/in.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#define RECENT 4096   /* ports not handed out again by this process until 4096 others were */
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
    /* Never hand out the same port twice in a row: under TSI a listener that was just closed is still alive for a
     * moment on the host side, and a new listener on the same port number is accepted by bind() (no EADDRINUSE) but
     * its connections land on the dying one (EOF, "unexpected end of stream"; verified 2026-10-14, run 220: every
     * failure had port == previous port). So ports come from a high-resolution seed (the old pid^time(s)^fd seed
     * repeated within a second, i.e. the same port for every test of that second) and skip the last RECENT ports. */
    static pthread_mutex_t pm = PTHREAD_MUTEX_INITIALIZER;
    static unsigned short recent[RECENT]; static unsigned nrecent;
    static unsigned long long ctr;
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    unsigned long long z = (unsigned long long)ts.tv_nsec ^ ((unsigned long long)ts.tv_sec << 30) ^ ((unsigned long long)getpid() << 17) ^ (++ctr * 0x9E3779B97F4A7C15ull);
    z ^= z >> 30; z *= 0xBF58476D1CE4E5B9ull; z ^= z >> 27; z *= 0x94D049BB133111EBull; z ^= z >> 31;
    unsigned seed = (unsigned)z;
    /* 20000-32000: below the kernel ephemeral range, so no clash with auto-assigned ports */
    for (int i = 0; i < 400; i++) {
        unsigned short port = (unsigned short)(20000 + rand_r(&seed) % 12000);
        int seen = 0;
        pthread_mutex_lock(&pm);
        for (unsigned k = 0; k < RECENT && k < nrecent; k++) if (recent[k] == port) { seen = 1; break; }
        pthread_mutex_unlock(&pm);
        if (seen) continue;
        if (copy.ss.ss_family == AF_INET) copy.a4.sin_port = htons(port);
        else copy.a6.sin6_port = htons(port);
        int rc = real(fd, (struct sockaddr *)&copy, len);
        if (rc == 0) { pthread_mutex_lock(&pm); recent[nrecent++ % RECENT] = port; pthread_mutex_unlock(&pm); }
        if (rc == 0 || errno != EADDRINUSE) return rc;
    }
    return real(fd, addr, len);
}

/* shutdown() on a listener must not reach the kernel, and the shim cannot ask the socket whether it is a
 * listener: under TSI getsockopt(SO_ACCEPTCONN) answers 0 for a listener, and getpeername and shutdown block while
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
static shutdown_fn real_shutdown;

/* Any other socket: under TSI, shutdown() also blocks while another thread sits in a blocking read() or
 * connect() on it (okhttp's WebSocket reader; Socket.close() calls shutdown first). Run the real call in a
 * helper thread and give up waiting after 300 ms; the helper is then already inside the kernel, so the later
 * close() cannot race with fd reuse, and the JDK's dup2+signal wakes the blocked reader as usual. */
struct sd { int fd, how, rc, err, done, refs; pthread_mutex_t m; pthread_cond_t c; };

static void *sd_thread(void *p) {
    struct sd *a = p;
    int rc = real_shutdown(a->fd, a->how), e = errno;
    pthread_mutex_lock(&a->m);
    a->rc = rc; a->err = e; a->done = 1; pthread_cond_signal(&a->c);
    int last = --a->refs == 0;
    pthread_mutex_unlock(&a->m);
    if (last) free(a);
    return 0;
}

int shutdown(int fd, int how) {
    if (!real_shutdown) real_shutdown = (shutdown_fn)dlsym(RTLD_NEXT, "shutdown");
    if (fd >= 0 && fd < MAXFD && listening[fd]) return 0;
    static int mode = -1;   /* SHIM_SHUTDOWN: async (default) | passthrough | noop, for experiments */
    if (mode < 0) { const char *e = getenv("SHIM_SHUTDOWN"); mode = !e ? 0 : !strcmp(e, "passthrough") ? 1 : !strcmp(e, "noop") ? 2 : 0; }
    if (mode == 1) return real_shutdown(fd, how);
    if (mode == 2) return 0;
    struct sd *a = calloc(1, sizeof *a);
    pthread_t t;
    if (!a) return real_shutdown(fd, how);
    a->fd = fd; a->how = how; a->refs = 2;
    pthread_mutex_init(&a->m, 0); pthread_cond_init(&a->c, 0);
    if (pthread_create(&t, 0, sd_thread, a)) { free(a); return real_shutdown(fd, how); }
    pthread_detach(t);
    struct timespec dl; clock_gettime(CLOCK_REALTIME, &dl);
    dl.tv_nsec += 300 * 1000000L; if (dl.tv_nsec >= 1000000000L) { dl.tv_sec++; dl.tv_nsec -= 1000000000L; }
    int rc = 0, e = 0;
    pthread_mutex_lock(&a->m);
    while (!a->done && pthread_cond_timedwait(&a->c, &a->m, &dl) == 0) ;
    if (a->done) { rc = a->rc; e = a->err; }
    int last = --a->refs == 0;
    pthread_mutex_unlock(&a->m);
    if (last) free(a);
    if (rc) { errno = e; return rc; }
    return 0;
}
