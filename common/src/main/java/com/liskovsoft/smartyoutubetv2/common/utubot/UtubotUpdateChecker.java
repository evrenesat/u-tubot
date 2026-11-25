package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;
import android.content.pm.PackageManager;
import android.net.Uri;

import androidx.annotation.Nullable;

import com.liskovsoft.appupdatechecker2.AppUpdateChecker;
import com.liskovsoft.appupdatechecker2.AppUpdateCheckerListener;
import com.liskovsoft.appupdatechecker2.other.SettingsManager;
import com.liskovsoft.sharedutils.helpers.FileHelpers;
import com.liskovsoft.sharedutils.helpers.Helpers;
import com.liskovsoft.sharedutils.mylogger.Log;

import java.util.ArrayList;
import java.util.Collections;
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
    static final String NO_DOWNLOAD = "The update file offers no download";
    private final Context mContext;
    private final SettingsManager mSettingsManager;
    private int mLatestVersionNumber;

    public UtubotUpdateChecker(Context context, AppUpdateCheckerListener listener) {
        super(context, listener);
        mContext = context.getApplicationContext();
        mSettingsManager = new SettingsManager(context);
    }

    @Override
    public void onChangelogReceived(boolean isLatestVersion, String latestVersionName, int latestVersionNumber, List<String> changelog,
                                    Uri[] downloadUris) {
        mLatestVersionNumber = latestVersionNumber;
        // The channel's versionCode is what decides, as the backend publishes one per release: a version name can be shared
        // (the build's -dev suffix, or an older manifest) while the code already grew.
        boolean isNewer = isNewer(getInstalledVersionCode(), latestVersionNumber, !isLatestVersion);

        if (!isNewer) {
            super.onChangelogReceived(true, latestVersionName, latestVersionNumber, null, downloadUris);
            return;
        }

        if (downloadUris == null) {
            onCheckError(new IllegalStateException(NO_DOWNLOAD));
            return;
        }

        discardCachedApkOfAnotherCode(latestVersionName, latestVersionNumber);
        Uri[] allowed = allowedDownloads(downloadUris);

        if (allowed.length == 0) {
            Log.e(TAG, "No download of %s is allowed (https, or http for a private host): %d listed", latestVersionName, downloadUris.length);
            onCheckError(new IllegalStateException(NO_SAFE_DOWNLOAD));
            return;
        }

        super.onChangelogReceived(false, latestVersionName, latestVersionNumber,
                changelog != null ? changelog : Collections.emptyList(), allowed);
    }

    public int getLatestVersionNumber() {
        return mLatestVersionNumber;
    }

    private void discardCachedApkOfAnotherCode(String latestVersionName, int latestVersionNumber) {
        if (!Helpers.equals(latestVersionName, mSettingsManager.getLatestVersionName()) ||
                mSettingsManager.getLatestVersionNumber() == latestVersionNumber) {
            return;
        }

        Log.d(TAG, "Cached apk of %s is code %d, not the offered %d: downloading it again", latestVersionName,
                mSettingsManager.getLatestVersionNumber(), latestVersionNumber);
        FileHelpers.delete(mSettingsManager.getApkPath());
        mSettingsManager.setApkPath(null);
        mSettingsManager.setLatestVersionName(null);
        mSettingsManager.setLatestVersionNumber(0);
    }

    /**
     * Whether the channel's version is newer than the installed one. With both codes known (they are always on this channel),
     * the code decides; a manifest without one falls back to the version name comparison the shared checker made.
     */
    static boolean isNewer(int installedVersionCode, int latestVersionCode, boolean isNameNewer) {
        if (installedVersionCode > 0 && latestVersionCode > 0) {
            return latestVersionCode > installedVersionCode;
        }

        return isNameNewer;
    }

    /**
     * The installed app's versionCode, 0 when it can't be read (the name comparison is used then)
     */
    int getInstalledVersionCode() {
        try {
            return mContext.getPackageManager().getPackageInfo(mContext.getPackageName(), 0).versionCode;
        } catch (PackageManager.NameNotFoundException e) {
            return 0;
        }
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
