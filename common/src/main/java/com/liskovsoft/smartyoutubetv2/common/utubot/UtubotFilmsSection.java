package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;
import android.content.Intent;

import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.smartyoutubetv2.common.R;

/**
 * The Films item of the main home sidebar. It is a rail entry, not a grid: a click opens the films home screen (the grid behind it holds one
 * button, for a D-pad move to the right).
 */
public final class UtubotFilmsSection {
    /** A reserved sidebar id, past the Inbox section (27) and the MediaGroup.TYPE_... ids (MediaGroup is a pinned sibling repo) */
    public static final int ID = 28;

    private UtubotFilmsSection() {
    }

    /**
     * Opens the films home, or says where to turn the entry on.
     */
    public static void open(Context context) {
        if (!UtubotSettings.instance(context).isFilmsDeveloperEnabled()) {
            MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_films_turn_on));
            return;
        }

        context.startActivity(new Intent().setClassName(context, UtubotFilmsDeveloperPresenter.HOME_ACTIVITY).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
    }
}
