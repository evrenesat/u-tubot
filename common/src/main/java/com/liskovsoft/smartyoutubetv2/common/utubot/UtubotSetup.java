package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The setup file a backend serves at /setup.json (ai/CONTRACT.md) and the rules that turn what the user types into the
 * address to fetch it from.
 */
public final class UtubotSetup {
    public static final int FORMAT_VERSION = 1;
    public static final String SETUP_PATH = "/setup.json";
    public static final String UPDATE_PATH = "/app/update.json";
    private static final Pattern IPV4 = Pattern.compile("^(\\d{1,3})\\.(\\d{1,3})\\.(\\d{1,3})\\.(\\d{1,3})$");
    private static final String[] LOCAL_SUFFIXES = {".local", ".lan", ".internal", ".home.arpa", ".ts.net"};
    private static final int CGNAT_SECOND_OCTET_FIRST = 64;
    private static final int CGNAT_SECOND_OCTET_LAST = 127;
    private static final int PRIVATE_172_FIRST = 16;
    private static final int PRIVATE_172_LAST = 31;

    /**
     * What the user typed is not a usable address
     */
    public static class SetupException extends Exception {
        public SetupException(String message) {
            super(message);
        }
    }

    /**
     * App switch values from the setup; null means the setup doesn't say
     */
    public static final class Defaults {
        @Nullable public Boolean assess;
        @Nullable public Boolean markOnly;
        @Nullable public Boolean answerInMenu;
        @Nullable public Boolean summaryPanel;
        @Nullable public Boolean autoCaptions;
    }

    public String name = "";
    public String backendUrl = "";
    public String updateUrl = "";
    public boolean pairing = true;
    public final Defaults defaults = new Defaults();
    public final List<String> promptSetUrls = new ArrayList<>();

    private UtubotSetup() {
    }

    /**
     * The address to fetch the setup from. A bare host (utubot.example.com, host:port) gets https and /setup.json; a bare LAN
     * address gets http, as it can't have a certificate. A full URL is used as typed. http is accepted for private addresses only.
     */
    public static String resolveUrl(@Nullable String input) throws SetupException {
        String text = input == null ? "" : input.trim();

        if (text.isEmpty()) {
            throw new SetupException("Type the server address");
        }

        boolean full = text.contains("://");
        URI uri = parseUri(full ? text : "https://" + text);
        String host = hostOf(uri);

        if (full) {
            requireAllowedScheme(uri, host);
            return text;
        }

        String scheme = isPrivateHost(host) ? "http" : "https";
        String path = uri.getRawPath() == null || uri.getRawPath().isEmpty() || uri.getRawPath().equals("/") ? SETUP_PATH : uri.getRawPath();
        String port = uri.getPort() >= 0 ? ":" + uri.getPort() : "";
        String hostPart = host.contains(":") ? "[" + host + "]" : host;
        String query = uri.getRawQuery() != null ? "?" + uri.getRawQuery() : "";

        return scheme + "://" + hostPart + port + path + query;
    }

    /**
     * The update file of a backend: its /app/update.json
     */
    public static String deriveUpdateUrl(String backendUrl) {
        return stripTrailingSlash(backendUrl.trim()) + UPDATE_PATH;
    }

    /**
     * An address of the backend or of the update file from the setup: https, or http for a private address
     */
    public static String requireUrl(@Nullable String url, String what) throws SetupException {
        if (url == null || url.trim().isEmpty()) {
            throw new SetupException("The setup has no " + what);
        }

        URI uri = parseUri(url.trim());
        requireAllowedScheme(uri, hostOf(uri));

        return url.trim();
    }

    public static UtubotSetup parse(String json) throws SetupException {
        try {
            JSONObject root = new JSONObject(json);

            if (root.optInt("utubot_setup", 0) != FORMAT_VERSION) {
                throw new SetupException("Not a u·tubot setup file");
            }

            UtubotSetup setup = new UtubotSetup();
            setup.name = root.optString("name", "");
            setup.backendUrl = stripTrailingSlash(requireUrl(root.optString("backend_url", ""), "backend_url"));
            String update = root.optString("update_url", "");
            setup.updateUrl = update.trim().isEmpty() ? "" : requireUrl(update, "update_url");
            setup.pairing = root.optBoolean("pairing", true);
            readDefaults(root.optJSONObject("defaults"), setup.defaults);
            JSONArray sets = root.optJSONArray("prompt_set_urls");

            for (int i = 0; sets != null && i < sets.length(); i++) {
                String url = sets.optString(i, "").trim();

                if (!url.isEmpty()) {
                    setup.promptSetUrls.add(url);
                }
            }

            return setup;
        } catch (JSONException e) {
            throw new SetupException("Not a u·tubot setup file");
        }
    }

    /**
     * Loopback, RFC1918, link-local, CGNAT (tailnet) and unique-local addresses, local names (single label, .local, .lan, ...)
     */
    public static boolean isPrivateHost(@Nullable String host) {
        if (host == null || host.isEmpty()) {
            return false;
        }

        String name = host.toLowerCase(Locale.ROOT);

        if (name.contains(":")) {
            return name.equals("::1") || name.startsWith("fc") || name.startsWith("fd") || name.startsWith("fe80");
        }

        Matcher ip = IPV4.matcher(name);

        if (ip.matches()) {
            int a = Integer.parseInt(ip.group(1));
            int b = Integer.parseInt(ip.group(2));

            return a == 10 || a == 127 || (a == 169 && b == 254) || (a == 192 && b == 168)
                    || (a == 172 && b >= PRIVATE_172_FIRST && b <= PRIVATE_172_LAST)
                    || (a == 100 && b >= CGNAT_SECOND_OCTET_FIRST && b <= CGNAT_SECOND_OCTET_LAST);
        }

        if (!name.contains(".")) {
            return true;
        }

        for (String suffix : LOCAL_SUFFIXES) {
            if (name.endsWith(suffix)) {
                return true;
            }
        }

        return false;
    }

    private static void readDefaults(@Nullable JSONObject json, Defaults out) {
        if (json == null) {
            return;
        }

        out.assess = optBoolean(json, "assess");
        out.markOnly = optBoolean(json, "mark_only");
        out.answerInMenu = optBoolean(json, "answer_in_menu");
        out.summaryPanel = optBoolean(json, "summary_panel");
        out.autoCaptions = optBoolean(json, "auto_captions");
    }

    @Nullable
    private static Boolean optBoolean(JSONObject json, String key) {
        return json.has(key) && json.opt(key) instanceof Boolean ? json.optBoolean(key) : null;
    }

    private static URI parseUri(String url) throws SetupException {
        try {
            URI uri = new URI(url);

            if (uri.getHost() == null) {
                throw new SetupException("Not a valid address: " + url);
            }

            return uri;
        } catch (URISyntaxException e) {
            throw new SetupException("Not a valid address: " + url);
        }
    }

    private static String hostOf(URI uri) {
        String host = uri.getHost();

        return host.startsWith("[") && host.endsWith("]") ? host.substring(1, host.length() - 1) : host;
    }

    private static void requireAllowedScheme(URI uri, String host) throws SetupException {
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);

        if (scheme.equals("https")) {
            return;
        }

        if (scheme.equals("http") && isPrivateHost(host)) {
            return;
        }

        throw new SetupException(scheme.equals("http") ? "http is only allowed for local network addresses" : "Use an https address");
    }

    private static String stripTrailingSlash(String url) {
        return url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
    }
}
