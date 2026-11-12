package com.liskovsoft.smartyoutubetv2.tv.ui.main;

import android.os.Build.VERSION;

import androidx.annotation.NonNull;
import androidx.multidex.MultiDexApplication;
import androidx.work.Configuration;

import com.bumptech.glide.Glide;
import com.liskovsoft.sharedutils.helpers.Helpers;
import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.BrowseSection;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.BrowsePresenter;
import com.liskovsoft.smartyoutubetv2.common.app.views.AddDeviceView;
import com.liskovsoft.smartyoutubetv2.common.app.views.AppDialogView;
import com.liskovsoft.smartyoutubetv2.common.app.views.BrowseView;
import com.liskovsoft.smartyoutubetv2.common.app.views.ChannelUploadsView;
import com.liskovsoft.smartyoutubetv2.common.app.views.ChannelView;
import com.liskovsoft.smartyoutubetv2.common.app.views.KeywordWordsView;
import com.liskovsoft.smartyoutubetv2.common.app.views.PlaybackView;
import com.liskovsoft.smartyoutubetv2.common.app.views.QrCodeView;
import com.liskovsoft.smartyoutubetv2.common.app.views.ReleaseNotesView;
import com.liskovsoft.smartyoutubetv2.common.app.views.SearchView;
import com.liskovsoft.smartyoutubetv2.common.app.views.SettingsCardsView;
import com.liskovsoft.smartyoutubetv2.common.app.views.SignInView;
import com.liskovsoft.smartyoutubetv2.common.app.views.SplashView;
import com.liskovsoft.smartyoutubetv2.common.app.views.ViewManager;
import com.liskovsoft.smartyoutubetv2.common.app.views.WebBrowserView;
import com.liskovsoft.smartyoutubetv2.common.diagnostics.AppExits;
import com.liskovsoft.smartyoutubetv2.common.prefs.HomeScreenPlaylistsData;
import com.liskovsoft.smartyoutubetv2.common.prefs.NetworkData;
import com.liskovsoft.smartyoutubetv2.common.prefs.PlayerData;
import com.liskovsoft.smartyoutubetv2.common.prefs.PlayerTweaksData;
import com.liskovsoft.smartyoutubetv2.tv.ui.adddevice.AddDeviceActivity;
import com.liskovsoft.smartyoutubetv2.tv.ui.browse.BrowseActivity;
import com.liskovsoft.smartyoutubetv2.tv.ui.channel.ChannelActivity;
import com.liskovsoft.smartyoutubetv2.tv.ui.channeluploads.ChannelUploadsActivity;
import com.liskovsoft.smartyoutubetv2.tv.ui.dialogs.AppDialogActivity;
import com.liskovsoft.smartyoutubetv2.tv.ui.dialogs.AppDialogActivityOpaque;
import com.liskovsoft.smartyoutubetv2.tv.ui.keywords.KeywordWordsActivity;
import com.liskovsoft.smartyoutubetv2.tv.ui.playback.PlaybackActivity;
import com.liskovsoft.smartyoutubetv2.tv.ui.qrcode.QrCodeActivity;
import com.liskovsoft.smartyoutubetv2.tv.ui.releasenotes.ReleaseNotesActivity;
import com.liskovsoft.smartyoutubetv2.tv.ui.search.tags.SearchTagsActivity;
import com.liskovsoft.smartyoutubetv2.tv.ui.skin.SkinRegistry;
import com.liskovsoft.smartyoutubetv2.tv.ui.settingscards.SettingsCardsActivity;
import com.liskovsoft.smartyoutubetv2.tv.ui.signin.SignInActivity;
import com.liskovsoft.smartyoutubetv2.tv.ui.webbrowser.WebBrowserActivity;
import com.liskovsoft.smartyoutubetv2.tv.utubot.UtubotAppHooks;
import com.liskovsoft.youtubeapi.service.YouTubeServiceManager;

import org.conscrypt.Conscrypt;

import java.lang.Thread.UncaughtExceptionHandler;
import java.security.Provider;
import java.security.Security;

public class MainApplication extends MultiDexApplication implements Configuration.Provider { // fix: Didn't find class "com.google.firebase.provider.FirebaseInitProvider"
    static {
        // fix YouTube bandwidth throttling (best - false)???
        // false is better for streams (less buffering)
        System.setProperty("http.keepAlive", "false");
        // fix ipv6 infinite video buffering???
        // Better to remove this fix at all. Users complain about infinite loading.
        //System.setProperty("java.net.preferIPv6Addresses", "true");
        // Another IPv6 fix (no effect)
        // https://stackoverflow.com/questions/1920623/sometimes-httpurlconnection-getinputstream-executes-too-slowly
        //System.setProperty("java.net.preferIPv4Stack" , "true");
    }

    @Override
    public void onCreate() {
        super.onCreate();

        // ByeByeDPI fix
        // https://android-review.googlesource.com/c/platform/external/conscrypt/+/89408/
        // NOTE: Android 10+ (API 29+) uses system Conscrypt TLS; custom Security providers are unnecessary
        // NOTE: May cause 'Unexpected playback error null'
        //if (Build.VERSION.SDK_INT < 29 && Conscrypt.isAvailable()) {
        //    Security.insertProviderAt(Conscrypt.newProvider(), 1);
        //}

        // Important: Initialize the native Conscrypt provider BEFORE reading any configs/SharedPreferences.
        // Otherwise, early disk I/O shifts the ClassLoader on some Android TV devices, causing silent JNI linking errors.
        Provider conscryptProvider = null;
        try {
            conscryptProvider = Conscrypt.newProvider();
        } catch (Throwable e) {
            // UnsatisfiedLinkError
        }

        if (conscryptProvider != null && NetworkData.instance(this).isConscryptEnabled()) {
            try {
                Security.insertProviderAt(conscryptProvider, 1);
            } catch (Throwable e) {
                // UnsatisfiedLinkError
            }
        }

        setupGlobalExceptionHandler();
        setupViewManager();
        UtubotAppHooks.install(this);

        // The channels can be updated with nothing else of the app running
        HomeScreenPlaylistsData.registerChannelsSource(this);
    }

    /**
     * Hidden, the UI's images and the TV poToken's WebView only make the process a bigger target for the low memory killer: it kills
     * one with a foreground service running too (e.g. the remote control's, see AppExits). The images shown stay: Glide keeps the
     * ones in use, and by itself only halves its cache for a hidden UI.
     */
    @Override
    public void onTrimMemory(int level) {
        super.onTrimMemory(level);

        if (level >= TRIM_MEMORY_UI_HIDDEN) {
            Glide.get(this).clearMemory();
            YouTubeServiceManager.instance().trimMemory();
        }
    }

    /**
     * Lazy WorkManager init (auto-init is removed in the manifest).<br/>
     * Fix: 'IllegalStateException: Cannot initialize WorkManager in direct boot mode' thrown at process start on some Android 9 devices.
     * With the lazy init the exception is thrown from WorkManager.getInstance() where it's caught by SafeWorkManager.
     */
    @NonNull
    @Override
    public Configuration getWorkManagerConfiguration() {
        return new Configuration.Builder().build();
    }

    /**
     * The classic activity of each view. The skin picked registers its own (see SkinRegistry).
     */
    private void setupViewManager() {
        SkinRegistry registry = SkinRegistry.instance();

        Class<? extends AppDialogActivity> dialogClass = getDialogClass();

        registry.setClassicRoot(BrowseActivity.class);
        registry.addView(SplashView.class, SplashActivity.class, true); // no parent, because it's root activity
        registry.addView(BrowseView.class, BrowseActivity.class, true); // no parent, because it's root activity
        registry.addView(PlaybackView.class, PlaybackActivity.class, false);
        registry.addView(AppDialogView.class, dialogClass, false);
        registry.addView(SearchView.class, SearchTagsActivity.class, false);
        registry.addView(SignInView.class, SignInActivity.class, false);
        registry.addView(AddDeviceView.class, AddDeviceActivity.class, false);
        registry.addView(ChannelView.class, ChannelActivity.class, false);
        registry.addView(ChannelUploadsView.class, ChannelUploadsActivity.class, false);
        registry.addView(WebBrowserView.class, WebBrowserActivity.class, false);
        registry.addView(QrCodeView.class, QrCodeActivity.class, false);
        registry.addView(KeywordWordsView.class, KeywordWordsActivity.class, false);
        registry.addView(ReleaseNotesView.class, ReleaseNotesActivity.class, false);
        registry.addView(SettingsCardsView.class, SettingsCardsActivity.class, false);
        registry.init(this);
    }

    /**
     * Fix for the 'IllegalStateException: Only fullscreen opaque activities can request orientation'
     */
    private static Class<? extends AppDialogActivity> getDialogClass() {
        Class<? extends AppDialogActivity> dialogClass;

        if (VERSION.SDK_INT == 26
                && Helpers.equalsAny(Helpers.getCrashlyticsDeviceName(),
                "4S806_Z51S1 (Panasonic)",
                "5S72Z_G20S (Panasonic)",
                "9S60Z_ZQ21S (Panasonic)",
                "Android Smart TV (MStar)",
                "Xgimi TV (Xgimi Technology Co.,Ltd)"
        )) {
            // The fix: Only fullscreen opaque activities can request orientation
            dialogClass = AppDialogActivityOpaque.class;
        } else {
            dialogClass = AppDialogActivity.class;
        }
        return dialogClass;
    }

    private void setupGlobalExceptionHandler() {
        UncaughtExceptionHandler defaultHandler = Thread.getDefaultUncaughtExceptionHandler();

        if (defaultHandler == null) {
            return;
        }

        Thread.setDefaultUncaughtExceptionHandler((t, e) -> {
            if (shouldIgnore(e)) {
                MessageHelpers.showLongMessage(this, e.getMessage());
                return;
            }

            // To the player failure log, before the app dies (see Settings → Debugging)
            AppExits.recordCrash(this, t, e);
            applyCrashFixes(e);
            //e = wrapWithAdditionalInfo(e);

            defaultHandler.uncaughtException(t, e);
        });
    }

    private boolean shouldIgnore(Throwable e) {
        // IllegalStateException: Not allowed to start service Intent { act=android.service.voice.VoiceInteractionService
        // cmp=com.google.android.katniss/.search.serviceapi.KatnissVoiceInteractionService (has extras) }:
        // app is in background uid UidRecord{40e7240 u0a19 CEM idle change:cached procs:1 seq(0,0,0)}

        // java.lang.NoSuchMethodError: No interface method addListener(Ljava/lang/Runnable;Ljava/util/concurrent/Executor;)V
        // in class Lcom/google/common/util/concurrent/ListenableFuture; or its super classes
        // (declaration of 'com.google.common.util.concurrent.ListenableFuture' appears in /system/framework/libsetting.jar)

        // org.chromium.base.JniAndroid$UncaughtExceptionException
        // 1) Caused by java.lang.InterruptedException
        // 2) Caused by java.lang.SecurityException: The calling process has already registered an InputDevicesChangedListener.

        // IllegalArgumentException: Missing android.support.FILE_PROVIDER_PATHS meta-data (Shield Android TV 95%, MiTV-AFKR0 5%)

        // RuntimeException: Error receiving broadcast Intent { act=android.hardware.usb.action.USB_DEVICE_ATTACHED flg=0x10 }
        // Caused by NullPointerException: Attempt to invoke virtual method 'int android.hardware.usb.UsbDevice.getInterfaceCount()' on a null object reference

        return Helpers.containsAny(e.getMessage(),
                "KatnissVoiceInteractionService", "ListenableFuture", "Missing android.support.FILE_PROVIDER_PATHS meta-data",
                "Error receiving broadcast Intent { act=android.hardware.usb.action.USB_DEVICE_ATTACHED flg=0x10 }")
                || e.getClass().getName().startsWith("org.chromium");
    }

    private Throwable wrapWithAdditionalInfo(Throwable e) {
        if (Helpers.equalsAny(e.getMessage(),
                "parameter must be a descendant of this view",
                "Attempt to invoke virtual method 'android.view.ViewGroup$LayoutParams android.view.View.getLayoutParams()' on a null object reference")) {
            Class<?> view = ViewManager.instance(getApplicationContext()).getTopView();
            BrowseSection section = null;

            if (view == BrowseView.class) {
                section = BrowsePresenter.instance(getApplicationContext()).getCurrentSection();
            }

            e = new RuntimeException("A crash in the view " + view.getSimpleName() + ", section id " + (section != null ? section.getId() : "-1"), e);
        }
        return e;
    }

    private void applyCrashFixes(Throwable e) {
        if (e instanceof OutOfMemoryError || e.getCause() instanceof OutOfMemoryError) {
            Class<?> view = ViewManager.instance(getApplicationContext()).getTopView();
            if (view == PlaybackView.class) {
                PlayerTweaksData tweaksData = PlayerTweaksData.instance(getApplicationContext());
                PlayerData playerData = PlayerData.instance(getApplicationContext());
                int playerDataSource = tweaksData.getPlayerDataSource();
                int videoBufferType = playerData.getVideoBufferType();
                if (playerDataSource == PlayerTweaksData.PLAYER_DATA_SOURCE_OKHTTP) {
                    tweaksData.setPlayerDataSource(PlayerTweaksData.PLAYER_DATA_SOURCE_DEFAULT);
                    tweaksData.persistNow();
                } else if (videoBufferType == PlayerData.BUFFER_HIGH || videoBufferType == PlayerData.BUFFER_HIGHEST) {
                    playerData.setVideoBufferType(PlayerData.BUFFER_MEDIUM);
                    playerData.persistNow();
                }
            }
        }
    }
}
