package com.liskovsoft.smartyoutubetv2.common.misc;

import com.liskovsoft.smartyoutubetv2.common.misc.GitHubReleases.Release;
import com.liskovsoft.smartyoutubetv2.common.utubot.TinyHttpServer;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.IOException;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

/**
 * Settings, Updates, Release notes over the wire: GitHub's list filtered by the tag prefix, and the changelog of the update channel
 * standing in for it when GitHub can't be reached
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class GitHubReleasesLoadTest {
    private static final String TAG_PREFIX = "utubot-v";
    private static final String GITHUB_RELEASES = "[" +
            "{\"tag_name\":\"v1.2.3\",\"body_html\":\"<p>Upstream</p>\"}," +
            "{\"tag_name\":\"utubot-v0.3.2\",\"html_url\":\"https://github.com/o/r/releases/tag/utubot-v0.3.2\",\"body_html\":\"<p>New</p>\"}," +
            "{\"tag_name\":\"32.68.3\",\"body_html\":\"<p>Upstream</p>\"}," +
            "{\"tag_name\":\"utubot-v0.3.1\",\"body_html\":\"<p>Old</p>\"}]";
    private static final String UPDATE_JSON = "{\"package\":{\"downloadUrlList\":[\"https://utubot.example.com/app/u-tubot.apk\"]}," +
            "\"0.3.1\":{\"versionCode\":3001,\"changelog\":[\"Older\"]}," +
            "\"0.3.2\":{\"versionCode\":3002,\"changelog\":[\"Newer\",\"Newest\"]}}";

    private TinyHttpServer mServer;
    private final AtomicReference<String> mAccept = new AtomicReference<>();
    private String mBase;

    @Before
    public void start() throws IOException {
        mServer = new TinyHttpServer();
        mServer.on("/github/releases", request -> {
            mAccept.set(request.headers.get("accept"));
            return new TinyHttpServer.Response(200, GITHUB_RELEASES);
        });
        mServer.on("/github/down", request -> new TinyHttpServer.Response(503, "{\"message\":\"unavailable\"}"));
        mServer.on("/github/limit", request -> new TinyHttpServer.Response(403, "{\"message\":\"API rate limit exceeded\"}"));
        mServer.on("/app/update.json", request -> new TinyHttpServer.Response(200, UPDATE_JSON));
        mBase = "http://127.0.0.1:" + mServer.getPort();
    }

    @After
    public void stop() {
        mServer.stop();
    }

    @Test
    public void load_listsOnlyTheReleasesWithTheTagPrefixNewestFirst() throws IOException {
        List<Release> releases = GitHubReleases.load(mBase + "/github/releases", TAG_PREFIX);

        assertEquals(2, releases.size());
        assertEquals("utubot-v0.3.2", releases.get(0).version);
        assertEquals("<p>New</p>", releases.get(0).bodyHtml);
        assertEquals("utubot-v0.3.1", releases.get(1).version);
        // GitHub renders the notes itself
        assertTrue(mAccept.get().contains("html"));
    }

    @Test
    public void load_failsWhenGitHubAnswersAnError() {
        assertFails(() -> GitHubReleases.load(mBase + "/github/down", TAG_PREFIX), "HTTP 503");
        assertFails(() -> GitHubReleases.load(mBase + "/github/limit", TAG_PREFIX), "HTTP 403");
    }

    @Test
    public void fallbackToUpdateChannel_listsTheChangelogOfTheChannel() throws IOException {
        IOException githubError = new IOException("HTTP 503");

        List<Release> releases = GitHubReleases.fallbackToUpdateChannel(mBase + "/app/update.json", githubError);

        assertEquals(2, releases.size());
        assertEquals("0.3.2", releases.get(0).version);
        assertEquals("<ul><li>Newer</li><li>Newest</li></ul>", releases.get(0).bodyHtml);
        assertEquals("0.3.1", releases.get(1).version);
        // The installed version is found in it too
        assertTrue(GitHubReleases.isInstalled(releases.get(0), "0.3.2", TAG_PREFIX));
    }

    @Test
    public void fallbackToUpdateChannel_theChannelFailsToo_githubsFailureIsTheResult() {
        IOException githubError = new IOException("HTTP 503");

        try {
            GitHubReleases.fallbackToUpdateChannel(mBase + "/nothing-here/update.json", githubError);
            fail("expected the failure of GitHub");
        } catch (IOException e) {
            assertSame(githubError, e);
        }
    }

    @Test
    public void fallbackToUpdateChannel_withoutAChannel_githubsFailureIsTheResult() {
        IOException githubError = new IOException("HTTP 503");

        for (String none : new String[] {null, ""}) {
            try {
                GitHubReleases.fallbackToUpdateChannel(none, githubError);
                fail("expected the failure of GitHub");
            } catch (IOException e) {
                assertSame(githubError, e);
            }
        }
    }

    private interface Load {
        void run() throws IOException;
    }

    private static void assertFails(Load load, String message) {
        try {
            load.run();
            fail("expected " + message);
        } catch (IOException e) {
            assertEquals(message, e.getMessage());
        }
    }
}
