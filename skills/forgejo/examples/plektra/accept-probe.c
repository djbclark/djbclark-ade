/* accept-probe.c: what wakes a thread blocked in accept() on a loopback listener? Prints one line per case. */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>
#include <fcntl.h>
static volatile int done;
static void onsig(int s) { (void)s; }
static int fd_listen(int port) {
    int s = socket(AF_INET, SOCK_STREAM, 0), one = 1; setsockopt(s, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    struct sockaddr_in a = {.sin_family = AF_INET, .sin_port = htons(port), .sin_addr.s_addr = htonl(0x7f000001)};
    if (bind(s, (void *)&a, sizeof a) || listen(s, 5)) { perror("bind/listen"); return -1; }
    return s;
}
static void *acc(void *p) { int r = accept(*(int *)p, 0, 0); printf("   accept returned %d errno=%d (%s)\n", r, errno, strerror(errno)); fflush(stdout); done = 1; return 0; }
static int wait_done(int ms) { for (int i = 0; i < ms / 10 && !done; i++) usleep(10000); return done; }
int main(int c, char **v) {
    int mode = atoi(v[1]); int port = 31400 + mode; int s = fd_listen(port); pthread_t t;
    struct sigaction sa = {.sa_handler = onsig}; sigaction(SIGUSR1, &sa, 0);   /* no SA_RESTART */
    pthread_create(&t, 0, acc, &s); usleep(300000);
    const char *name[] = {"", "pthread_kill(SIGUSR1) only", "close(fd) only", "dup2(other,fd) then pthread_kill", "shutdown(fd,SHUT_RD)", "shutdown(fd,SHUT_RDWR)", "connect to self (wake with a connection)", "report SO_ACCEPTCONN and getpeername on the listener"};
    printf("CASE %d: %s\n", mode, name[mode]); fflush(stdout);
    if (mode == 1) pthread_kill(t, SIGUSR1);
    if (mode == 2) close(s);
    if (mode == 3) { int o = open("/dev/null", O_RDONLY); dup2(o, s); pthread_kill(t, SIGUSR1); }
    if (mode == 4) printf("   shutdown rc=%d errno=%d\n", shutdown(s, SHUT_RD), errno);
    if (mode == 5) printf("   shutdown rc=%d errno=%d\n", shutdown(s, SHUT_RDWR), errno);
    if (mode == 6) { int cs = socket(AF_INET, SOCK_STREAM, 0); struct sockaddr_in a = {.sin_family = AF_INET, .sin_port = htons(port), .sin_addr.s_addr = htonl(0x7f000001)}; printf("   connect rc=%d\n", connect(cs, (void *)&a, sizeof a)); }
    if (mode == 7) { int ac = -1; socklen_t l = sizeof ac; int r = getsockopt(s, SOL_SOCKET, SO_ACCEPTCONN, &ac, &l); struct sockaddr_in pa; socklen_t pl = sizeof pa; int pr = getpeername(s, (void *)&pa, &pl);
        printf("   getsockopt(SO_ACCEPTCONN) rc=%d value=%d; getpeername rc=%d errno=%d (%s)\n", r, ac, pr, errno, strerror(errno)); }
    fflush(stdout);
    printf("   RESULT case %d: %s\n", mode, wait_done(mode == 7 ? 10 : 3000) ? "accept woke" : "accept still blocked after 3 s");
    return 0;
}
