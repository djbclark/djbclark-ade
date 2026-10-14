import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import okhttp3.WebSocket;
import okhttp3.WebSocketListener;
import okhttp3.*;
import okhttp3.mockwebserver.*;

/** One MockWebServer per iteration + OkHttpClient to http://localhost:PORT/ (like the Plektra unit tests).
 *  Usage: java -cp ... Churn ITERATIONS THREADS [sharedClient|newClient] [get|post] [noShutdown] [sleepMs=N] [trace].
 *  noShutdown: never shut a server down (leak it); sleepMs: pause between iterations; trace: one line per iteration
 *  with the port and the start/request/shutdown phase times. A correct stack reports 0 errors. */
public class Churn {
    static class Done extends RuntimeException { Done() { super(null, null, false, false); } }
    public static void main(String[] a) throws Exception {
        int n = Integer.parseInt(a[0]), threads = Integer.parseInt(a[1]);
        boolean shared = a.length > 2 && a[2].equals("sharedClient"), post = a.length > 3 && a[3].equals("post");
        List<String> extra = Arrays.asList(a).subList(Math.min(a.length, 4), a.length);
        boolean noShutdown = extra.contains("noShutdown"), trace = extra.contains("trace"), ws = extra.contains("ws"); long sleepMs = 0;
        for (String e : extra) if (e.startsWith("sleepMs=")) sleepMs = Long.parseLong(e.substring(8));
        final long sleep = sleepMs; List<MockWebServer> leaked = Collections.synchronizedList(new ArrayList<>());
        OkHttpClient sharedClient = new OkHttpClient();
        AtomicInteger ok = new AtomicInteger(), done = new AtomicInteger();
        AtomicLong slowest = new AtomicLong();
        ConcurrentHashMap<String, AtomicInteger> errs = new ConcurrentHashMap<>();
        ExecutorService ex = Executors.newFixedThreadPool(threads);
        long t0 = System.currentTimeMillis();
        for (int t = 0; t < threads; t++) {
            ex.submit(() -> {
                for (int i = 0; i < n / threads; i++) {
                    String token = UUID.randomUUID().toString(); long it0 = System.nanoTime();
                    long ts = 0, tr = 0; int port = 0; String res = "ok";
                    MockWebServer s = new MockWebServer();
                    try {
                        if (ws) s.enqueue(new MockResponse().withWebSocketUpgrade(new WebSocketListener() {
                            @Override public void onMessage(WebSocket w, String text) { w.send("echo:" + text); }
                        }));
                        else s.enqueue(new MockResponse().setBody("{\"text\":\"" + token + "\"}"));
                        s.start(); port = s.getPort(); ts = (System.nanoTime() - it0) / 1_000_000;
                        OkHttpClient c = shared ? sharedClient : new OkHttpClient();
                        if (ws) {   // WebSocket round trip: send one text message, expect "echo:<token>" within 3 s
                            CountDownLatch got = new CountDownLatch(1); AtomicReference<String> msg = new AtomicReference<>(), fail = new AtomicReference<>();
                            WebSocket w = c.newWebSocket(new Request.Builder().url(s.url("/")).build(), new WebSocketListener() {
                                @Override public void onOpen(WebSocket x, Response r) { x.send(token); }
                                @Override public void onMessage(WebSocket x, String t) { msg.set(t); got.countDown(); }
                                @Override public void onFailure(WebSocket x, Throwable t, Response r) { fail.set(t.getClass().getSimpleName() + ": " + t.getMessage()); got.countDown(); }
                            });
                            boolean in = got.await(3, TimeUnit.SECONDS); tr = (System.nanoTime() - it0) / 1_000_000;
                            if (in && msg.get() != null && msg.get().contains(token)) ok.incrementAndGet();
                            else errs.computeIfAbsent(in ? "ws failure " + String.valueOf(fail.get()).replaceAll(":\\d+", ":PORT") : "ws TIMEOUT waiting 3 s for the echo", k -> new AtomicInteger()).incrementAndGet();
                            if (!in || fail.get() != null) res = "ERR ws " + (in ? "failure" : "timeout");
                            w.cancel();
                            throw new Done();
                        }
                        Request.Builder rb = new Request.Builder().url(s.url("/"));
                        if (post) rb.post(new MultipartBody.Builder().setType(MultipartBody.FORM)
                                .addFormDataPart("language", "de").addFormDataPart("file", "a.wav", RequestBody.create(MediaType.parse("audio/wav"), new byte[20000])).build());
                        try (Response r = c.newCall(rb.build()).execute()) {
                            String body = r.body().string(); tr = (System.nanoTime() - it0) / 1_000_000;
                            if (body.contains(token)) ok.incrementAndGet(); else errs.computeIfAbsent("wrong body " + body, k -> new AtomicInteger()).incrementAndGet();
                        }
                    } catch (Done d) { /* ws round trip finished */
                    } catch (Throwable e) {
                        res = "ERR " + e.getClass().getSimpleName();
                        errs.computeIfAbsent(e.getClass().getSimpleName() + ": " + String.valueOf(e.getMessage()).replaceAll(":\\d+", ":PORT"), k -> new AtomicInteger()).incrementAndGet();
                    }
                    long tq = (System.nanoTime() - it0) / 1_000_000;
                    if (noShutdown) leaked.add(s); else { try { s.shutdown(); } catch (Throwable e) { res += " shutdown:" + e.getClass().getSimpleName(); } }
                    long ms = (System.nanoTime() - it0) / 1_000_000;
                    if (trace) System.out.printf("iter port=%d %s start=%dms request_done=%dms before_shutdown=%dms total=%dms%n", port, res, ts, tr, tq, ms);
                    if (sleep > 0) { try { Thread.sleep(sleep); } catch (InterruptedException ie) {} }
                    slowest.accumulateAndGet(ms, Math::max);
                    int d = done.incrementAndGet();
                    if (d % 50 == 0) System.out.printf("progress %d/%d slowest_iteration=%dms errors_so_far=%d%n", d, n, slowest.get(), errs.values().stream().mapToInt(AtomicInteger::get).sum());
                }
            });
        }
        ex.shutdown();
        if (!ex.awaitTermination(600, TimeUnit.SECONDS)) System.out.println("TIMEOUT: workers still running");
        int total = errs.values().stream().mapToInt(AtomicInteger::get).sum();
        System.out.printf("threads=%d iterations=%d client=%s method=%s ok=%d errors=%d slowest_iteration=%dms secs=%.1f%n", threads, n, shared ? "shared" : "new", post ? "post" : "get", ok.get(), total, slowest.get(), (System.currentTimeMillis() - t0) / 1000.0);
        errs.forEach((k, v) -> System.out.println("  " + v + "  " + k));
        System.exit(total == 0 ? 0 : 1);
    }
}
