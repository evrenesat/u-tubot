package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.content.Context;

import androidx.leanback.widget.Action;
import androidx.core.content.ContextCompat;

import com.liskovsoft.smartyoutubetv2.tv.R;

/**
 * The player's "Subtitles" button for a film: the file's own tracks and the subtitles from the internet in one picker, with a delay
 * (see UtubotFilmSubtitlesController). It stands in for the closed captions button of a video.
 */
public class UtubotFilmSubtitlesAction extends Action {
    public UtubotFilmSubtitlesAction(Context context) {
        super(R.id.action_utubot_films_subtitles);
        setIcon(ContextCompat.getDrawable(context, R.drawable.lb_ic_cc));
        setLabel1(context.getString(R.string.utubot_films_subtitles));
    }
}
