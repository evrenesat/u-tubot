package com.liskovsoft.smartyoutubetv2.common.app.models.playback.controllers;

import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.BasePlayerController;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionCategory;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.FormatItem;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.track.MediaTrack;
import com.liskovsoft.smartyoutubetv2.common.utils.AppDialogUtil;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotFilmPlaybackSettings;

import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

public class HQDialogController extends BasePlayerController {
    private static final String TAG = HQDialogController.class.getSimpleName();
    private static final int VIDEO_FORMATS_ID = 132;
    private static final int AUDIO_FORMATS_ID = 133;
    // NOTE: using map, because same item could be changed time to time
    private final Map<Integer, OptionCategory> mCategories = new LinkedHashMap<>();
    private final Map<Integer, OptionCategory> mCategoriesInt = new LinkedHashMap<>();
    private final Set<Runnable> mHideListeners = new HashSet<>();
    private AppDialogPresenter mAppDialogPresenter;

    @Override
    public void onInit() {
        mAppDialogPresenter = AppDialogPresenter.instance(getContext());
    }

    @Override
    public void onViewResumed() {
        //updateBackgroundPlayback();
    }

    @Override
    public void onButtonClicked(int buttonId, int buttonState) {
        if (buttonId == R.id.lb_control_high_quality) {
            onHighQualityClicked();
        }
    }

    private void onHighQualityClicked() {
        fitVideoIntoDialog();

        boolean film = getVideo() != null && getVideo().isFilm();

        addQualityCategories(film);
        if (isShown(UtubotFilmPlaybackSettings.Option.AUDIO_LANGUAGE_LIST, film)) {
            addAudioLanguage();
        }
        if (isShown(UtubotFilmPlaybackSettings.Option.VIDEO_PRESETS, film)) {
            addPresetsCategory();
        }
        addVideoZoomCategory();
        if (isShown(UtubotFilmPlaybackSettings.Option.NETWORK_ENGINE, film)) {
            addNetworkEngine();
        }
        addVideoBufferCategory();
        addAudioDelayCategory();
        addPitchEffectCategory();
        addSleepTimerCategory();
        //addBackgroundPlaybackCategory();

        appendOptions(mCategoriesInt);
        appendOptions(mCategories);

        mAppDialogPresenter.showDialog(getContext().getString(R.string.playback_settings), this::onDialogHide);
    }

    private static boolean isShown(UtubotFilmPlaybackSettings.Option option, boolean film) {
        return UtubotFilmPlaybackSettings.isShown(option, film);
    }

    private void addQualityCategories(boolean film) {
        if (getPlayer() == null) {
            return;
        }

        List<FormatItem> videoFormats = getPlayer().getVideoFormats();
        String videoFormatsTitle = getContext().getString(R.string.title_video_formats);

        List<FormatItem> audioFormats = getPlayer().getAudioFormats();
        String audioFormatsTitle = getContext().getString(R.string.title_audio_formats);

        if (isShown(UtubotFilmPlaybackSettings.Option.VIDEO_FORMATS, film)) {
            addCategoryInt(OptionCategory.from(
                    VIDEO_FORMATS_ID,
                    OptionCategory.TYPE_RADIO_LIST,
                    videoFormatsTitle,
                    UiOptionItem.from(videoFormats, this::selectFormatOption, getContext().getString(R.string.option_disabled))));
        }
        addCategoryInt(OptionCategory.from(
                AUDIO_FORMATS_ID,
                OptionCategory.TYPE_RADIO_LIST,
                audioFormatsTitle,
                UiOptionItem.from(audioFormats, this::selectFormatOption, getContext().getString(R.string.option_disabled))));
    }

    private void selectFormatOption(OptionItem option) {
        if (getPlayer() == null) {
            return;
        }

        FormatItem formatItem = UiOptionItem.toFormat(option);
        getPlayer().setFormat(formatItem);
        persistFormat(formatItem);

        if (getPlayerData().getFormat(formatItem.getType()).isPreset()) {
            // Preset currently active. Show warning about format reset.
            MessageHelpers.showMessage(getContext(), R.string.video_preset_enabled);
        }

        if (!getPlayer().containsMedia()) {
            getPlayer().reloadPlayback();
        }

        // Make result easily be spotted by the user
        if (formatItem.getType() == FormatItem.TYPE_VIDEO) {
            getPlayer().showOverlay(false);
        }
    }

    private void persistFormat(FormatItem formatItem) {
        if (formatItem.getType() == FormatItem.TYPE_VIDEO) {
            if (!getPlayerData().getFormat(FormatItem.TYPE_VIDEO).isPreset()) {
                getPlayerData().setFormat(formatItem);
            } else {
                getPlayerData().setTempVideoFormat(formatItem);
            }
        } else if (formatItem.getType() == FormatItem.TYPE_AUDIO) {
            // For this video only. The audio format of the other videos is in the settings.
            getPlayerData().setTempAudioFormat(formatItem);

            // A track picked: the sound is on
            if (!formatItem.isDefault() && getPlayerData().isSoundOff()) {
                getPlayerData().setSoundOff(false);
            }
        } else {
            getPlayerData().setFormat(formatItem);
        }
    }

    private void addVideoBufferCategory() {
        if (getPlayer() == null) {
            return;
        }
        addCategoryInt(AppDialogUtil.createVideoBufferCategory(getContext(),
                () -> getPlayer().restartEngine()));
    }

    private void addAudioDelayCategory() {
        if (getPlayer() == null) {
            return;
        }
        addCategoryInt(AppDialogUtil.createAudioDelayCategory(getContext(),
                () -> getPlayer().restartEngine()));
    }

    private void addPitchEffectCategory() {
        addCategoryInt(AppDialogUtil.createPitchEffectCategory(getContext()));
    }

    private void addSleepTimerCategory() {
        addCategoryInt(AppDialogUtil.createSleepTimerCategory(getContext()));
    }

    private void addAudioLanguage() {
        if (getPlayer() == null) {
            return;
        }
        addCategoryInt(AppDialogUtil.createAudioLanguageCategory(getContext(),
                () -> {
                    // The format picked for this video goes on in the language chosen
                    MediaTrack track = FormatItem.toMediaTrack(getPlayerData().getTempAudioFormat());
                    if (track != null) {
                        track.isSaved = true;
                    }

                    if (getPlayer() != null) {
                        getPlayer().restartEngine();
                    }
                }));
    }

    private void addNetworkEngine() {
        if (getPlayer() == null) {
            return;
        }
        addCategoryInt(AppDialogUtil.createNetworkEngineCategory(getContext(),
                () -> getPlayer().restartEngine()));
    }

    private void onDialogHide() {
        //updateBackgroundPlayback();

        for (Runnable listener : mHideListeners) {
            listener.run();
        }

        mHideListeners.clear();
        mCategories.clear();
        mCategoriesInt.clear();
    }

    //private void updateBackgroundPlayback() {
    //    ViewManager.instance(getContext()).blockTop(null);
    //
    //    if (getPlayer() != null) {
    //        getPlayer().setBackgroundMode(getPlayerData().getBackgroundMode());
    //    }
    //}

    //private void addBackgroundPlaybackCategory() {
    //    OptionCategory category =
    //            AppDialogUtil.createBackgroundPlaybackCategory(getContext(), getPlayerData(), GeneralData.instance(getContext()), this::updateBackgroundPlayback);
    //
    //    addCategoryInt(category);
    //}

    private void addPresetsCategory() {
        addCategoryInt(AppDialogUtil.createVideoPresetsCategory(
                getContext(), () -> {
                    if (getPlayer() == null) {
                        return;
                    }

                    FormatItem format = getPlayerData().getFormat(FormatItem.TYPE_VIDEO);
                    getPlayer().setFormat(format);

                    if (!getPlayer().containsMedia()) {
                        getPlayer().reloadPlayback();
                    }

                    // Make result easily be spotted by the user
                    getPlayer().showOverlay(false);
                }
        ));
    }

    private void addVideoZoomCategory() {
        if (getPlayer() == null) {
            return;
        }

        addCategoryInt(AppDialogUtil.createVideoZoomCategory(
                getContext(), () -> {
                    getPlayer().setResizeMode(getPlayerData().getResizeMode());
                    getPlayer().setZoomPercents(getPlayerData().getZoomPercents());

                    // Make result easily be spotted by the user
                    getPlayer().showOverlay(false);
                }));
    }

    private void removeCategoryInt(int id) {
        mCategoriesInt.remove(id);
    }

    private void addCategoryInt(OptionCategory category) {
        mCategoriesInt.put(category.id, category);
    }

    public void removeCategory(int id) {
        mCategories.remove(id);
    }

    public void addCategory(OptionCategory category) {
        mCategories.put(category.id, category);
    }

    public void addOnDialogHide(Runnable listener) {
        mHideListeners.add(listener);
    }

    public void removeOnDialogHide(Runnable listener) {
        mHideListeners.remove(listener);
    }

    private void appendOptions(Map<Integer, OptionCategory> categories) {
        for (OptionCategory category : categories.values()) {
            mAppDialogPresenter.appendCategory(category);
        }
    }
}
