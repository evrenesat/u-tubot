package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import java.io.IOException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

/**
 * The record, WAV, upload pipeline of {@link UtubotSpeechInput} with a fake capture (no microphone)
 * and a loopback backend: the capture gets the length in milliseconds and runs off the calling
 * thread, the text or the error reaches the listener, and a cancelled call reports nothing.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotSpeechInputTest {
    private static final String TEXT = "Skip the sponsor.";
    private static final int SECONDS = 7;
    private static final int WAIT_S = 5;
    private TinyHttpServer mServer;
    private Context mContext;

    @Before
    public void start() throws IOException {
        mServer = new TinyHttpServer();
        mServer.on("/v1/speech", request -> new TinyHttpServer.Response(200, "{\"text\":\"" + TEXT + "\"}"));
        mContext = RuntimeEnvironment.getApplication();
    }

    @After
    public void stop() {
        mServer.stop();
    }

    private UtubotClient client() {
        return new UtubotClient("http://127.0.0.1:" + mServer.getPort() + "/", "token");
    }

    private static final class FakeCapture implements UtubotSpeechInput.Capture {
        final AtomicInteger requestedMs = new AtomicInteger();
        final AtomicReference<Thread> thread = new AtomicReference<>();
        final String error;

        FakeCapture(String error) {
            this.error = error;
        }

        @Override
        public void record(int maxDurationMs, Result result) {
            requestedMs.set(maxDurationMs);
            thread.set(Thread.currentThread());

            if (error != null) {
                result.onError(error);
            } else {
                result.onPcm(new short[]{100, -100, 100}, 16_000, 1);
            }
        }

        @Override
        public void stop() {
        }

        @Override
        public void cancel() {
        }
    }

    private static final class Recorder implements UtubotSpeechInput.Listener {
        final CountDownLatch done = new CountDownLatch(1);
        final AtomicReference<String> text = new AtomicReference<>();
        final AtomicReference<String> error = new AtomicReference<>();

        @Override
        public void onProgress(String message) {
        }

        @Override
        public void onText(String value) {
            text.set(value);
            done.countDown();
        }

        @Override
        public void onError(String message) {
            error.set(message);
            done.countDown();
        }
    }

    @Test
    public void itRecordsForTheRequestedSecondsOffTheCallingThreadAndReturnsTheText() throws InterruptedException {
        FakeCapture capture = new FakeCapture(null);
        Recorder listener = new Recorder();

        new UtubotSpeechInput(mContext, client(), capture).describe(null, SECONDS, listener);

        assertTrue(listener.done.await(WAIT_S, TimeUnit.SECONDS));
        assertEquals(TEXT, listener.text.get());
        assertEquals(SECONDS * 1000, capture.requestedMs.get());
        assertTrue(capture.thread.get() != Thread.currentThread());
    }

    @Test
    public void aCaptureErrorIsReportedToTheListener() throws InterruptedException {
        Recorder listener = new Recorder();

        new UtubotSpeechInput(mContext, client(), new FakeCapture(UtubotSpeechInput.ERROR_EMPTY)).describe(null, SECONDS, listener);

        assertTrue(listener.done.await(WAIT_S, TimeUnit.SECONDS));
        assertEquals(UtubotSpeechInput.ERROR_EMPTY, listener.error.get());
        assertNull(listener.text.get());
    }
}
