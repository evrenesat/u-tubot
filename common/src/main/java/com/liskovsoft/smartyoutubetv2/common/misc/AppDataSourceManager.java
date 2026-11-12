package com.liskovsoft.smartyoutubetv2.common.misc;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettingsPresenter;
import android.content.Context;
import com.liskovsoft.sharedutils.helpers.Helpers;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.SettingsItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.settings.AboutSettingsPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.settings.AboutSimpleSettingsPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.settings.AccountSettingsPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.settings.ContentFilteringSettingsPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.settings.DebuggingSettingsPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.settings.MainUISectionSettingsPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.settings.PlayerSectionSettingsPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.settings.SearchSectionSettingsPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.settings.SystemSectionSettingsPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.settings.UpdatesSettingsPresenter;
import com.liskovsoft.smartyoutubetv2.common.diagnostics.DataSubmitter;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.ExoFormatItem;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.FormatItem;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.FormatItem.VideoPreset;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.TrackSelectorManager;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;

import java.util.ArrayList;
import java.util.List;

public class AppDataSourceManager {
    private static AppDataSourceManager sInstance;

    private AppDataSourceManager() {
    }

    public static AppDataSourceManager instance() {
        if (sInstance == null) {
            sInstance = new AppDataSourceManager();
        }

        return sInstance;
    }

    public List<SettingsItem> getSettingItems(Context context) {
        List<SettingsItem> settingItems = new ArrayList<>();

        settingItems.add(new SettingsItem(
                context.getString(R.string.settings_accounts), () -> AccountSettingsPresenter.instance(context).show(), R.drawable.settings_account));
        settingItems.add(new SettingsItem(
                context.getString(R.string.settings_system), () -> SystemSectionSettingsPresenter.instance(context).show(), R.drawable.settings_app));
        settingItems.add(new SettingsItem(
                context.getString(R.string.settings_main_ui), () -> MainUISectionSettingsPresenter.instance(context).show(), R.drawable.settings_main_ui));
        settingItems.add(new SettingsItem(
                context.getString(R.string.settings_content_filtering), () -> ContentFilteringSettingsPresenter.instance(context).show(), R.drawable.settings_content_filtering));
        settingItems.add(new SettingsItem(
                context.getString(R.string.settings_player), () -> PlayerSectionSettingsPresenter.instance(context).show(), R.drawable.settings_player));
        settingItems.add(new SettingsItem(
                context.getString(R.string.settings_search), () -> SearchSectionSettingsPresenter.instance(context).show(), R.drawable.settings_search));

        if (UtubotSettings.isBuiltIn()) {
            settingItems.add(new SettingsItem(
                    context.getString(R.string.utubot_title), () -> UtubotSettingsPresenter.instance(context).show(), R.drawable.settings_utubot));
        }

        settingItems.add(new SettingsItem(
                context.getString(R.string.settings_updates), () -> UpdatesSettingsPresenter.instance(context).show(), R.drawable.settings_updates));
        // The section is about submitting the diagnostics: without a server (the flavor has none) it is left out
        if (DataSubmitter.isConfigured(context)) {
            settingItems.add(new SettingsItem(
                    context.getString(R.string.settings_debugging), () -> DebuggingSettingsPresenter.instance(context).show(), R.drawable.settings_debugging));
        }

        if (Helpers.equalsAny(context.getPackageName(), Utils.KNOWN_PACKAGES)) {
            settingItems.add(new SettingsItem(
                    context.getString(R.string.settings_about), () -> AboutSettingsPresenter.instance(context).show(), R.drawable.settings_about));
        } else {
            settingItems.add(new SettingsItem(
                    context.getString(R.string.settings_about), () -> AboutSimpleSettingsPresenter.instance(context).show(), R.drawable.settings_about));
        }

        return settingItems;
    }

    public VideoPreset[] getVideoPresets() {
        VideoPreset[] presets = {
                new VideoPreset("144p     30fps    avc", "256,144,30,avc"),
                new VideoPreset("144p     30fps    vp9", "256,144,30,vp9"),
                new VideoPreset("144p     30fps    av01", "256,144,30,av01"),
                new VideoPreset("240p     30fps    avc", "320,240,30,avc"),
                new VideoPreset("240p     30fps    vp9", "320,240,30,vp9"),
                new VideoPreset("240p     30fps    av01", "320,240,30,av01"),
                new VideoPreset("360p     30fps    avc", "640,360,30,avc"),
                new VideoPreset("360p     30fps    vp9", "640,360,30,vp9"),
                new VideoPreset("360p     30fps    av01", "640,360,30,av01"),
                new VideoPreset("360p     60fps    avc", "640,360,60,avc"),
                new VideoPreset("360p     60fps    vp9", "640,360,60,vp9"),
                new VideoPreset("360p     60fps    av01", "640,360,60,av01"),
                new VideoPreset("480p     30fps    avc", "854,480,30,avc"),
                new VideoPreset("480p     30fps    vp9", "854,480,30,vp9"),
                new VideoPreset("480p     30fps    av01", "854,480,30,av01"),
                new VideoPreset("480p     60fps    avc", "854,480,60,avc"),
                new VideoPreset("480p     60fps    vp9", "854,480,60,vp9"),
                new VideoPreset("480p     60fps    av01", "854,480,60,av01"),
                new VideoPreset("720p     30fps    avc", "1280,720,30,avc"),
                new VideoPreset("720p     60fps    avc", "1280,720,60,avc"),
                new VideoPreset("720p     30fps    vp9", "1280,720,30,vp9"),
                new VideoPreset("720p     60fps    vp9", "1280,720,60,vp9"),
                new VideoPreset("720p     30fps    av01", "1280,720,30,av01"),
                new VideoPreset("720p     60fps    av01", "1280,720,60,av01"),
                new VideoPreset("720p     30fps    av01+hdr", "1280,720,30,av01.hdr"),
                new VideoPreset("720p     60fps    av01+hdr", "1280,720,60,av01.hdr"),
                new VideoPreset("1080p    30fps    avc", "1920,1080,30,avc"),
                new VideoPreset("1080p    60fps    avc", "1920,1080,60,avc"),
                new VideoPreset("1080p    30fps    vp9", "1920,1080,30,vp9"),
                new VideoPreset("1080p    60fps    vp9", "1920,1080,60,vp9"),
                new VideoPreset("1080p    30fps    vp9+hdr", "1920,1080,30,vp9.2"),
                new VideoPreset("1080p    60fps    vp9+hdr", "1920,1080,60,vp9.2"),
                new VideoPreset("1080p    30fps    av01", "1920,1080,30,av01"),
                new VideoPreset("1080p    60fps    av01", "1920,1080,60,av01"),
                new VideoPreset("1080p    30fps    av01+hdr", "1920,1080,30,av01.hdr"),
                new VideoPreset("1080p    60fps    av01+hdr", "1920,1080,60,av01.hdr"),
                new VideoPreset("(2K) 1440p    30fps    vp9", "2560,1440,30,vp9"),
                new VideoPreset("(2K) 1440p    60fps    vp9", "2560,1440,60,vp9"),
                new VideoPreset("(2K) 1440p    30fps    vp9+hdr", "2560,1440,30,vp9.2"),
                new VideoPreset("(2K) 1440p    60fps    vp9+hdr", "2560,1440,60,vp9.2"),
                new VideoPreset("(2K) 1440p    30fps    av01", "2560,1440,30,av01"),
                new VideoPreset("(2K) 1440p    60fps    av01", "2560,1440,60,av01"),
                new VideoPreset("(2K) 1440p    30fps    av01+hdr", "2560,1440,30,av01.hdr"),
                new VideoPreset("(2K) 1440p    60fps    av01+hdr", "2560,1440,60,av01.hdr"),
                new VideoPreset("(4K) 2160p    30fps    vp9", "3840,2160,30,vp9"),
                new VideoPreset("(4K) 2160p    60fps    vp9", "3840,2160,60,vp9"),
                new VideoPreset("(4K) 2160p    30fps    vp9+hdr", "3840,2160,30,vp9.2"),
                new VideoPreset("(4K) 2160p    60fps    vp9+hdr", "3840,2160,60,vp9.2"),
                new VideoPreset("(4K) 2160p    30fps    av01", "3840,2160,30,av01"),
                new VideoPreset("(4K) 2160p    60fps    av01", "3840,2160,60,av01"),
                new VideoPreset("(4K) 2160p    30fps    av01+hdr", "3840,2160,30,av01.hdr"),
                new VideoPreset("(4K) 2160p    60fps    av01+hdr", "3840,2160,60,av01.hdr"),
                new VideoPreset("(8K) 4320p    30fps    vp9", "7680,4320,30,vp9"),
                new VideoPreset("(8K) 4320p    60fps    vp9", "7680,4320,60,vp9"),
                new VideoPreset("(8K) 4320p    30fps    vp9+hdr", "7680,4320,30,vp9.2"),
                new VideoPreset("(8K) 4320p    60fps    vp9+hdr", "7680,4320,60,vp9.2"),
                new VideoPreset("(8K) 4320p    30fps    av01", "7680,4320,30,av01"),
                new VideoPreset("(8K) 4320p    60fps    av01", "7680,4320,60,av01"),
                new VideoPreset("(8K) 4320p    30fps    av01+hdr", "7680,4320,30,av01.hdr"),
                new VideoPreset("(8K) 4320p    60fps    av01+hdr", "7680,4320,60,av01.hdr"),
                //new VideoPreset("Adaptive", null)
        };

        return presets;
    }

    /**
     * The audio formats of the settings, by itag, with its DRC and voice boost copies.<br/>
     * A video without the copy chosen plays the original of the itag.
     */
    public List<FormatItem> getAudioFormats() {
        List<FormatItem> formats = new ArrayList<>();

        addAudioFormat(formats, "380", "ac-3", 384_000, false);
        addAudioFormat(formats, "328", "ec-3", 384_000, false);
        addAudioFormat(formats, "251", "opus", 160_000, true);
        addAudioFormat(formats, "140", "mp4a.40.2", 128_000, true);
        addAudioFormat(formats, "250", "opus", 70_000, true);
        addAudioFormat(formats, "249", "opus", 50_000, true);
        addAudioFormat(formats, "139", "mp4a.40.5", 48_000, true);

        return formats;
    }

    private static void addAudioFormat(List<FormatItem> formats, String iTag, String codecs, int bitrate, boolean hasCopies) {
        formats.add(audioFormat(iTag, codecs, bitrate, false, false));

        if (hasCopies) {
            formats.add(audioFormat(iTag, codecs, bitrate, true, false));
            formats.add(audioFormat(iTag, codecs, bitrate, false, true));
        }
    }

    private static FormatItem audioFormat(String iTag, String codecs, int bitrate, boolean isDrc, boolean isVb) {
        return ExoFormatItem.from(FormatItem.TYPE_AUDIO, TrackSelectorManager.RENDERER_INDEX_AUDIO, iTag, codecs,
                -1, -1, -1, null, false, bitrate, isDrc, isVb);
    }
}
