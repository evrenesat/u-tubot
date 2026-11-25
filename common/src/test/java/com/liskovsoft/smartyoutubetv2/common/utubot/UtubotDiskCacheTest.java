package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Flag;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Summary;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Verdict;

import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotDiskCacheTest {
    private static final String SCOPE = UtubotDiskCache.scopeOf("https://a.example", "token", "1.0");
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

    private static Verdict verdict(String id, String status) {
        Verdict verdict = new Verdict();
        verdict.videoId = id;
        verdict.status = status;
        verdict.action = UtubotModels.ACTION_MARK;
        verdict.markLabel = "Clickbait";
        verdict.titleQuestion = "Does it work?";
        verdict.answerShort = "Yes";
        verdict.insightReady = true;
        Flag flag = new Flag();
        flag.kind = "clickbait";
        flag.label = "Bait";
        flag.severity = 0.75;
        flag.reason = "The title promises more";
        verdict.flags = Collections.singletonList(flag);
        return verdict;
    }

    private static Summary summary(String id, String status, String text) {
        Summary summary = new Summary();
        summary.videoId = id;
        summary.status = status;
        summary.prompt = "builtin/tldr";
        summary.text = text;
        summary.source = "captions";
        return summary;
    }

    @Test
    public void aVerdictComesBackFieldForFieldAfterARestart() {
        mCache.putVerdicts(Collections.singletonList(verdict("aaaaaaaaaaa", "ready")));

        List<Verdict> stored = restart().loadVerdicts();

        assertEquals(1, stored.size());
        Verdict back = stored.get(0);
        assertEquals("aaaaaaaaaaa", back.videoId);
        assertEquals(UtubotModels.ACTION_MARK, back.action);
        assertEquals("Clickbait", back.markLabel);
        assertEquals("Does it work?", back.titleQuestion);
        assertEquals("Yes", back.answerShort);
        assertTrue(back.insightReady);
        assertFalse(back.captionsReady);
        assertEquals(1, back.flags.size());
        assertEquals("clickbait", back.flags.get(0).kind);
        assertEquals(0.75, back.flags.get(0).severity, 0.0001);
        assertEquals("The title promises more", back.flags.get(0).reason);
    }

    @Test
    public void onlyReadyVerdictsAreStored() {
        mCache.putVerdicts(java.util.Arrays.asList(verdict("aaaaaaaaaaa", "pending"), verdict("bbbbbbbbbbb", "failed"), verdict("ccccccccccc", "ready")));

        List<Verdict> stored = restart().loadVerdicts();

        assertEquals(1, stored.size());
        assertEquals("ccccccccccc", stored.get(0).videoId);
    }

    @Test
    public void anExpiredVerdictIsNotLoaded() {
        mCache.putVerdicts(Collections.singletonList(verdict("aaaaaaaaaaa", "ready")));

        mNow.addAndGet(UtubotDiskCache.TTL_MS + 1);

        assertTrue(restart().loadVerdicts().isEmpty());
    }

    @Test
    public void theOldestVerdictsAreDroppedBeyondTheLimit() {
        for (int i = 0; i < UtubotDiskCache.MAX_VERDICTS + 5; i++) {
            mCache.putVerdicts(Collections.singletonList(verdict(String.format("v%010d", i), "ready")));
        }

        List<Verdict> stored = restart().loadVerdicts();

        assertEquals(UtubotDiskCache.MAX_VERDICTS, stored.size());
        assertEquals(String.format("v%010d", 5), stored.get(0).videoId);
    }

    @Test
    public void anotherServerVersionTokenOrAddressStartsEmptyAndRemovesTheOldScope() {
        mCache.putVerdicts(Collections.singletonList(verdict("aaaaaaaaaaa", "ready")));
        mCache.putSummary("panel", summary("aaaaaaaaaaa", "ready", "- one"));
        String newVersion = UtubotDiskCache.scopeOf("https://a.example", "token", "1.1");
        assertNotEquals(SCOPE, newVersion);
        assertNotEquals(SCOPE, UtubotDiskCache.scopeOf("https://a.example", "other", "1.0"));
        assertNotEquals(SCOPE, UtubotDiskCache.scopeOf("https://b.example", "token", "1.0"));

        UtubotDiskCache updated = new UtubotDiskCache(mRoot, mNow::get);
        updated.useScope(newVersion);

        assertTrue(updated.loadVerdicts().isEmpty());
        assertNull(updated.getSummary("aaaaaaaaaaa", "panel"));
        assertFalse(new File(mRoot, SCOPE).exists());
    }

    @Test
    public void aReadySummaryComesBackAfterARestartPerPrompt() {
        mCache.putSummary("panel", summary("aaaaaaaaaaa", "ready", "- one"));

        UtubotDiskCache restarted = restart();
        Summary back = restarted.getSummary("aaaaaaaaaaa", "panel");

        assertNotNull(back);
        assertEquals("- one", back.text);
        assertEquals("builtin/tldr", back.prompt);
        assertEquals("captions", back.source);
        assertTrue(back.isReady());
        assertNull(restarted.getSummary("aaaaaaaaaaa", "builtin/tldr"));
        assertNull(restarted.getSummary("aaaaaaaaaaa", null));
    }

    @Test
    public void aFailurePendingJobOrTranscriptStateIsNeverStored() {
        mCache.putSummary("panel", summary("aaaaaaaaaaa", "failed", null));
        mCache.putSummary("panel", summary("bbbbbbbbbbb", "pending", null));
        Summary delayed = summary("ccccccccccc", "pending", null);
        delayed.transcriptStatus = UtubotModels.TRANSCRIPT_DELAYED;
        mCache.putSummary("panel", delayed);
        mCache.putSummary("panel", summary("ddddddddddd", "ready", ""));

        assertEquals(0, restart().summaryCount());
    }

    @Test
    public void anExpiredSummaryIsNotReturnedAndIsRemoved() {
        mCache.putSummary("panel", summary("aaaaaaaaaaa", "ready", "- one"));
        mNow.addAndGet(UtubotDiskCache.TTL_MS + 1);

        UtubotDiskCache restarted = restart();

        assertNull(restarted.getSummary("aaaaaaaaaaa", "panel"));
        assertEquals(0, restarted.summaryCount());
    }

    @Test
    public void clearingTheSummariesKeepsTheVerdicts() {
        mCache.putVerdicts(Collections.singletonList(verdict("aaaaaaaaaaa", "ready")));
        mCache.putSummary("panel", summary("aaaaaaaaaaa", "ready", "- one"));

        mCache.clearSummaries();

        assertNull(mCache.getSummary("aaaaaaaaaaa", "panel"));
        assertEquals(1, restart().loadVerdicts().size());
    }

    @Test
    public void clearingTheSummariesBeforeTheScopeIsOpenedClearsTheStoredOnes() {
        mCache.putSummary("panel", summary("aaaaaaaaaaa", "ready", "- one"));

        new UtubotDiskCache(mRoot, mNow::get).clearSummaries();

        assertNull(restart().getSummary("aaaaaaaaaaa", "panel"));
    }

    @Test
    public void clearingTheSummariesWhileAnotherScopeIsOpenClearsTheOneThatWillBeUsed() throws IOException {
        mCache.putSummary("panel", summary("aaaaaaaaaaa", "ready", "- one"));
        String other = UtubotDiskCache.scopeOf("https://b.example", "token", "1.0");
        File from = new File(new File(new File(mRoot, SCOPE), "summaries"), "aaaaaaaaaaa-" + UtubotDiskCache.promptHash("panel") + ".json");
        File to = new File(new File(mRoot, other), "summaries");
        assertTrue(to.mkdirs());
        Files.copy(from.toPath(), new File(to, from.getName()).toPath());

        mCache.clearSummaries();

        assertFalse(to.exists());
        assertNull(restart().getSummary("aaaaaaaaaaa", "panel"));
    }

    @Test
    public void aDamagedFileIsDroppedWithoutAnError() throws IOException {
        mCache.putVerdicts(Collections.singletonList(verdict("aaaaaaaaaaa", "ready")));
        mCache.putSummary("panel", summary("aaaaaaaaaaa", "ready", "- one"));
        Files.write(new File(new File(mRoot, SCOPE), "verdicts.json").toPath(), "{not json".getBytes(StandardCharsets.UTF_8));
        File[] summaries = new File(new File(mRoot, SCOPE), "summaries").listFiles();
        Files.write(summaries[0].toPath(), "[]".getBytes(StandardCharsets.UTF_8));

        UtubotDiskCache restarted = restart();

        assertTrue(restarted.loadVerdicts().isEmpty());
        assertNull(restarted.getSummary("aaaaaaaaaaa", "panel"));
    }

    @Test
    public void aVideoIdThatIsNotOneNeverBecomesAPath() {
        mCache.putSummary("panel", summary("../../etc/passwd", "ready", "- one"));

        assertEquals(0, mCache.summaryCount());
        assertNull(mCache.getSummary("../x", "panel"));
    }

    @Test
    public void theOldestSummariesAreDroppedBeyondTheLimit() {
        for (int i = 0; i < UtubotDiskCache.MAX_SUMMARIES + 3; i++) {
            mCache.putSummary("panel", summary(String.format("s%010d", i), "ready", "- text"));
            new File(new File(new File(mRoot, SCOPE), "summaries"), String.format("s%010d", i) + "-" + UtubotDiskCache.promptHash("panel") + ".json").setLastModified(1_000L + i);
        }

        assertEquals(UtubotDiskCache.MAX_SUMMARIES, mCache.summaryCount());
        assertNull(mCache.getSummary(String.format("s%010d", 0), "panel"));
        assertNotNull(mCache.getSummary(String.format("s%010d", UtubotDiskCache.MAX_SUMMARIES + 2), "panel"));
    }
}
