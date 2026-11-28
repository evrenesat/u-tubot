package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.PlaybackPresenter;
import com.liskovsoft.smartyoutubetv2.common.prefs.PlayerData;

/**
 * Whether the player shows its corner clock, the end time and the remaining-time line. A YouTube video follows the player's own
 * settings. A film has one choice of its own, off until the viewer turns it on with the Clock button, kept apart from YouTube's so
 * turning the clock on over a film does not change what a video shows.
 */
public final class UtubotClockPolicy {
    private UtubotClockPolicy() {
    }

    public static boolean isFilmPlaying(Context context) {
        Video video = PlaybackPresenter.instance(context).getVideo();

        return video != null && video.isFilm();
    }

    public static boolean cornerClock(Context context, PlayerData data) {
        return corner(isFilmPlaying(context), UtubotSettings.instance(context).isFilmClockEnabled(), data.isGlobalClockEnabled());
    }

    public static boolean cornerEndingTime(Context context, PlayerData data) {
        return corner(isFilmPlaying(context), UtubotSettings.instance(context).isFilmClockEnabled(), data.isGlobalEndingTimeEnabled());
    }

    /**
     * The line under the seek bar ("Remaining" or the end time): over a film only with the clock on, then as the player's setting says
     */
    public static boolean timeLine(Context context) {
        return !isFilmPlaying(context) || UtubotSettings.instance(context).isFilmClockEnabled();
    }

    /**
     * What the Clock button shows now: on when anything of the corner is on
     */
    public static boolean isOn(Context context, PlayerData data) {
        return isFilmPlaying(context) ? UtubotSettings.instance(context).isFilmClockEnabled()
                : data.isGlobalClockEnabled() || data.isGlobalEndingTimeEnabled();
    }

    /**
     * @return the new state
     */
    public static boolean toggle(Context context, PlayerData data) {
        boolean on = !isOn(context, data);

        if (isFilmPlaying(context)) {
            UtubotSettings.instance(context).setFilmClockEnabled(on);
        } else {
            data.setGlobalClockEnabled(on);
            data.setGlobalEndingTimeEnabled(on);
        }

        return on;
    }

    /**
     * @param film a film is playing
     * @param filmChoice the viewer's choice for films
     * @param youtubeSetting the player's setting
     */
    static boolean corner(boolean film, boolean filmChoice, boolean youtubeSetting) {
        return film ? filmChoice : youtubeSetting;
    }
}
