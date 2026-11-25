package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Verdict;

import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/**
 * The disk cache is opened for one connection. A switch while the old connection is still reading it must not publish the old scope
 * over the new one: the next request would then believe the new backend already has its cache open and never load it.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotDiskScopeRaceTest {
    private static final int WAIT_MS = 5000;
    @Rule
    public TemporaryFolder mFolder = new TemporaryFolder();
    private TinyHttpServer mServer;
    private Activity mActivity;
    private UtubotSettings mSettings;

    @Before
    public void start() throws IOException {
        mServer = new TinyHttpServer();
        mServer.on("/v1/health", request -> new TinyHttpServer.Response(200, "{\"ok\":true,\"version\":\"1.0\"}"));
        mActivity = Robolectric.buildActivity(Activity.class).setup().get();
        mSettings = UtubotSettings.instance(mActivity);
        mSettings.setUrl(backend());
        mSettings.setToken("old");
    }

    @After
    public void stop() {
        mSettings.setUrl("");
        mSettings.setToken("");
        mServer.stop();
    }

    private String backend() {
        return "http://127.0.0.1:" + mServer.getPort();
    }

    @Test
    public void aSwitchWhileTheDiskIsOpenedDoesNotPublishTheOldScope() throws Exception {
        BlockingDisk disk = new BlockingDisk(new File(mFolder.getRoot(), UtubotDiskCache.DIRECTORY));
        UtubotManager manager = new UtubotManager(mActivity, disk);
        AtomicBoolean opened = new AtomicBoolean(true);
        Thread opener = new Thread(() -> opened.set(manager.useDiskCache(manager.newClient())));
        opener.start();

        assertTrue("the old connection reached the disk", disk.mLoading.await(WAIT_MS, TimeUnit.MILLISECONDS));

        mSettings.setToken("new");
        disk.mMayLoad.countDown();

        opener.join(WAIT_MS);
        assertFalse("the old connection did not open the disk", opened.get());
        assertTrue("the new connection opens its own scope", manager.useDiskCache(manager.newClient()));
        assertEquals(Arrays.asList(UtubotDiskCache.scopeOf(backend(), "old", "1.0"),
                UtubotDiskCache.scopeOf(backend(), "new", "1.0")), disk.mScopes);
    }

    private static class BlockingDisk extends UtubotDiskCache {
        private final CountDownLatch mLoading = new CountDownLatch(1);
        private final CountDownLatch mMayLoad = new CountDownLatch(1);
        private final List<String> mScopes = Collections.synchronizedList(new ArrayList<>());

        BlockingDisk(File root) {
            super(root, System::currentTimeMillis);
        }

        @Override
        public synchronized void useScope(String scope) {
            mScopes.add(scope);
            super.useScope(scope);
        }

        @Override
        public synchronized List<Verdict> loadVerdicts() {
            mLoading.countDown();

            try {
                mMayLoad.await(WAIT_MS, TimeUnit.MILLISECONDS);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }

            return super.loadVerdicts();
        }
    }
}
