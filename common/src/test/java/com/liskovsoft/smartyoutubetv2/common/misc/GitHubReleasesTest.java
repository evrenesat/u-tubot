package com.liskovsoft.smartyoutubetv2.common.misc;

import com.liskovsoft.smartyoutubetv2.common.misc.GitHubReleases.Release;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.IOException;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class GitHubReleasesTest {
    @Test
    public void parse_keepsTheOrderOfGitHub() throws IOException {
        List<Release> releases = GitHubReleases.parse("[" +
                "{\"tag_name\":\"32.68.3\",\"html_url\":\"https://github.com/o/r/releases/tag/32.68.3\"," +
                "\"body_html\":\"<p>New</p>\",\"published_at\":\"2026-10-25T01:14:33Z\"}," +
                "{\"tag_name\":\"32.68.2\",\"body_html\":\"<p>Old</p>\",\"published_at\":\"2026-10-18T10:08:25Z\"}]", "");

        assertEquals(2, releases.size());
        assertEquals("32.68.3", releases.get(0).version);
        assertEquals("https://github.com/o/r/releases/tag/32.68.3", releases.get(0).pageUrl);
        assertEquals("<p>New</p>", releases.get(0).bodyHtml);
        assertEquals(1792890873000L, releases.get(0).publishedMs);
        assertEquals("32.68.2", releases.get(1).version);
    }

    @Test
    public void parse_leavesOutDraftsAndUntagged() throws IOException {
        List<Release> releases = GitHubReleases.parse("[" +
                "{\"tag_name\":\"33.0\",\"draft\":true}," +
                "{\"tag_name\":\"\"}," +
                "{\"name\":\"No tag\"}," +
                "{\"tag_name\":\"32.68.3\"}]", "");

        assertEquals(1, releases.size());
        assertEquals("32.68.3", releases.get(0).version);
    }

    @Test
    public void parse_tagPrefixKeepsOnlyItsReleasesInOrder() throws IOException {
        List<Release> releases = GitHubReleases.parse("[" +
                "{\"tag_name\":\"utubot-v0.3.0\"}," +
                "{\"tag_name\":\"v1.2.3\"}," +
                "{\"tag_name\":\"utubot-v0.2.2\"}," +
                "{\"tag_name\":\"nightly\"}," +
                "{\"tag_name\":\"UTUBOT-V0.1.0\"}," +
                "{\"tag_name\":\"0.2.1-utubot-v\"}," +
                "{\"tag_name\":\"utubot-v0.2.0\",\"draft\":true}," +
                "{\"tag_name\":\"utubot-v0.2.1\"}]", "utubot-v");

        assertEquals(3, releases.size());
        assertEquals("utubot-v0.3.0", releases.get(0).version);
        assertEquals("utubot-v0.2.2", releases.get(1).version);
        assertEquals("utubot-v0.2.1", releases.get(2).version);
    }

    @Test
    public void parse_tagPrefixWithoutMatchIsEmpty() throws IOException {
        List<Release> releases = GitHubReleases.parse("[{\"tag_name\":\"32.68.3\"},{\"name\":\"No tag\"}]", "utubot-v");

        assertEquals(0, releases.size());
    }

    @Test
    public void parse_emptyTagPrefixKeepsAll() throws IOException {
        List<Release> releases = GitHubReleases.parse("[{\"tag_name\":\"utubot-v0.3.0\"},{\"tag_name\":\"32.68.3\"}]", "");

        assertEquals(2, releases.size());
    }

    /**
     * Without notes or a date (e.g. published without a body): nothing in them, not "null"
     */
    @Test
    public void parse_missingFieldsAreEmpty() throws IOException {
        Release release = GitHubReleases.parse("[{\"tag_name\":\"32.68.3\",\"body_html\":null,\"published_at\":null}]", "").get(0);

        assertEquals("", release.pageUrl);
        assertEquals("", release.bodyHtml);
        assertEquals(0, release.publishedMs);
    }

    @Test(expected = IOException.class)
    public void parse_notAList() throws IOException {
        // E.g. the API's error: {"message":"API rate limit exceeded ..."}
        GitHubReleases.parse("{\"message\":\"API rate limit exceeded\"}", "");
    }

    @Test
    public void parseDate_isUtc() {
        assertEquals(0L, GitHubReleases.parseDate("1970-01-01T00:00:00Z"));
        assertEquals(1792890873000L, GitHubReleases.parseDate("2026-10-25T01:14:33Z"));
    }

    @Test
    public void parseDate_invalidIsZero() {
        assertEquals(0L, GitHubReleases.parseDate(""));
        assertEquals(0L, GitHubReleases.parseDate("yesterday"));
    }

    @Test
    public void isInstalled_tagIsTheVersionNameWithPrefixAndV() {
        assertTrue(GitHubReleases.isInstalled(release("utubot-v0.2.2"), "0.2.2", "utubot-v"));
        // The update channel's versions have no prefix
        assertTrue(GitHubReleases.isInstalled(release("0.2.2"), "0.2.2", "utubot-v"));
        assertTrue(GitHubReleases.isInstalled(release("v0.2.2"), "0.2.2", ""));
        assertTrue(GitHubReleases.isInstalled(release("32.68.3"), "32.68.3", ""));
        assertFalse(GitHubReleases.isInstalled(release("utubot-v0.2.20"), "0.2.2", "utubot-v"));
        assertFalse(GitHubReleases.isInstalled(release("utubot-v0.2.1"), "0.2.2", "utubot-v"));
        assertFalse(GitHubReleases.isInstalled(release("utubot-v0.2.2"), "", "utubot-v"));
    }

    @Test
    public void parseUpdateChannel_newestFirstWithTheChangelog() throws IOException {
        List<Release> releases = GitHubReleases.parseUpdateChannel("{" +
                "\"package\":{\"downloadUrlList\":[\"https://utubot.example.com/app/u-tubot_0.9.0_universal.apk\"]}," +
                "\"0.9.0\":{\"versionCode\":9,\"changelog\":[\"First signed release\"]}," +
                "\"0.10.0\":{\"versionCode\":10,\"changelog\":[\"Marks & <b>hiding</b>\",\"  \",\"Summary panel\"]}," +
                "\"0.2.2\":{\"versionCode\":4,\"changelog\":\"One text\"}}");

        assertEquals(3, releases.size());
        assertEquals("0.10.0", releases.get(0).version);
        assertEquals("<ul><li>Marks &amp; &lt;b&gt;hiding&lt;/b&gt;</li><li>Summary panel</li></ul>", releases.get(0).bodyHtml);
        assertEquals("0.9.0", releases.get(1).version);
        assertEquals("0.2.2", releases.get(2).version);
        assertEquals("<ul><li>One text</li></ul>", releases.get(2).bodyHtml);
        assertEquals("", releases.get(0).pageUrl);
        assertEquals(0, releases.get(0).publishedMs);
    }

    @Test
    public void parseUpdateChannel_withoutVersionsIsEmpty() throws IOException {
        assertEquals(0, GitHubReleases.parseUpdateChannel("{\"package\":{}}").size());
    }

    @Test(expected = IOException.class)
    public void parseUpdateChannel_notAnObject() throws IOException {
        GitHubReleases.parseUpdateChannel("[]");
    }

    @Test
    public void compareVersions_numberByNumber() {
        assertTrue(GitHubReleases.compareVersions("0.10.0", "0.9.0") > 0);
        assertTrue(GitHubReleases.compareVersions("0.2.2", "0.2.10") < 0);
        assertTrue(GitHubReleases.compareVersions("v1.0", "1.0.0") == 0);
        assertTrue(GitHubReleases.compareVersions("1.0.1", "1.0") > 0);
    }

    private static Release release(String tag) {
        return new Release(tag, "", "", 0);
    }
}
