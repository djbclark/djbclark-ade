import java.net.*; import java.io.*;
// A client socket with another thread blocked in read(); close it from the main thread (okhttp WebSocket.cancel).
public class Sd3 { public static void main(String[] a) throws Exception {
  int port = Integer.parseInt(a[0]);
  ServerSocket srv = new ServerSocket(port);
  Thread acc = new Thread(() -> { try { Socket c = srv.accept(); Thread.sleep(60000); c.close(); } catch (Exception e) {} }); acc.setDaemon(true); acc.start();
  Socket cl = new Socket("127.0.0.1", port);
  Thread rd = new Thread(() -> { try { cl.getInputStream().read(); System.out.println("read returned"); } catch (Exception e) { System.out.println("read ended: " + e); } }); rd.setDaemon(true); rd.start();
  Thread.sleep(500);
  long t0 = System.nanoTime(); cl.close(); System.out.println("client Socket.close returned after " + (System.nanoTime() - t0) / 1000000 + " ms");
  Thread.sleep(300); System.out.println("done"); System.exit(0); } }
