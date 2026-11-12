package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.app.Activity;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionCategory;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.net.ConnectException;
import java.net.SocketTimeoutException;
import java.net.UnknownHostException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import javax.net.ssl.SSLHandshakeException;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotSetupFlowTest {
    private static final String SETUP = "{\"utubot_setup\":1,\"name\":\"Family\",\"backend_url\":\"http://127.0.0.1:1\"}";
    private Activity mActivity;
    private TinyHttpServer mServer;

    @Before
    public void setUp() throws Exception {
        mActivity = Robolectric.buildActivity(Activity.class).setup().get();
        mServer = new TinyHttpServer();
    }

    @After
    public void tearDown() {
        mServer.stop();
    }

    @Test
    public void importErrors_areMappedToReasons() {
        assertEquals(mActivity.getString(R.string.utubot_error_dns), UtubotSetupFlow.describeError(mActivity, new UnknownHostException("x")));
        assertEquals(mActivity.getString(R.string.utubot_error_tls), UtubotSetupFlow.describeError(mActivity, new SSLHandshakeException("x")));
        assertEquals(mActivity.getString(R.string.utubot_error_timeout), UtubotSetupFlow.describeError(mActivity, new SocketTimeoutException()));
        assertEquals(mActivity.getString(R.string.utubot_error_connect), UtubotSetupFlow.describeError(mActivity, new ConnectException("x")));
        assertEquals(mActivity.getString(R.string.utubot_error_http, 404),
                UtubotSetupFlow.describeError(mActivity, new UtubotClient.HttpException(404, "HTTP 404")));
        assertEquals("Not a u·tubot setup file", UtubotSetupFlow.describeError(mActivity, new UtubotSetup.SetupException("Not a u·tubot setup file")));
        assertEquals("EOFException", UtubotSetupFlow.describeError(mActivity, new java.io.EOFException()));
        assertEquals("boom", UtubotSetupFlow.describeError(mActivity, new IOException("boom")));
    }

    @Test
    public void fetchSetup_shortBodyIsRead() throws Exception {
        mServer.on("/setup.json", request -> new TinyHttpServer.Response(200, SETUP));

        UtubotSetup setup = UtubotClient.fetchSetup("http://127.0.0.1:" + mServer.getPort() + "/setup.json");

        assertEquals("Family", setup.name);
        assertEquals("http://127.0.0.1:1", setup.backendUrl);
    }

    @Test
    public void fetchSetup_httpErrorBecomesStatus() {
        mServer.on("/setup.json", request -> new TinyHttpServer.Response(404, "{}"));

        try {
            UtubotClient.fetchSetup("http://127.0.0.1:" + mServer.getPort() + "/setup.json");
            fail();
        } catch (UtubotClient.HttpException e) {
            assertEquals(404, e.code);
        } catch (Exception e) {
            fail(e.toString());
        }
    }

    @Test
    public void fetchSetup_badJson() {
        mServer.on("/setup.json", request -> new TinyHttpServer.Response(200, "<html>nope</html>"));

        try {
            UtubotClient.fetchSetup("http://127.0.0.1:" + mServer.getPort() + "/setup.json");
            fail();
        } catch (UtubotSetup.SetupException e) {
            assertEquals("Not a u·tubot setup file", e.getMessage());
        } catch (Exception e) {
            fail(e.toString());
        }
    }

    @Test
    public void readBounded_rejectsOversizedBody() throws Exception {
        byte[] big = new byte[100];
        Arrays.fill(big, (byte) 'a');

        assertEquals("abc", UtubotClient.readBounded(new ByteArrayInputStream("abc".getBytes(StandardCharsets.UTF_8)), 10));

        try {
            UtubotClient.readBounded(new ByteArrayInputStream(big), 10);
            fail();
        } catch (UtubotSetup.SetupException e) {
            assertTrue(e.getMessage().contains("too large"));
        }
    }

    @Test
    public void settingsList_hasImportAndPairFirst_thenSwitches_promptsTestAdvanced() {
        List<OptionCategory> categories = UtubotSettingsPresenter.instance(mActivity).buildCategories();
        List<String> titles = new ArrayList<>();
        List<Integer> types = new ArrayList<>();

        for (OptionCategory category : categories) {
            titles.add(category.options.get(0).getTitle().toString());
            types.add(category.type);
        }

        assertEquals(Arrays.asList(
                mActivity.getString(R.string.utubot_import_setup),
                mActivity.getString(R.string.utubot_pair),
                mActivity.getString(R.string.utubot_assess),
                mActivity.getString(R.string.utubot_mark_only),
                mActivity.getString(R.string.utubot_answer_in_menu),
                mActivity.getString(R.string.utubot_summary_panel),
                mActivity.getString(R.string.utubot_auto_captions),
                mActivity.getString(R.string.utubot_prompts),
                mActivity.getString(R.string.utubot_test_connection),
                mActivity.getString(R.string.utubot_advanced)), titles);
        assertEquals(OptionCategory.TYPE_SINGLE_BUTTON, (int) types.get(0));
        assertEquals(OptionCategory.TYPE_SINGLE_BUTTON, (int) types.get(1));
        assertEquals(OptionCategory.TYPE_SINGLE_SWITCH, (int) types.get(2));
    }

    @Test
    public void settingsList_isTheSameWhenConfigured() {
        UtubotSettings settings = UtubotSettings.instance(mActivity);
        settings.setUrl("https://utubot.example.com");
        settings.setToken("utb_x");

        List<OptionCategory> categories = UtubotSettingsPresenter.instance(mActivity).buildCategories();

        assertEquals(10, categories.size());
        assertEquals(mActivity.getString(R.string.utubot_import_setup), categories.get(0).options.get(0).getTitle().toString());
        assertEquals(mActivity.getString(R.string.utubot_pair), categories.get(1).options.get(0).getTitle().toString());
    }

    @Test
    public void manualBackend_derivesUpdateUrl() throws Exception {
        UtubotSettings settings = UtubotSettings.instance(mActivity);
        settings.setUpdateUrl("");

        settings.setUrlManually("https://utubot.example.com/");

        assertEquals("https://utubot.example.com/app/update.json", settings.getUpdateUrl());
    }

    @Test
    public void manualBackend_keepsAnImportedUpdateUrl() throws Exception {
        UtubotSettings settings = UtubotSettings.instance(mActivity);
        settings.setUrl("https://a.example.com");
        settings.setUpdateUrl("https://cdn.example.com/update.json");

        settings.setUrlManually("https://b.example.com");

        assertEquals("https://cdn.example.com/update.json", settings.getUpdateUrl());
    }

    @Test
    public void manualBackend_followsADerivedUpdateUrl() throws Exception {
        UtubotSettings settings = UtubotSettings.instance(mActivity);
        settings.setUrlManually("https://a.example.com");

        settings.setUrlManually("https://b.example.com");

        assertEquals("https://b.example.com/app/update.json", settings.getUpdateUrl());
    }

    @Test
    public void upgradedDevice_backendTypedBeforeUpdateUrlsFollowsTheBackend() {
        UtubotSettings settings = freshSettings(prefs -> prefs.putString("url", "https://utubot.example.com/ai"));

        assertEquals("https://utubot.example.com/ai/app/update.json", settings.getUpdateUrl());
    }

    @Test
    public void upgradedDevice_aStoredUpdateUrlWinsOverTheBackend() {
        UtubotSettings settings = freshSettings(prefs -> prefs.putString("url", "https://utubot.example.com").putString("update_url", "https://cdn.example.com/update.json"));

        assertEquals("https://cdn.example.com/update.json", settings.getUpdateUrl());
    }

    @Test
    public void upgradedDevice_anUpdateUrlStoredEmptyByASetupStaysEmpty() {
        UtubotSettings settings = freshSettings(prefs -> prefs.putString("url", "https://utubot.example.com").putString("update_url", ""));

        assertEquals("", settings.getUpdateUrl());
    }

    @Test
    public void upgradedDevice_noBackendOrAnUnsafeOneMeansNoUpdateSource() {
        assertEquals("", freshSettings(prefs -> prefs.putString("token", "t")).getUpdateUrl());
        assertEquals("", freshSettings(prefs -> prefs.putString("url", "http://utubot.example.com")).getUpdateUrl());
        assertEquals("", freshSettings(prefs -> prefs.putString("url", "ftp://utubot.example.com")).getUpdateUrl());
    }

    @Test
    public void upgradedDevice_aBackendTypedLaterKeepsTheDerivedAddressInStep() throws Exception {
        UtubotSettings settings = freshSettings(prefs -> prefs.putString("url", "https://a.example.com"));

        settings.setUrlManually("https://b.example.com");

        assertEquals("https://b.example.com/app/update.json", settings.getUpdateUrl());
    }

    /**
     * The settings with only these values stored, as an upgrade leaves them
     */
    private UtubotSettings freshSettings(java.util.function.Function<android.content.SharedPreferences.Editor, android.content.SharedPreferences.Editor> store) {
        UtubotSettings settings = UtubotSettings.instance(mActivity);
        store.apply(StoredSettings.cleared(settings)).commit();

        return settings;
    }

    @Test
    public void deriveUpdateUrl_trimsTheSlash() throws Exception {
        assertEquals("http://10.0.0.5:8790/app/update.json", UtubotSetup.deriveUpdateUrl(" http://10.0.0.5:8790/ "));
    }

    @Test
    public void deriveUpdateUrl_keepsThePathAndDropsQueryAndFragment() throws Exception {
        assertEquals("https://h.example.com:8443/ai/app/update.json", UtubotSetup.deriveUpdateUrl("https://h.example.com:8443/ai/?x=1#f"));
        assertEquals("https://h.example.com/app/update.json", UtubotSetup.deriveUpdateUrl("https://h.example.com?token=s"));
    }

    @Test
    public void manualBackend_rejectsPlainHttpToAPublicHost() {
        UtubotSettings settings = UtubotSettings.instance(mActivity);
        settings.setUrl("https://ok.example.com");
        settings.setUpdateUrl("");

        try {
            settings.setUrlManually("http://evil.example.com");
            fail();
        } catch (UtubotSetup.SetupException e) {
            assertTrue(e.getMessage().contains("http"));
        }

        assertEquals("https://ok.example.com", settings.getUrl());
        assertEquals("", settings.getUpdateUrl());
    }

    @Test
    public void manualBackend_rejectsGarbageAndOtherSchemes() {
        UtubotSettings settings = UtubotSettings.instance(mActivity);

        for (String bad : new String[]{"ftp://x.example.com", "not a url", "https://"}) {
            try {
                settings.setUrlManually(bad);
                fail(bad);
            } catch (UtubotSetup.SetupException expected) {
                // rejected
            }
        }
    }

    @Test
    public void manualBackend_acceptsPrivateHttp() throws Exception {
        UtubotSettings settings = UtubotSettings.instance(mActivity);
        settings.setUpdateUrl("");

        settings.setUrlManually("http://10.0.0.5:8790");

        assertEquals("http://10.0.0.5:8790/app/update.json", settings.getUpdateUrl());
    }

    @Test
    public void manualBackend_hostChangeDropsTheToken() throws Exception {
        UtubotSettings settings = UtubotSettings.instance(mActivity);
        settings.setUrlManually("https://a.example.com");
        settings.setToken("secret");

        settings.setUrlManually("https://a.example.com/");
        assertEquals("secret", settings.getToken());

        settings.setUrlManually("https://b.example.com");
        assertEquals("", settings.getToken());
        assertFalse(settings.isPairPromptDone());
    }

    @Test
    public void applySetup_needsPairingOnlyWithoutATokenOrOnANewBackend() throws Exception {
        UtubotSettings settings = UtubotSettings.instance(mActivity);
        UtubotSetup setup = UtubotSetup.parse("{\"utubot_setup\":1,\"backend_url\":\"https://a.example.com\"}");
        settings.setUrl("");
        settings.setToken("");

        assertTrue(settings.applySetup(setup));

        settings.setToken("secret");
        assertFalse(settings.applySetup(setup));
        assertEquals("secret", settings.getToken());

        UtubotSetup other = UtubotSetup.parse("{\"utubot_setup\":1,\"backend_url\":\"https://b.example.com\"}");
        assertTrue(settings.applySetup(other));
    }

    @Test
    public void withoutQuery_dropsQueryAndFragment() {
        assertEquals("https://h.example.com:8443/setup.json", UtubotSetupFlow.withoutQuery("https://h.example.com:8443/setup.json?code=abc#x"));
    }

    @Test
    public void firstLaunchPrompt_offersImportNotNowAndDontAskAgain() {
        UtubotSettings settings = UtubotSettings.instance(mActivity);
        settings.setSetupPromptDone(false);

        List<OptionCategory> categories = UtubotPairing.buildPromptCategories(mActivity, true);

        assertEquals(3, categories.size());
        assertTrue(UtubotPairing.shouldPromptSetup(settings) == UtubotSettings.isBuiltIn() && !settings.isConfigured() || settings.isConfigured());

        categories.get(1).options.get(0).onSelect(true);
        assertFalse("Not now doesn't stop the prompt", settings.isSetupPromptDone());

        categories.get(2).options.get(0).onSelect(true);
        assertTrue("Don't ask again does", settings.isSetupPromptDone());
        assertFalse(UtubotPairing.shouldPromptSetup(settings));
    }
}
