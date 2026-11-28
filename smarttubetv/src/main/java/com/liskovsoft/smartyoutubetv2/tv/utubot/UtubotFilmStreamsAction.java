package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.content.Context;

import androidx.core.content.ContextCompat;
import androidx.leanback.widget.Action;

import com.liskovsoft.smartyoutubetv2.tv.R;

/**
 * The player's "Streams" button for a film: opens the list of the title's other streams (see UtubotFilmStreamsController).
 */
public class UtubotFilmStreamsAction extends Action {
    public UtubotFilmStreamsAction(Context context) {
        super(R.id.action_utubot_films_streams);
        setIcon(ContextCompat.getDrawable(context, R.drawable.settings_utubot));
        setLabel1(context.getString(R.string.utubot_films_streams));
    }
}
