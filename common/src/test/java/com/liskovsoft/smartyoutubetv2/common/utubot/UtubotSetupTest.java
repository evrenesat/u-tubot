package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSetup.SetupException;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotSetupTest {
    @Test
    public void bareHostGetsHttpsAndSetupPath() throws Exception {
        assertEquals("https://utubot.example.com/setup.json", UtubotSetup.resolveUrl("utubot.example.com"));
        assertEquals("https://utubot.example.com/setup.json", UtubotSetup.resolveUrl("  utubot.example.com/ "));
        assertEquals("https://utubot.example.com:8443/setup.json", UtubotSetup.resolveUrl("utubot.example.com:8443"));
    }

    @Test
    public void bareLanAddressGetsHttp() throws Exception {
        assertEquals("http://10.0.0.10:8790/setup.json", UtubotSetup.resolveUrl("10.0.0.10:8790"));
        assertEquals("http://nas:8790/setup.json", UtubotSetup.resolveUrl("nas:8790"));
        assertEquals("http://100.64.0.7:8790/setup.json", UtubotSetup.resolveUrl("100.64.0.7:8790"));
    }

    @Test
    public void fullUrlIsUsedAsTyped() throws Exception {
        assertEquals("https://example.com/me/setup.json", UtubotSetup.resolveUrl("https://example.com/me/setup.json"));
        assertEquals("http://10.0.0.10:8790/setup.json", UtubotSetup.resolveUrl("http://10.0.0.10:8790/setup.json"));
    }

    @Test
    public void httpOnlyForPrivateAddresses() {
        assertRejected("http://example.com/setup.json");
        assertRejected("http://8.8.8.8/setup.json");
        assertRejected("ftp://example.com/setup.json");
        assertRejected("");
        assertRejected("   ");
        assertRejected(null);
    }

    @Test
    public void privateHosts() {
        assertTrue(UtubotSetup.isPrivateHost("10.0.0.1"));
        assertTrue(UtubotSetup.isPrivateHost("172.16.5.5"));
        assertTrue(UtubotSetup.isPrivateHost("172.31.255.1"));
        assertTrue(UtubotSetup.isPrivateHost(String.join(".", "192", "168", "0", "9")));
        assertTrue(UtubotSetup.isPrivateHost("127.0.0.1"));
        assertTrue(UtubotSetup.isPrivateHost("169.254.1.1"));
        assertTrue(UtubotSetup.isPrivateHost("::1"));
        assertTrue(UtubotSetup.isPrivateHost("fd00::1"));
        assertTrue(UtubotSetup.isPrivateHost("localhost"));
        assertTrue(UtubotSetup.isPrivateHost("nas.local"));
        assertFalse(UtubotSetup.isPrivateHost("172.32.0.1"));
        assertFalse(UtubotSetup.isPrivateHost("100.128.0.1"));
        assertFalse(UtubotSetup.isPrivateHost("8.8.8.8"));
        assertFalse(UtubotSetup.isPrivateHost("example.com"));
        assertFalse(UtubotSetup.isPrivateHost(""));
    }

    @Test
    public void parsesTheSetupFile() throws Exception {
        UtubotSetup setup = UtubotSetup.parse("{\"utubot_setup\":1,\"name\":\"Home\",\"backend_url\":\"https://utubot.example.com/\","
                + "\"update_url\":\"https://utubot.example.com/app/update.json\",\"pairing\":true,"
                + "\"defaults\":{\"assess\":true,\"mark_only\":true,\"summary_panel\":false,\"auto_captions\":true},"
                + "\"prompt_set_urls\":[\"https://example.com/p.json\",\"\"]}");

        assertEquals("Home", setup.name);
        assertEquals("https://utubot.example.com", setup.backendUrl);
        assertEquals("https://utubot.example.com/app/update.json", setup.updateUrl);
        assertTrue(setup.pairing);
        assertEquals(Boolean.TRUE, setup.defaults.markOnly);
        assertEquals(Boolean.FALSE, setup.defaults.summaryPanel);
        assertNull(setup.defaults.answerInMenu);
        assertEquals(1, setup.promptSetUrls.size());
    }

    @Test
    public void minimalSetupKeepsDefaultsUnset() throws Exception {
        UtubotSetup setup = UtubotSetup.parse("{\"utubot_setup\":1,\"backend_url\":\"http://10.0.0.10:8790\"}");

        assertEquals("", setup.updateUrl);
        assertTrue(setup.pairing);
        assertNull(setup.defaults.assess);
        assertTrue(setup.promptSetUrls.isEmpty());
    }

    @Test
    public void rejectsBadSetupFiles() {
        assertBad("not json");
        assertBad("{\"backend_url\":\"https://utubot.example.com\"}");
        assertBad("{\"utubot_setup\":2,\"backend_url\":\"https://utubot.example.com\"}");
        assertBad("{\"utubot_setup\":1}");
        assertBad("{\"utubot_setup\":1,\"backend_url\":\"http://example.com\"}");
        assertBad("{\"utubot_setup\":1,\"backend_url\":\"https://utubot.example.com\",\"update_url\":\"http://example.com/u.json\"}");
    }

    private static void assertRejected(String input) {
        try {
            UtubotSetup.resolveUrl(input);
            fail("accepted: " + input);
        } catch (SetupException expected) {
            // ok
        }
    }

    private static void assertBad(String json) {
        try {
            UtubotSetup.parse(json);
            fail("accepted: " + json);
        } catch (SetupException expected) {
            // ok
        }
    }
}
