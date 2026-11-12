package com.liskovsoft.smartyoutubetv2.common.utubot;

import androidx.annotation.Nullable;

import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Prompt;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.PromptList;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Summary;

import java.util.Collections;
import java.util.List;

import io.reactivex.android.schedulers.AndroidSchedulers;
import io.reactivex.disposables.Disposable;

/**
 * What the Summary panel shows for the focused video: the prompts to pick from, and the summary of the picked one.
 * The view only draws the state it is given.
 */
public class UtubotPanelModel {
    public enum Phase {
        IDLE, LOADING, READY, FAILED
    }

    public static final class State {
        public final Video video;
        public final Phase phase;
        public final List<Prompt> prompts;
        @Nullable public final String selectedKey;
        @Nullable public final String text;
        @Nullable public final String source;
        @Nullable public final String error;

        State(Video video, Phase phase, List<Prompt> prompts, @Nullable String selectedKey, @Nullable String text, @Nullable String source,
              @Nullable String error) {
            this.video = video;
            this.phase = phase;
            this.prompts = prompts;
            this.selectedKey = selectedKey;
            this.text = text;
            this.source = source;
            this.error = error;
        }
    }

    public interface Listener {
        void onState(State state);
    }

    private final UtubotManager mManager;
    private final Listener mListener;
    private Video mVideo;
    private List<Prompt> mPrompts = Collections.emptyList();
    private String mSelectedKey;
    private Disposable mAction;

    public UtubotPanelModel(UtubotManager manager, Listener listener) {
        mManager = manager;
        mListener = listener;
    }

    /**
     * Starts loading for the video. Whatever was loading before is dropped.
     */
    public void show(Video video) {
        if (video == null || video.videoId == null) {
            return;
        }

        mVideo = video;
        mSelectedKey = mManager.getSessionPrompt();
        publish(Phase.LOADING, null, null, null);
        RxHelper.disposeActions(mAction);
        mAction = mManager.promptsObserve(false)
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(this::onPrompts, error -> {
                    // The summary of the backend's default prompt still works without the list
                    mPrompts = Collections.emptyList();
                    loadSummary();
                });
    }

    /**
     * The prompt stays for the rest of the session
     */
    public void selectPrompt(String key) {
        if (mVideo == null || key == null || key.equals(mSelectedKey)) {
            return;
        }

        mSelectedKey = key;
        mManager.setSessionPrompt(key);
        publish(Phase.LOADING, null, null, null);
        loadSummary();
    }

    public void dispose() {
        RxHelper.disposeActions(mAction);
        mAction = null;
        mVideo = null;
    }

    @Nullable
    public Video getVideo() {
        return mVideo;
    }

    private void onPrompts(PromptList list) {
        mPrompts = list.allPrompts();

        if (mSelectedKey == null || list.find(mSelectedKey) == null) {
            mSelectedKey = list.defaultKey;
        }

        publish(Phase.LOADING, null, null, null);
        loadSummary();
    }

    private void loadSummary() {
        Video video = mVideo;
        RxHelper.disposeActions(mAction);
        mAction = mManager.summaryObserve(video, mSelectedKey)
                .observeOn(AndroidSchedulers.mainThread())
                .subscribe(summary -> onSummary(video, summary),
                        error -> {
                            if (video == mVideo) {
                                publish(Phase.FAILED, null, null, error.getMessage());
                            }
                        });
    }

    private void onSummary(Video video, Summary summary) {
        if (video != mVideo) {
            return;
        }

        if (summary.isFailed() || summary.isPending()) {
            publish(Phase.FAILED, null, summary.source, summary.error);
        } else {
            publish(Phase.READY, summary.text, summary.source, null);
        }
    }

    private void publish(Phase phase, @Nullable String text, @Nullable String source, @Nullable String error) {
        mListener.onState(new State(mVideo, phase, mPrompts, mSelectedKey, text, source, error));
    }
}
