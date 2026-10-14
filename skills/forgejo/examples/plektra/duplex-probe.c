/* duplex-probe.c: does send() on a TCP socket stall while ANOTHER thread is blocked in recv() on the same socket?
 * (full-duplex use: a WebSocket reader thread blocked in read() while a writer thread sends; okhttp does exactly this.)
 *
 * A normal kernel: the send goes out at once. libkrun TSI: see the result on forgejo.mit.edu's runner, 2026-10-14.
 *   gcc -O2 -pthread -o duplex-probe duplex-probe.c && ./duplex-probe
 * One line per case: how long until the data sent while the other thread was blocked in recv() reached the peer.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <poll.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1000.0 + t.tv_nsec / 1e6; }
static const char *reader = "recv";   /* how the parked thread waits: recv | poll | pollslice | nonblock */
static void *blocker(void *p) {   /* parked until the peer sends */
    int fd = *(int *)p; char b[8];
    if (!strcmp(reader, "recv")) recv(fd, b, sizeof b, 0);
    else if (!strcmp(reader, "poll")) { struct pollfd pf = {fd, POLLIN, 0}; poll(&pf, 1, -1); recv(fd, b, sizeof b, MSG_DONTWAIT); }
    else if (!strcmp(reader, "pollslice")) { struct pollfd pf = {fd, POLLIN, 0}; while (poll(&pf, 1, 20) == 0) ; recv(fd, b, sizeof b, MSG_DONTWAIT); }
    else { while (recv(fd, b, sizeof b, MSG_DONTWAIT) < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) usleep(5000); }
    return 0;
}
struct job { int fd; double t0; double sent_ms; int rc; };
static void *sender(void *p) { struct job *j = p; j->rc = send(j->fd, "hello", 5, 0); j->sent_ms = now() - j->t0; return 0; }

static int pair(int *c, int *s) {
    int l = socket(AF_INET, SOCK_STREAM, 0), one = 1; setsockopt(l, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    struct sockaddr_in a = {.sin_family = AF_INET, .sin_port = 0, .sin_addr.s_addr = htonl(0x7f000001)};
    int port = 31970 + rand() % 2000; a.sin_port = htons(port);
    if (bind(l, (void *)&a, sizeof a) || listen(l, 5)) return -1;
    *c = socket(AF_INET, SOCK_STREAM, 0);
    if (connect(*c, (void *)&a, sizeof a)) return -1;
    *s = accept(l, 0, 0); close(l); return 0;
}
/* blocked = the end whose recv() is parked in thread t; a second thread sends on that same end; main watches the peer. */
static void run(const char *label, int use_server_end) {
    int c, s; if (pair(&c, &s)) { printf("%s: setup failed (%s)\n", label, strerror(errno)); return; }
    int blocked = use_server_end ? s : c, other = use_server_end ? c : s;
    pthread_t t, w; pthread_create(&t, 0, blocker, &blocked); usleep(300000);     /* recv() is now parked in thread t */
    struct job j = {blocked, now(), -1, 0}; pthread_create(&w, 0, sender, &j);    /* send() while t sits in recv() */
    char b[16]; struct pollfd pf = {other, POLLIN, 0}; int n = poll(&pf, 1, 3000) > 0 ? recv(other, b, sizeof b, 0) : 0;   /* poll: SO_RCVTIMEO may not be honoured */
    double got = now() - j.t0;
    if (n > 0) printf("%-40s data reached the peer after %.0f ms (send took %.0f ms)\n", label, got, j.sent_ms);
    else { printf("%-40s peer received NOTHING in 3 s; send() %s   <== STALLED\n", label, j.sent_ms < 0 ? "has not returned" : "returned late"); 
    }
    send(other, "wake", 4, 0);                                                   /* release the parked recv() */
    pthread_join(t, 0); pthread_join(w, 0);
    if (n <= 0) printf("%-40s ...after the blocker was released, send() returned after %.0f ms (rc=%d)\n", "", j.sent_ms, j.rc);
    close(c); close(s);
}
int main(void) {
    setvbuf(stdout, 0, _IOLBF, 0); srand(getpid() ^ time(0));
    const char *modes[] = {"recv", "poll", "pollslice", "nonblock"};
    for (int i = 0; i < 4; i++) {
        reader = modes[i]; char l1[80], l2[80];
        snprintf(l1, sizeof l1, "reader=%-9s client end", reader); snprintf(l2, sizeof l2, "reader=%-9s accepted end", reader);
        run(l1, 0); run(l2, 1);
    }
    return 0;
}
