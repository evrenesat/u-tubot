package com.liskovsoft.smartyoutubetv2.common.diagnostics;

import androidx.annotation.Nullable;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * What must not leave the TV in a report: the query and the opaque segments of a URL (a Real-Debrid token sits in the path of an add-on
 * address, a file key in the path of a direct link), the values after token, key, secret, password and authorization, bearer and
 * device tokens, and the exact secrets the app holds. {@link Scrubber} then takes out addresses and emails.
 */
public final class ReportRedaction {
    public static final String MASK = "<redacted>";
    private static final int MIN_SECRET_CHARS = 6;
    private static final int OPAQUE_SEGMENT_CHARS = 20;
    private static final Pattern URL = Pattern.compile("(https?://)([^\\s\"'<>\\\\]+)");
    private static final Pattern OPAQUE_SEGMENT = Pattern.compile("[A-Za-z0-9_~.=%+-]{" + OPAQUE_SEGMENT_CHARS + ",}");
    private static final Pattern NAMED_SECRET = Pattern.compile(
            "(?i)\\b([\\w-]*(?:token|apikey|api_key|secret|password|passwd|authorization|key))(\\s*[=:]\\s*)(?:Bearer\\s+)?[^\\s\"'&,;<>\\\\]+");
    private static final Pattern BEARER = Pattern.compile("(?i)\\bBearer\\s+[A-Za-z0-9._~+/=-]+");
    private static final Pattern DEVICE_TOKEN = Pattern.compile("\\butb_[A-Za-z0-9_-]+");

    private ReportRedaction() {
    }

    /**
     * @param secrets values held by the app (Real-Debrid token, device token, add-on address) removed wherever they appear
     */
    public static String redact(@Nullable String text, String... secrets) {
        if (text == null || text.isEmpty()) {
            return text == null ? "" : text;
        }

        String result = text;

        for (String secret : secrets) {
            if (secret != null && secret.length() >= MIN_SECRET_CHARS) {
                result = result.replace(secret, MASK);
            }
        }

        result = redactUrls(result);
        result = BEARER.matcher(result).replaceAll("Bearer " + MASK);
        result = DEVICE_TOKEN.matcher(result).replaceAll(MASK);
        result = NAMED_SECRET.matcher(result).replaceAll("$1$2" + MASK);

        return result;
    }

    private static String redactUrls(String text) {
        Matcher matcher = URL.matcher(text);
        StringBuffer out = new StringBuffer();

        while (matcher.find()) {
            matcher.appendReplacement(out, Matcher.quoteReplacement(matcher.group(1) + redactRest(matcher.group(2))));
        }

        matcher.appendTail(out);

        return out.toString();
    }

    /**
     * Of a URL after "https://": no user info, the path's opaque or key=value segments masked, the query and fragment gone
     */
    private static String redactRest(String rest) {
        int tail = indexOfAny(rest, '?', '#');
        String query = tail >= 0 ? rest.substring(tail) : "";
        String authorityAndPath = tail >= 0 ? rest.substring(0, tail) : rest;
        int slash = authorityAndPath.indexOf('/');
        String authority = slash >= 0 ? authorityAndPath.substring(0, slash) : authorityAndPath;
        String path = slash >= 0 ? authorityAndPath.substring(slash) : "";
        int at = authority.lastIndexOf('@');

        if (at >= 0) {
            authority = authority.substring(at + 1);
        }

        StringBuilder safe = new StringBuilder(authority);

        for (String segment : path.split("/", -1)) {
            if (segment.isEmpty()) {
                continue;
            }

            safe.append('/').append(segment.indexOf('=') > 0 || OPAQUE_SEGMENT.matcher(segment).matches() && !looksLikeFile(segment) ? MASK : segment);
        }

        if (path.endsWith("/")) {
            safe.append('/');
        }

        return safe + (query.isEmpty() ? "" : query.charAt(0) + MASK);
    }

    /**
     * A name with an extension of a media or subtitle file is shown (a release name is not a secret); the rest of a long opaque
     * segment is
     */
    private static boolean looksLikeFile(String segment) {
        return segment.matches("(?i).*\\.(mkv|mp4|avi|m4v|ts|webm|srt|ass|vtt|sub)$");
    }

    private static int indexOfAny(String text, char... chars) {
        int best = -1;

        for (char c : chars) {
            int index = text.indexOf(c);

            if (index >= 0 && (best < 0 || index < best)) {
                best = index;
            }
        }

        return best;
    }
}
