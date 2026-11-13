package com.liskovsoft.smartyoutubetv2.common.storage;

import android.content.Context;

import com.liskovsoft.sharedutils.helpers.FileHelpers;
import com.liskovsoft.sharedutils.prefs.GlobalPreferences;
import com.liskovsoft.smartyoutubetv2.common.prefs.AppPrefs;
import com.liskovsoft.smartyoutubetv2.common.prefs.GeneralData;
import com.liskovsoft.smartyoutubetv2.common.prefs.PlayerData;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;
import com.liskovsoft.youtubeapi.service.ServiceProfileData;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.shadows.ShadowLooper;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;
import java.util.function.BooleanSupplier;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.fail;

/**
 * The sync against a fake electriceel-storage (the API's behaviour, in memory): joining takes the server's values and sends the
 * missing ones, a change on either side reaches the other, Child mode stops both directions and its end joins again, and a
 * revoked device stops.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class StorageSyncTest {
    private static final String SCOPE = "account:" + AccountKeys.SIGNED_OUT;
    private Context mContext;
    private FakeServer mServer;

    /**
     * The API, in memory: revisions, pulls and pushes (every push applied), an authorization approved at once
     */
    static final class FakeServer {
        final ServerSocket socket;
        final Map<String, Map<String, Object[]>> scopes = new HashMap<>(); // scope -> key -> {json, revision}
        long revision;
        volatile boolean revoked;
        volatile int pushes;
        /**
         * The last push of each key had ifAbsent
         */
        final Map<String, Boolean> ifAbsent = new java.util.concurrent.ConcurrentHashMap<>();
        /**
         * The cursor of each scope in the last pull: the revision the device had pulled to
         */
        final Map<String, Long> pulledTo = new java.util.concurrent.ConcurrentHashMap<>();
        /**
         * The database's ID in the pulls (the server's Group.DatabaseID), null: a server that doesn't tell
         */
        String databaseId;
        /**
         * Restored right after the next push, before the device can pull: {scope, key, json}
         */
        String[] restoreAfterPush;

        FakeServer() throws IOException {
            socket = new ServerSocket(0, 50, InetAddress.getByName("127.0.0.1"));
            Thread accept = new Thread(() -> {
                while (!socket.isClosed()) {
                    try {
                        Socket client = socket.accept();
                        new Thread(() -> serve(client)).start();
                    } catch (IOException e) {
                        return;
                    }
                }
            });
            accept.setDaemon(true);
            accept.start();
        }

        void stop() {
            try {
                socket.close();
            } catch (IOException e) {
                // closed
            }
        }

        String url() {
            return "http://127.0.0.1:" + socket.getLocalPort();
        }

        /**
         * One request per connection (Connection: close): the request line, the headers, the body by its length
         */
        private void serve(Socket client) {
            try (Socket c = client) {
                InputStream in = c.getInputStream();
                String requestLine = line(in);
                int length = 0;

                for (String header = line(in); !header.isEmpty(); header = line(in)) {
                    if (header.toLowerCase().startsWith("content-length:")) {
                        length = Integer.parseInt(header.substring(15).trim());
                    }
                }

                byte[] body = new byte[length];
                int read = 0;

                while (read < length) {
                    int n = in.read(body, read, length - read);
                    if (n < 0) {
                        break;
                    }
                    read += n;
                }

                String target = requestLine.split(" ")[1];
                String path = target.contains("?") ? target.substring(0, target.indexOf('?')) : target;
                Object[] response = handle(path.substring("/api/v1".length()), new String(body, StandardCharsets.UTF_8));
                byte[] bytes = ((String) response[1]).getBytes(StandardCharsets.UTF_8);
                OutputStream out = c.getOutputStream();
                out.write(("HTTP/1.1 " + response[0] + " X\r\nContent-Type: application/json\r\nContent-Length: " + bytes.length
                        + "\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.UTF_8));
                out.write(bytes);
                out.flush();
            } catch (IOException | RuntimeException e) {
                // The client went away
            }
        }

        private static String line(InputStream in) throws IOException {
            StringBuilder sb = new StringBuilder();
            int b;

            while ((b = in.read()) >= 0 && b != '\n') {
                if (b != '\r') {
                    sb.append((char) b);
                }
            }

            return sb.toString();
        }

        synchronized void set(String scope, String key, String json) {
            revision++;
            scope(scope).put(key, new Object[] {json, revision});
        }

        /**
         * The database restored from an older backup: fewer revisions, other values
         */
        synchronized void restore(String scope, String key, String json) {
            scopes.clear();
            revision = 0;
            set(scope, key, json);
        }

        /**
         * Restored with a new database ID, then taken to the revision given by other devices' changes (of settings of another app
         * version), all before the device pulls again
         */
        synchronized void restore(String scope, String key, String json, String databaseId, long toRevision) {
            restore(scope, key, json);
            this.databaseId = databaseId;

            while (revision < toRevision) {
                set(scope, "another.version" + revision, "1");
            }
        }

        synchronized void setDatabaseId(String databaseId) {
            this.databaseId = databaseId;
        }

        synchronized void restoreAfterPush(String scope, String key, String json) {
            restoreAfterPush = new String[] {scope, key, json};
        }

        synchronized String get(String scope, String key) {
            Object[] entry = scope(scope).get(key);
            return entry != null ? (String) entry[0] : null;
        }

        synchronized long revision() {
            return revision;
        }

        /**
         * The device has pulled the revisions up to this one (its own pushes included), -1 before its first pull
         */
        long pulledTo(String scope) {
            Long cursor = pulledTo.get(scope);
            return cursor != null ? cursor : -1;
        }

        private Map<String, Object[]> scope(String scope) {
            Map<String, Object[]> map = scopes.get(scope);

            if (map == null) {
                map = new HashMap<>();
                scopes.put(scope, map);
            }

            return map;
        }

        private Object[] handle(String path, String body) {
            int status = 200;
            String out;

            try {
                if (path.equals("/info")) {
                    out = "{\"service\":\"electriceel-storage\",\"name\":\"Fake\",\"instanceId\":\"fake\",\"version\":\"test\"}";
                } else if (path.equals("/pairings")) {
                    status = 201;
                    out = "{\"pairingId\":\"p1\",\"pairingSecret\":\"s\",\"code\":\"123 456\",\"expiresAt\":" + (System.currentTimeMillis() + 600_000) + "}";
                } else if (path.startsWith("/pairings/")) {
                    out = "{\"status\":\"approved\",\"deviceId\":\"d1\",\"token\":\"eesd_t\",\"group\":{\"id\":\"g1\",\"name\":\"Test group\"}}";
                } else if (revoked) {
                    status = 401;
                    out = "{\"error\":\"device_unknown\"}";
                } else if (path.equals("/device")) {
                    out = "{\"deviceId\":\"d1\",\"deviceName\":\"TV\",\"group\":{\"id\":\"g1\",\"name\":\"Test group\"},\"needsManifest\":false}";
                } else if (path.equals("/manifest")) {
                    out = "{}";
                } else if (path.equals("/sync/pull")) {
                    out = pull(new JSONObject(body));
                } else if (path.equals("/sync/push")) {
                    out = push(new JSONObject(body));
                } else {
                    status = 404;
                    out = "{}";
                }
            } catch (JSONException e) {
                status = 400;
                out = "{}";
            }

            return new Object[] {status, out};
        }

        private String pull(JSONObject req) throws JSONException {
            JSONObject cursors = req.getJSONObject("cursors");
            boolean waits = req.optInt("wait") > 0;
            JSONArray changes = new JSONArray();
            JSONObject next = new JSONObject();
            String database;

            synchronized (this) {
                database = databaseId;

                for (Iterator<String> it = cursors.keys(); it.hasNext(); ) {
                    String scope = it.next();
                    long since = cursors.getLong(scope);
                    pulledTo.put(scope, since);

                    for (Map.Entry<String, Object[]> e : scope(scope).entrySet()) {
                        if ((long) e.getValue()[1] > since) {
                            JSONObject c = new JSONObject();
                            c.put("scope", scope);
                            c.put("key", e.getKey());
                            c.put("value", new org.json.JSONTokener((String) e.getValue()[0]).nextValue());
                            c.put("revision", e.getValue()[1]);
                            changes.put(c);
                        }
                    }

                    next.put(scope, revision);
                }
            }

            if (changes.length() == 0 && waits) {
                try {
                    Thread.sleep(100);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }

            JSONObject res = new JSONObject().put("changes", changes).put("cursors", next).put("more", false);

            if (database != null) {
                res.put("databaseId", database);
            }

            return res.toString();
        }

        private synchronized String push(JSONObject req) throws JSONException {
            JSONArray changes = req.getJSONArray("changes");
            JSONArray results = new JSONArray();

            for (int i = 0; i < changes.length(); i++) {
                JSONObject c = changes.getJSONObject(i);
                ifAbsent.put(c.getString("key"), c.optBoolean("ifAbsent"));
                Object value = c.get("value");
                String json = value instanceof String ? JSONObject.quote((String) value) : String.valueOf(value);
                set(c.getString("scope"), c.getString("key"), json);
                results.put(new JSONObject().put("scope", c.getString("scope")).put("key", c.getString("key"))
                        .put("status", "applied").put("revision", revision));
            }

            pushes++;
            String res = new JSONObject().put("results", results).put("revision", revision).toString();

            if (restoreAfterPush != null) {
                restore(restoreAfterPush[0], restoreAfterPush[1], restoreAfterPush[2]);
                restoreAfterPush = null;
            }

            return res;
        }

    }

    @Before
    public void setUp() throws IOException {
        mContext = RuntimeEnvironment.getApplication();
        // The services' store is written through MediaServicePrefs (see ServiceProfileData.setData), which reads the app's context from it
        GlobalPreferences.instance(mContext);
        AppPrefs.instance(mContext).onAccountChanged(null); // signed out
        FileHelpers.delete(new File(FileHelpers.getFilesDir(mContext), StorageConfig.DIR));
        StorageSync.resetForTesting();
        mServer = new FakeServer();
    }

    @After
    public void tearDown() {
        StorageSync.resetForTesting();
        mServer.stop();
        Utils.sHandler.removeCallbacksAndMessages(null);
    }

    private static void await(String what, BooleanSupplier condition) {
        long end = System.currentTimeMillis() + 20_000;

        while (System.currentTimeMillis() < end) {
            ShadowLooper.idleMainLooper();

            if (condition.getAsBoolean()) {
                return;
            }

            try {
                Thread.sleep(20);
            } catch (InterruptedException e) {
                throw new AssertionError(e);
            }
        }

        fail("Timed out waiting for: " + what);
    }

    private void connect() throws IOException {
        StorageSettings.setEnabled(mContext, true);
        StorageSettings.setServer(mContext, mServer.url());
        StorageSettings.setAccountSynced(mContext, AccountKeys.SIGNED_OUT, true);
        StorageSettings.requestAuthorization(mContext);
        await("authorized", () -> StorageSync.instance(mContext).getConfig().isAuthorized());
    }

    @Test
    public void joinsThenSyncsBothWays() throws IOException {
        PlayerData player = PlayerData.instance(mContext);
        GeneralData general = GeneralData.instance(mContext);
        player.setSubtitleScale(1.25f);
        general.setScreensaverTimeoutMs(60_000);
        ShadowLooper.idleMainLooper();
        // The group has a subtitle size already, not the screensaver timeout
        mServer.set(SCOPE, "player.subtitleScale", "2");

        connect();
        assertEquals("Test group", StorageSync.instance(mContext).getConfig().getGroupName());

        // Joining: the group's size is taken, the device's timeout sent
        await("the group's size taken", () -> Math.abs(player.getSubtitleScale() - 2.0f) < 0.001);
        await("the timeout sent", () -> "60000".equals(mServer.get(SCOPE, "general.screensaverTimeoutMs")));
        assertEquals("2", mServer.get(SCOPE, "player.subtitleScale"));
        // Never had from the server: the group's value would win
        assertEquals(Boolean.TRUE, mServer.ifAbsent.get("general.screensaverTimeoutMs"));
        // Only what's listed: no Child mode, no password
        assertNull(mServer.get(SCOPE, "general.childMode"));

        // Another device changes the size
        mServer.set(SCOPE, "player.subtitleScale", "1.75");
        await("the new size taken", () -> Math.abs(player.getSubtitleScale() - 1.75f) < 0.001);

        // Changed here: sent
        general.setScreensaverTimeoutMs(90_000);
        ShadowLooper.idleMainLooper();
        StorageSync.instance(mContext).wake();
        await("the change sent", () -> "90000".equals(mServer.get(SCOPE, "general.screensaverTimeoutMs")));
        // A change of a synced setting: the newer one wins
        assertEquals(Boolean.FALSE, mServer.ifAbsent.get("general.screensaverTimeoutMs"));
    }

    @Test
    public void childModeStopsTheSyncAndItsEndJoinsAgain() throws IOException {
        PlayerData player = PlayerData.instance(mContext);
        GeneralData general = GeneralData.instance(mContext);
        player.setSubtitleScale(1.5f);
        ShadowLooper.idleMainLooper();
        connect();
        await("the size sent", () -> "1.5".equals(mServer.get(SCOPE, "player.subtitleScale")));

        general.setChildModeEnabled(true);
        ShadowLooper.idleMainLooper();
        StorageSync.instance(mContext).wake();
        sleepPumping(1_500);

        // Neither way: the child's size isn't sent, the group's isn't taken
        player.setSubtitleScale(0.5f);
        ShadowLooper.idleMainLooper();
        mServer.set(SCOPE, "player.subtitleScale", "3");
        StorageSync.instance(mContext).wake();
        sleepPumping(1_500);
        assertEquals(0.5f, player.getSubtitleScale(), 0.001f);
        assertEquals("3", mServer.get(SCOPE, "player.subtitleScale"));

        // Child mode off: the account joins again and takes the group's settings
        general.setChildModeEnabled(false);
        ShadowLooper.idleMainLooper();
        StorageSync.instance(mContext).wake();
        await("the group's size after Child mode", () -> Math.abs(player.getSubtitleScale() - 3.0f) < 0.001);
    }

    @Test
    public void aRevokedDeviceKeepsItsSettings() throws IOException {
        PlayerData player = PlayerData.instance(mContext);
        player.setSubtitleScale(1.5f);
        ShadowLooper.idleMainLooper();
        connect();
        await("the size sent", () -> "1.5".equals(mServer.get(SCOPE, "player.subtitleScale")));

        mServer.revoked = true;
        StorageSync.instance(mContext).wake();
        // The loop clears the authorization before it sets the status: wait until both settled, else the status check races
        await("not authorized", () -> !StorageSync.instance(mContext).getConfig().isAuthorized()
                && StorageSync.instance(mContext).getStatus().state == StorageSync.State.NOT_AUTHORIZED);
        assertEquals(StorageSync.State.NOT_AUTHORIZED, StorageSync.instance(mContext).getStatus().state);
        assertEquals(1.5f, player.getSubtitleScale(), 0.001f);
        assertFalse(StorageSync.instance(mContext).getConfig().isAuthorized());
    }

    @Test
    public void aRestoredServerIsJoinedAgain() throws IOException {
        PlayerData player = PlayerData.instance(mContext);
        GeneralData general = GeneralData.instance(mContext);
        player.setSubtitleScale(1.5f);
        general.setScreensaverTimeoutMs(30_000);
        ShadowLooper.idleMainLooper();
        connect();
        await("sent", () -> "30000".equals(mServer.get(SCOPE, "general.screensaverTimeoutMs")));
        // Restored once the device has pulled past its pushes: its cursor goes back (aServerRestoredBeforeThePullIsJoinedAgain
        // restores it before that)
        long head = mServer.revision();
        await("pulled past the pushes", () -> mServer.pulledTo(SCOPE) >= head);

        // Back to a backup with one revision: its value is taken, and the revisions this device knew don't hide the next ones
        mServer.restore(SCOPE, "player.subtitleScale", "2.5");
        StorageSync.instance(mContext).wake();
        await("the restored value taken", () -> Math.abs(player.getSubtitleScale() - 2.5f) < 0.001);
        await("the device's own value sent again", () -> "30000".equals(mServer.get(SCOPE, "general.screensaverTimeoutMs")));
        mServer.set(SCOPE, "player.subtitleScale", "1.1");
        await("the next change taken", () -> Math.abs(player.getSubtitleScale() - 1.1f) < 0.001);
    }

    @Test
    public void aServerRestoredBeforeThePullIsJoinedAgain() throws IOException {
        PlayerData player = PlayerData.instance(mContext);
        GeneralData general = GeneralData.instance(mContext);
        player.setSubtitleScale(1.5f);
        general.setScreensaverTimeoutMs(30_000);
        ShadowLooper.idleMainLooper();
        // Restored right after the device's first push: its cursor is still below the backup's revision, so nothing goes back,
        // and the backup's value has a revision the device had from its push. Only that the cursor is below the revisions of its
        // pushes shows the restore.
        mServer.restoreAfterPush(SCOPE, "player.subtitleScale", "2.5");

        connect();
        await("the restored value taken", () -> Math.abs(player.getSubtitleScale() - 2.5f) < 0.001);
        await("the device's own value sent again", () -> "30000".equals(mServer.get(SCOPE, "general.screensaverTimeoutMs")));
    }

    @Test
    public void aRestoredDatabaseIsJoinedAgainAfterTheGroupWentPast() throws IOException {
        PlayerData player = PlayerData.instance(mContext);
        GeneralData general = GeneralData.instance(mContext);
        player.setSubtitleScale(1.5f);
        general.setScreensaverTimeoutMs(30_000);
        ShadowLooper.idleMainLooper();
        mServer.setDatabaseId("first");
        connect();
        await("sent", () -> "30000".equals(mServer.get(SCOPE, "general.screensaverTimeoutMs")));
        long head = mServer.revision();
        await("pulled past the pushes", () -> mServer.pulledTo(SCOPE) >= head);

        // Restored, and the other devices take the group past this device's cursor before it pulls again: no revision goes back,
        // only the database's ID shows the restore
        mServer.restore(SCOPE, "player.subtitleScale", "2.5", "restored", head + 2);
        StorageSync.instance(mContext).wake();
        await("the restored value taken", () -> Math.abs(player.getSubtitleScale() - 2.5f) < 0.001);
        await("the device's own value sent again", () -> "30000".equals(mServer.get(SCOPE, "general.screensaverTimeoutMs")));
        mServer.set(SCOPE, "player.subtitleScale", "1.1");
        await("the next change taken", () -> Math.abs(player.getSubtitleScale() - 1.1f) < 0.001);
    }

    @Test
    public void syncsTheAccountsContent() throws IOException {
        // Where the services keep it: under Robolectric their context is the first test's (see ServiceProfileData.dataDir)
        File serviceDir = ServiceProfileData.dataDir();
        File searchTags = new File(serviceDir, "anonymous_search_tag_data");
        AppPrefs prefs = AppPrefs.instance(mContext);
        File hiddenVideos = prefs.getDataFile(prefs.getAccountDataKey(null, "hidden_videos_data"));
        FileHelpers.delete(searchTags);
        FileHelpers.delete(hiddenVideos);
        // The services' store and the app's: both taken from the group
        mServer.set(SCOPE, "content.searchHistory", JSONObject.quote("cats%AR%dogs"));
        mServer.set(SCOPE, "content.hiddenVideos", JSONObject.quote("1%OB%Home%OB%card"));

        connect();
        await("the search history taken", () -> "cats%AR%dogs".equals(FileHelpers.getFileContents(searchTags)));
        await("the hidden videos taken", () -> "1%OB%Home%OB%card".equals(FileHelpers.getFileContents(hiddenVideos)));

        // Changed here: sent
        FileHelpers.stringToFileAtomic("cats%AR%dogs%AR%eels", searchTags);
        StorageSync.instance(mContext).wake();
        await("the search history sent", () -> JSONObject.quote("cats%AR%dogs%AR%eels").equals(mServer.get(SCOPE, "content.searchHistory")));
    }

    private static void sleepPumping(long ms) {
        long end = System.currentTimeMillis() + ms;

        while (System.currentTimeMillis() < end) {
            ShadowLooper.idleMainLooper();

            try {
                Thread.sleep(20);
            } catch (InterruptedException e) {
                throw new AssertionError(e);
            }
        }
    }
}
