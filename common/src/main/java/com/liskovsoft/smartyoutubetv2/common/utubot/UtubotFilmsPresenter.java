package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;
import android.content.Intent;

import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.base.BasePresenter;
import com.liskovsoft.smartyoutubetv2.common.utils.SimpleEditDialog;

/**
 * Settings, "Films": the user-facing Real-Debrid films entry (issue 248). Holds the stream addon address and the Real-Debrid token (both shown
 * only as set or not set), an IMDb id, and opens the film screen. The addon address and the token can be keys, so they are entered here on the TV,
 * kept in the app's private preferences and never logged. Unlike the developer entry (the hand-written skip list), this one is always available and
 * is not behind the developer toggle: the token and the addon URL are per user on the device and the backend never sees them.
 */
public class UtubotFilmsPresenter extends BasePresenter<Void> {
    public static final String FILMS_ACTIVITY = "com.liskovsoft.smartyoutubetv2.tv.utubot.films.RealDebridFilmsActivity";
    public static final String EXTRA_IMDB_ID = "imdb_id";
    public static final String EXTRA_SKIPS = "skips";

    private final UtubotSettings mSettings;

    private UtubotFilmsPresenter(Context context) {
        super(context);
        mSettings = UtubotSettings.instance(context);
    }

    public static UtubotFilmsPresenter instance(Context context) {
        return new UtubotFilmsPresenter(context);
    }

    public void show() {
        Context context = getContext();
        AppDialogPresenter dialog = AppDialogPresenter.instance(context);

        dialog.appendSingleButton(UiOptionItem.from(context.getString(R.string.utubot_films_addon), setOrNot(mSettings.getFilmsAddonUrl()),
                option -> edit(R.string.utubot_films_addon, R.string.utubot_films_addon_hint, mSettings::getFilmsAddonUrl, mSettings::setFilmsAddonUrl, true)));
        dialog.appendSingleButton(UiOptionItem.from(context.getString(R.string.utubot_films_token), setOrNot(mSettings.getFilmsRealDebridToken()),
                option -> edit(R.string.utubot_films_token, R.string.utubot_films_token_hint, mSettings::getFilmsRealDebridToken,
                        mSettings::setFilmsRealDebridToken, true)));
        dialog.appendSingleButton(UiOptionItem.from(context.getString(R.string.utubot_films_imdb), dash(mSettings.getFilmsImdbId()),
                option -> edit(R.string.utubot_films_imdb, R.string.utubot_films_imdb_hint, mSettings::getFilmsImdbId, mSettings::setFilmsImdbId, false)));
        dialog.appendSingleButton(UiOptionItem.from(context.getString(R.string.utubot_films_list), option -> openFilms()));
        dialog.showDialog(context.getString(R.string.utubot_films));
    }

    /**
     * The intent that opens the film screen, or null when the addon address and the IMDb id are not both set. Not behind the developer toggle.
     */
    Intent filmsIntent() {
        if (mSettings.getFilmsAddonUrl().isEmpty() || mSettings.getFilmsImdbId().isEmpty()) {
            return null;
        }

        return new Intent().setClassName(getContext(), FILMS_ACTIVITY)
                .putExtra(EXTRA_IMDB_ID, mSettings.getFilmsImdbId())
                .putExtra(EXTRA_SKIPS, mSettings.getFilmsSkips());
    }

    private void openFilms() {
        Context context = getContext();
        Intent intent = filmsIntent();

        if (intent == null) {
            MessageHelpers.showLongMessage(context, context.getString(R.string.utubot_films_missing));
            return;
        }

        AppDialogPresenter.instance(context).closeDialog();
        context.startActivity(intent);
    }

    private void edit(int titleRes, int hintRes, java.util.function.Supplier<String> getter, java.util.function.Consumer<String> setter, boolean secret) {
        Context context = getContext();
        AppDialogPresenter.instance(context).closeDialog();
        SimpleEditDialog.OnChange onChange = newValue -> {
            setter.accept(newValue);
            return true;
        };
        Runnable reopen = this::show;

        if (secret) {
            SimpleEditDialog.showPassword(context, context.getString(titleRes), getter.get(), onChange, reopen);
        } else {
            SimpleEditDialog.show(context, context.getString(titleRes), context.getString(hintRes), getter.get(), onChange, reopen);
        }
    }

    private String setOrNot(String value) {
        return getContext().getString(value.isEmpty() ? R.string.utubot_token_unset : R.string.utubot_token_set);
    }

    private static String dash(String text) {
        return text.isEmpty() ? "-" : text;
    }
}
