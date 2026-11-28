package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.BasePlayerController;
import com.liskovsoft.smartyoutubetv2.common.prefs.PlayerData;

/**
 * The player's Clock button: turns the corner clock, the end time and (over a film) the remaining-time line on and off, and keeps
 * the choice, apart for films and for YouTube (see UtubotClockPolicy).
 */
public class UtubotClockController extends BasePlayerController {
    @Override
    public void onButtonClicked(int buttonId, int buttonState) {
        if (buttonId != R.id.action_utubot_clock || getPlayer() == null) {
            return;
        }

        boolean on = UtubotClockPolicy.toggle(getContext(), PlayerData.instance(getContext()));
        getPlayer().updateEndingTime(); // applies the corner and the line
        MessageHelpers.showMessage(getContext(), on ? R.string.utubot_clock_on : R.string.utubot_clock_off);
    }
}
