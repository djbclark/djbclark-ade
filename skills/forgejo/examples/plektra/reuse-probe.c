/* reuse-probe.c: after a listener is closed while another thread is blocked in accept() on it (what the JDK and so
 * okhttp's MockWebServer.shutdown() do), does a NEW listener on the same port get its connections?
 *
 * A normal kernel: yes, always. libkrun TSI (verified on forgejo.mit.edu's runner, 2026-10-14): the new listener's
 * bind()+listen() succeed but the connection is delivered to the old, dying listener, so the client sees EOF or a reset.
 *
 *   gcc -O2 -pthread -o reuse-probe reuse-probe.c && ./reuse-probe [rounds] [gap_ms] [wake]
 *   wake: jdk (default; dup2 /dev/null over the fd, then pthread_kill SIGUSR1, as the JDK does), close (plain close),
 *         none (nobody was blocked in accept: the accepting thread already returned)
 * Prints one summary line: rounds where the client got its echo, EOF/reset, timed out.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static int trace;
#define T(...) do { if (trace) { fprintf(stderr, __VA_ARGS__); fputc(10, stderr); } } while (0)
static void onsig(int s) { (void)s; }
static int make_listener(int port) {
    int s = socket(AF_INET, SOCK_STREAM, 0), one = 1;
    setsockopt(s, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);   /* the JDK's default for ServerSocket on Linux */
    struct sockaddr_in a = {.sin_family = AF_INET, .sin_port = htons(port), .sin_addr.s_addr = htonl(0x7f000001)};
    if (bind(s, (void *)&a, sizeof a) || listen(s, 50)) { perror("bind/listen"); exit(2); }
    return s;
}
static void *acc_old(void *p) { accept(*(int *)p, 0, 0); return 0; }   /* blocks until woken; never answers */
static void *acc_new(void *p) {
    int c = accept(*(int *)p, 0, 0);
    if (c >= 0) { char b[16]; int n = read(c, b, sizeof b); if (n > 0) write(c, b, n); close(c); }
    return 0;
}
int main(int argc, char **argv) {
    setvbuf(stdout, 0, _IOLBF, 0);
    int rounds = argc > 1 ? atoi(argv[1]) : 200, gap = argc > 2 ? atoi(argv[2]) : 0; const char *wake = argc > 3 ? argv[3] : "jdk";
    trace = getenv("REUSE_TRACE") != 0; int port = 31960, ok = 0, eof = 0, timeout = 0, other = 0;
    struct sigaction sa = {.sa_handler = onsig}; sigaction(SIGUSR1, &sa, 0);   /* no SA_RESTART */
    for (int i = 0; i < rounds; i++) {
        T("round %d: listen l1", i); int l1 = make_listener(port); pthread_t t1;
        int blocked = strcmp(wake, "none");
        if (blocked) { pthread_create(&t1, 0, acc_old, &l1); usleep(20000); }
        T("round %d: waking old accept (%s)", i, wake);
        if (!strcmp(wake, "close")) close(l1);
        else if (!strcmp(wake, "jdk")) { int z = open("/dev/null", O_RDONLY); dup2(z, l1); close(z); pthread_kill(t1, SIGUSR1); T("round %d: signalled, joining old accept thread", i); pthread_join(t1, 0); T("round %d: old accept thread returned", i); close(l1); }
        else close(l1);                       /* none */
        if (blocked && !strcmp(wake, "close")) usleep(1000);
        if (gap) usleep(gap * 1000);
        T("round %d: listen l2 on the same port", i); int l2 = make_listener(port); pthread_t t2; pthread_create(&t2, 0, acc_new, &l2);
        int c = socket(AF_INET, SOCK_STREAM, 0);
        struct sockaddr_in a = {.sin_family = AF_INET, .sin_port = htons(port), .sin_addr.s_addr = htonl(0x7f000001)};
        T("round %d: connect", i); if (connect(c, (void *)&a, sizeof a)) { other++; close(c); goto next; }
        T("round %d: connected, send+wait", i); write(c, "ping\n", 5); char b[16]; struct pollfd pf = {c, POLLIN, 0};
        if (poll(&pf, 1, 2000) == 0) timeout++;   /* poll, not SO_RCVTIMEO: TSI does not honour it */
        else { int n = read(c, b, sizeof b); if (n > 0) ok++; else eof++; }
        close(c);
    next:
        if (ok + eof + timeout + other < i + 1) other++;
        /* wake and reap the new accept thread if it is still blocked, then close l2 the same way */
        T("round %d: cleanup l2", i);
        { int z = open("/dev/null", O_RDONLY); dup2(z, l2); close(z); pthread_kill(t2, SIGUSR1); pthread_join(t2, 0); close(l2); }
    }
    printf("wake=%s gap=%dms rounds=%d echoed=%d eof_or_reset=%d timeout=%d connect_failed=%d\n", wake, gap, rounds, ok, eof, timeout, other);
    return ok == rounds ? 0 : 1;
}
