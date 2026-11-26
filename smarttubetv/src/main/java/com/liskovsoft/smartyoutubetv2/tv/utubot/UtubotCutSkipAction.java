package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.content.Context;

import com.liskovsoft.smartyoutubetv2.tv.R;
import com.liskovsoft.smartyoutubetv2.tv.ui.playback.actions.TwoStateAction;

/**
 * The player's toggle of the applied cut's skipping: on while the cut skips its cut-out parts, off while they are watchable. The cut
 * stays selected either way. Only added by the built-in flavor pointed at a backend, with a cut applied.
 */
public class UtubotCutSkipAction extends TwoStateAction {
    public UtubotCutSkipAction(Context context) {
        super(context, R.id.action_utubot_cut_skip, R.drawable.settings_utubot);

        String[] labels = new String[2];
        // The labels denote the action taken when clicked: turning skipping off shows the parts, turning it back on skips them
        labels[INDEX_ON] = context.getString(R.string.utubot_cut_skip_show);
        labels[INDEX_OFF] = context.getString(R.string.utubot_cut_skip_skip);
        setLabels(labels);
    }
}
