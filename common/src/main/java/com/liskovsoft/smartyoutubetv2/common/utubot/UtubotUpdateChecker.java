package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;
import android.net.Uri;

import androidx.annotation.Nullable;

import com.liskovsoft.appupdatechecker2.AppUpdateChecker;
import com.liskovsoft.appupdatechecker2.AppUpdateCheckerListener;
import com.liskovsoft.sharedutils.mylogger.Log;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import okhttp3.HttpUrl;

/**
 * The update checker of the built-in flavor. The shared one downloads whatever address update.json lists (it only asks Android
 * whether it is a URL at all: http, file, content, ...). Here the APK addresses are held to the rule of the backend address
 * ({@link UtubotSetup#requireUrl}): https, or http for a private host, before they reach the downloader.
 */
public class UtubotUpdateChecker extends AppUpdateChecker {
    private static final String TAG = UtubotUpdateChecker.class.getSimpleName();
    static final String NO_SAFE_DOWNLOAD = "The update file offers no https download";

    public UtubotUpdateChecker(Context context, AppUpdateCheckerListener listener) {
        super(context, listener);
    }

    @Override
    public void onChangelogReceived(boolean isLatestVersion, String latestVersionName, int latestVersionNumber, List<String> changelog,
                                    Uri[] downloadUris) {
        if (isLatestVersion || downloadUris == null) {
            super.onChangelogReceived(isLatestVersion, latestVersionName, latestVersionNumber, changelog, downloadUris);
            return;
        }

        Uri[] allowed = allowedDownloads(downloadUris);

        if (allowed.length == 0) {
            Log.e(TAG, "No download of %s is allowed (https, or http for a private host): %d listed", latestVersionName, downloadUris.length);
            onCheckError(new IllegalStateException(NO_SAFE_DOWNLOAD));
            return;
        }

        super.onChangelogReceived(isLatestVersion, latestVersionName, latestVersionNumber, changelog, allowed);
    }

    /**
     * The addresses that may be downloaded, in their order
     */
    static Uri[] allowedDownloads(Uri[] uris) {
        List<Uri> allowed = new ArrayList<>();

        for (Uri uri : uris) {
            if (uri != null && isAllowedDownload(uri.toString())) {
                allowed.add(uri);
            } else {
                Log.w(TAG, "Skipping the download address %s", uri != null ? uri.getScheme() + "://" + uri.getHost() : null);
            }
        }

        return allowed.toArray(new Uri[0]);
    }

    /**
     * https, or http for a private host (loopback, LAN, tailnet, local names: the rule of {@link UtubotSetup#isPrivateHost}). The
     * address is read the way the downloader's HTTP client reads it, so what is judged is what is fetched.
     */
    static boolean isAllowedDownload(@Nullable String url) {
        HttpUrl parsed = url == null ? null : HttpUrl.parse(url.trim());

        if (parsed == null) {
            return false;
        }

        String scheme = parsed.scheme().toLowerCase(Locale.ROOT);

        return scheme.equals("https") || (scheme.equals("http") && UtubotSetup.isPrivateHost(parsed.host()));
    }
}
