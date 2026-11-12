package com.liskovsoft.smartyoutubetv2.common.utubot;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * A minimal HTTP/1.1 server for the client tests: one answer per path prefix, one request per connection
 */
public final class TinyHttpServer {
    public interface Handler {
        Response handle(Request request) throws InterruptedException;
    }

    public static final class Request {
        public String method;
        public String path;
        public String query;
        public final Map<String, String> headers = new HashMap<>();
        public String body = "";
    }

    public static final class Response {
        public final int code;
        public final String body;

        public Response(int code, String body) {
            this.code = code;
            this.body = body;
        }
    }

    private final ServerSocket mSocket;
    private final Map<String, Handler> mHandlers = new ConcurrentHashMap<>();
    private volatile boolean mStopped;

    public TinyHttpServer() throws IOException {
        mSocket = new ServerSocket(0, 0, InetAddress.getByName("127.0.0.1"));
        Thread thread = new Thread(this::acceptLoop, "tiny-http");
        thread.setDaemon(true);
        thread.start();
    }

    public int getPort() {
        return mSocket.getLocalPort();
    }

    public void on(String pathPrefix, Handler handler) {
        mHandlers.put(pathPrefix, handler);
    }

    public void stop() {
        mStopped = true;

        try {
            mSocket.close();
        } catch (IOException ignored) {
        }
    }

    private void acceptLoop() {
        while (!mStopped) {
            try {
                Socket socket = mSocket.accept();
                Thread worker = new Thread(() -> serve(socket));
                worker.setDaemon(true);
                worker.start();
            } catch (IOException e) {
                return;
            }
        }
    }

    private void serve(Socket socket) {
        try (Socket s = socket) {
            BufferedReader in = new BufferedReader(new InputStreamReader(s.getInputStream(), StandardCharsets.UTF_8));
            Request request = new Request();
            String[] first = in.readLine().split(" ");
            request.method = first[0];
            int q = first[1].indexOf('?');
            request.path = q >= 0 ? first[1].substring(0, q) : first[1];
            request.query = q >= 0 ? first[1].substring(q + 1) : "";
            String line;

            while ((line = in.readLine()) != null && !line.isEmpty()) {
                int colon = line.indexOf(':');
                request.headers.put(line.substring(0, colon).trim().toLowerCase(), line.substring(colon + 1).trim());
            }

            int length = request.headers.containsKey("content-length") ? Integer.parseInt(request.headers.get("content-length")) : 0;
            char[] body = new char[length];
            int read = 0;

            while (read < length) {
                int count = in.read(body, read, length - read);

                if (count < 0) {
                    break;
                }

                read += count;
            }

            request.body = new String(body, 0, read);
            Response response = new Response(404, "{}");

            for (Map.Entry<String, Handler> entry : mHandlers.entrySet()) {
                if (request.path.startsWith(entry.getKey())) {
                    response = entry.getValue().handle(request);
                    break;
                }
            }

            byte[] bytes = response.body.getBytes(StandardCharsets.UTF_8);
            OutputStream out = s.getOutputStream();
            out.write(("HTTP/1.1 " + response.code + " X\r\nContent-Type: application/json\r\nContent-Length: " + bytes.length
                    + "\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.UTF_8));
            out.write(bytes);
            out.flush();
        } catch (IOException | InterruptedException ignored) {
        }
    }
}
