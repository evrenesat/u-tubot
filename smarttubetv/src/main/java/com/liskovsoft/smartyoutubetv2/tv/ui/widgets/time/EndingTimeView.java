package com.liskovsoft.smartyoutubetv2.tv.ui.widgets.time;

import android.annotation.SuppressLint;
import android.content.Context;
import android.graphics.drawable.Drawable;
import android.util.AttributeSet;
import android.view.View;
import android.widget.TextView;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;

import com.liskovsoft.sharedutils.helpers.DateHelper;
import com.liskovsoft.sharedutils.helpers.Helpers;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.PlaybackPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.views.PlaybackView;
import com.liskovsoft.smartyoutubetv2.common.misc.TickleManager;
import com.liskovsoft.smartyoutubetv2.common.misc.TickleManager.TickleListener;
import com.liskovsoft.smartyoutubetv2.common.prefs.common.DataChangeBase.OnDataChange;
import com.liskovsoft.smartyoutubetv2.common.prefs.PlayerData;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCutController;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCutTime;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;
import com.liskovsoft.smartyoutubetv2.tv.R;

@SuppressLint("AppCompatCustomView")
public class EndingTimeView extends TextView implements TickleListener, OnDataChange {
    /** Marks the time as the end of the playing cut rather than of the full video */
    private static final String CUT_MARKER = "\u2702";
    private final Runnable mUpdateHandler = this::update;
    private TickleManager mTickleManager;
    private PlayerData mPlayerData;
    private boolean mIconIsSet;

    public EndingTimeView(Context context) {
        super(context);
        init();
    }

    public EndingTimeView(Context context, AttributeSet attrs) {
        super(context, attrs);
        init();
    }

    public EndingTimeView(Context context, AttributeSet attrs, int defStyleAttr) {
        super(context, attrs, defStyleAttr);
        init();
    }

    private void init() {
        mTickleManager = TickleManager.instance();
        mPlayerData = PlayerData.instance(getContext());
        updateListener();
    }

    private void setIcon() {
        Drawable drawable = ContextCompat.getDrawable(getContext(), R.drawable.icon_hourglass_bottom);
        if (drawable != null) {
            drawable.setBounds(3, 3, getLineHeight(), getLineHeight()); // add bounds to align vertically
            setCompoundDrawables(drawable, null, null, null);
            mIconIsSet = true;
        }
    }

    private void updateListener() {
        if (getVisibility() == View.VISIBLE) {
            mTickleManager.addListener(this);
            mPlayerData.setOnChange(this);
        } else {
            mTickleManager.removeListener(this);
            mPlayerData.removeOnChange(this);
            removeCallbacks(mUpdateHandler);
        }
    }

    @Override
    public void setVisibility(int visibility) {
        super.setVisibility(visibility);

        updateListener();
    }

    @Override
    public void onDataChange() {
        update();
    }

    @Override
    public void onTickle() {
        update();
    }

    public void update() {
        removeCallbacks(mUpdateHandler);

        if (getVisibility() == View.VISIBLE) {
            PlaybackView playbackView = PlaybackPresenter.instance(getContext()).getView();
            long cutRemainingMs = getCutRemainingMs(playbackView);
            boolean cutTime = cutRemainingMs > 0;
            long remainingTimeMs = applySpeedCorrection(cutTime ? cutRemainingMs : getFullRemainingMs(playbackView));
            long endingTimeMs = remainingTimeMs > 0 ? System.currentTimeMillis() + remainingTimeMs : 0;
            String text = endingTimeMs != 0 ? formatEndingTime(endingTimeMs, cutTime) : null;

            setText(text);

            // Paused or buffering, the ending time moves with the clock. Re-render it when its minute changes.
            // While playing it stands still, and the minute tick and the player events keep it current.
            if (endingTimeMs != 0 && playbackView != null && !playbackView.isPlaying()) {
                postDelayed(mUpdateHandler, 60_000 - endingTimeMs % 60_000);
            }

            //if (endingTime != null) {
            //    // https://stackoverflow.com/questions/5437674/what-unicode-characters-represent-time/9454080
            //    //setText(TextUtils.concat( Utils.icon(getContext(), R.drawable.action_pip, getLineHeight()), " ", endingTime));
            //    setText(String.format("⌛ %s", endingTime));
            //    //setText(String.format("(%s)", endingTime));
            //
            //
            //    // Use external icon
            //    //setText(endingTime);
            //    //if (!mIconIsSet) {
            //    //    setIcon();
            //    //}
            //}
        }
    }

    @Override
    protected void onDetachedFromWindow() {
        super.onDetachedFromWindow();

        // Player has been closed
        mTickleManager.removeListener(this);
        removeCallbacks(mUpdateHandler);
    }

    /**
     * The kept time left in the cut that plays, or 0 when no cut plays (none applied, its skipping off, or the playback is past its
     * last kept part and the full video is on again).
     */
    private long getCutRemainingMs(PlaybackView playbackView) {
        if (!hasPlayback(playbackView)) {
            return 0;
        }

        UtubotCutController cutController = PlaybackPresenter.instance(getContext()).getController(UtubotCutController.class);

        if (cutController == null) {
            return 0;
        }

        Cut cut = cutController.getPlayingCut();

        return cut != null ? UtubotCutTime.remainingKeptMs(cut, playbackView.getPositionMs()) : 0;
    }

    private long getFullRemainingMs(PlaybackView playbackView) {
        return hasPlayback(playbackView) ? playbackView.getDurationMs() - playbackView.getPositionMs() : 0;
    }

    private boolean hasPlayback(PlaybackView playbackView) {
        return playbackView != null && playbackView.getVideo() != null && !playbackView.getVideo().isLive;
    }

    private String formatEndingTime(long endingTimeMs, boolean cutTime) {
        String time = DateHelper.toShortTime(endingTimeMs);

        return cutTime ? String.format("%s %s %s", Helpers.HOURGLASS, time, CUT_MARKER)
                : String.format("%s %s", Helpers.HOURGLASS, time);
    }

    private long applySpeedCorrection(long timeMs) {
        timeMs = (long) (timeMs / mPlayerData.getSpeed());

        return timeMs >= 0 ? timeMs : 0;
    }
}
