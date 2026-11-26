package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotDiskCache.CutListCache;

import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.File;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

/**
 * The cut lists of earlier sessions, kept on the TV so the menu can show one at once when the server is
 * slow or down. Only a configured list is stored; an expired or damaged one is dropped.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotCutsDiskCacheTest {
    private static final String SCOPE = UtubotDiskCache.scopeOf("https://a.example", "token", "1.0");
    private static final String VIDEO = "aaaaaaaaaaa";
    private static final String OTHER = "bbbbbbbbbbb";
    private static final String ETAG = "\"v1\"";
    @Rule
    public TemporaryFolder mFolder = new TemporaryFolder();
    private final AtomicLong mNow = new AtomicLong(1_000_000);
    private File mRoot;
    private UtubotDiskCache mCache;

    @Before
    public void setUp() {
        mRoot = new File(mFolder.getRoot(), UtubotDiskCache.DIRECTORY);
        mCache = new UtubotDiskCache(mRoot, mNow::get);
        mCache.useScope(SCOPE);
    }

    private UtubotDiskCache restart() {
        UtubotDiskCache cache = new UtubotDiskCache(mRoot, mNow::get);
        cache.useScope(SCOPE);
        return cache;
    }

    private static String cutList(String videoId) {
        return "{\"configured\":true,\"default_mode\":\"quick\",\"presets\":" + presets(videoId) + "}";
    }

    private static String presets(String videoId) {
        return "[{\"id\":\"cut-no-filler\",\"label\":\"No filler\",\"state\":\"ready\",\"cut\":" + cut(videoId) + "},"
                + "{\"id\":\"cut-answer\",\"label\":\"Just the answer\",\"state\":\"none\"}]";
    }

    private static String cut(String videoId) {
        return "{\"version\":1,\"video_id\":\"" + videoId + "\",\"transcript_hash\":\"t\",\"duration_ms\":240000,"
                + "\"label\":\"No filler\",\"summary\":\"s\",\"parts\":[{\"label\":\"Start\",\"start_ms\":0,\"end_ms\":60000}],"
                + "\"skip_ranges_ms\":[[60000,108000]],\"kept_ms\":192000,\"source\":\"youtube_captions\",\"preset_id\":\"cut-no-filler\",\"mode\":\"quick\"}";
    }

    @Test
    public void aCutListComesBackWithItsEtagAfterARestart() {
        mCache.putCuts(VIDEO, ETAG, cutList(VIDEO));

        CutListCache back = restart().getCuts(VIDEO);

        assertNotNull(back);
        assertEquals(ETAG, back.etag);
        assertEquals(VIDEO, back.videoId);
        assertTrue(back.cuts.configured);
        assertEquals("quick", back.cuts.defaultMode);
        assertEquals(2, back.cuts.presets.size());
        assertEquals("ready", back.cuts.presets.get(0).state);
    }

    @Test
    public void everyCutListIsStoredAndLoadedSeparately() {
        mCache.putCuts(VIDEO, "\"a\"", cutList(VIDEO));
        mCache.putCuts(OTHER, "\"b\"", cutList(OTHER));

        List<CutListCache> all = restart().loadCuts();

        assertEquals(2, all.size());
        assertNotNull(restart().getCuts(VIDEO));
        assertNotNull(restart().getCuts(OTHER));
    }

    @Test
    public void anExpiredCutListIsNotReturned() {
        mCache.putCuts(VIDEO, ETAG, cutList(VIDEO));
        mNow.addAndGet(UtubotDiskCache.TTL_MS + 1);

        UtubotDiskCache restarted = restart();

        assertNull(restarted.getCuts(VIDEO));
        assertTrue(restarted.loadCuts().isEmpty());
    }

    @Test
    public void theDamagedCutListIsDroppedWithoutAnError() {
        mCache.putCuts(VIDEO, ETAG, cutList(VIDEO));
        File file = new File(new File(new File(mRoot, SCOPE), "cuts"), VIDEO + ".json");
        file.delete();

        mCache.putCuts(VIDEO, ETAG, "{not json");

        assertNull(restart().getCuts(VIDEO));
    }

    @Test
    public void theOldestCutListsAreDroppedBeyondTheLimit() {
        for (int i = 0; i < UtubotDiskCache.MAX_CUTS + 4; i++) {
            String id = String.format("v%010d", i);
            String etag = "\"" + i + "\"";
            mCache.putCuts(id, etag, cutList(id));
            new File(new File(new File(mRoot, SCOPE), "cuts"), id + ".json").setLastModified(1_000L + i);
        }

        assertEquals(UtubotDiskCache.MAX_CUTS, restart().loadCuts().size());
    }

    @Test
    public void clearingTheCutsRemovesEveryScope() {
        mCache.putCuts(VIDEO, ETAG, cutList(VIDEO));
        String other = UtubotDiskCache.scopeOf("https://b.example", "token", "1.0");
        mCache.useScope(other);
        mCache.putCuts(VIDEO, ETAG, cutList(VIDEO));

        mCache.clearCuts();

        new UtubotDiskCache(mRoot, mNow::get).useScope(SCOPE);
        assertNull(restart().getCuts(VIDEO));

        new UtubotDiskCache(mRoot, mNow::get).useScope(other);
        File otherCuts = new File(new File(mRoot, other), "cuts");

        assertTrue(otherCuts.listFiles() == null || otherCuts.listFiles().length == 0);
    }

    @Test
    public void aVideoIdThatIsNotOneNeverBecomesAPath() {
        mCache.putCuts("../../etc/passwd", ETAG, cutList("x"));

        assertTrue(restart().loadCuts().isEmpty());
        assertNull(restart().getCuts("../x"));
    }
}
