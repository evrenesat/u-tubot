package com.liskovsoft.smartyoutubetv2.common.app.models.playback.manager;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.SeekBarSegment;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.ChatReceiver;
import com.liskovsoft.smartyoutubetv2.common.diagnostics.VideoStart;

import java.util.List;

public interface PlayerUI {
    int BUTTON_OFF = 0;
    int BUTTON_ON = 1;
    int BUTTON_DISABLED = -1;
    void updateSuggestions(VideoGroup group);
    void removeSuggestions(VideoGroup group);
    int getSuggestionsIndex(VideoGroup group);
    VideoGroup getSuggestionsByIndex(int index);
    void focusSuggestedItem(int index);
    void focusSuggestedItem(Video video);
    void resetSuggestedPosition();
    boolean isSuggestionsEmpty();
    void clearSuggestions();
    void showOverlay(boolean show);
    boolean isOverlayShown();
    void showSuggestions(boolean show);
    boolean isSuggestionsShown();
    void showControls(boolean show);
    boolean isControlsShown();
    int getButtonState(int buttonId);
    void setButtonState(int buttonId, int buttonState);
    void setButtonLabel(int buttonId, CharSequence label);
    void setChannelIcon(String iconUrl);
    void setSeekPreviewTitle(String title);
    void setNextTitle(Video nextVideo);
    void showDebugInfo(boolean show);
    /**
     * Where the time of the video's start went, as a graph (see VideoStarts). Null hides it.
     */
    void showStartGraph(@Nullable VideoStart start);
    void showSubtitles(boolean show);
    void loadStoryboard();
    void setTitle(String title);
    void showProgressBar(boolean show);
    void setSeekBarSegments(List<SeekBarSegment> segments);
    void updateEndingTime();
    void setChatReceiver(ChatReceiver chatReceiver);
}
