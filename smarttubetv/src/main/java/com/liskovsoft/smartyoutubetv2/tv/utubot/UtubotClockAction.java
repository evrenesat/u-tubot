package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.content.Context;

import androidx.core.content.ContextCompat;
import androidx.leanback.widget.Action;

import com.liskovsoft.smartyoutubetv2.tv.R;

/**
 * The player's "Clock" button: the corner clock, the end time and the remaining-time line on or off (see UtubotClockController).
 */
public class UtubotClockAction extends Action {
    public UtubotClockAction(Context context) {
        super(R.id.action_utubot_clock);
        setIcon(ContextCompat.getDrawable(context, R.drawable.modern_ic_schedule));
        setLabel1(context.getString(R.string.utubot_clock));
    }
}
