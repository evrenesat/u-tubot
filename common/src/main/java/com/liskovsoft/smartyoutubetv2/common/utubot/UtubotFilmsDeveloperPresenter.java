package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.base.BasePresenter;
import com.liskovsoft.smartyoutubetv2.common.utils.SimpleEditDialog;

/**
 * Settings, Updates, "Films developer entry" (off by default): the Real-Debrid films spike (issue 211) hand-written skip list, fed through the
 * sponsor block for cut-style playback of a Real-Debrid stream. The addon address, the Real-Debrid token and the IMDb id are entered in the
 * user-facing "Films" entry (issue 248); the skip list stays here, behind the developer toggle. The skip list is entered on the TV, kept in the
 * app's private preferences and never logged.
 */
public class UtubotFilmsDeveloperPresenter extends BasePresenter<Void> {
    private final UtubotSettings mSettings;

    private UtubotFilmsDeveloperPresenter(Context context) {
        super(context);
        mSettings = UtubotSettings.instance(context);
    }

    public static UtubotFilmsDeveloperPresenter instance(Context context) {
        return new UtubotFilmsDeveloperPresenter(context);
    }

    public void show() {
        Context context = getContext();
        AppDialogPresenter dialog = AppDialogPresenter.instance(context);
        dialog.appendSingleButton(UiOptionItem.from(context.getString(R.string.utubot_films_skips), dash(mSettings.getFilmsSkips()),
                option -> edit(R.string.utubot_films_skips, R.string.utubot_films_skips_hint, mSettings::setFilmsSkips)));
        dialog.showDialog(context.getString(R.string.utubot_films_open));
    }

    private void edit(int titleRes, int hintRes, java.util.function.Consumer<String> setter) {
        Context context = getContext();
        AppDialogPresenter.instance(context).closeDialog();
        SimpleEditDialog.OnChange onChange = newValue -> {
            setter.accept(newValue);
            return true;
        };
        SimpleEditDialog.show(context, context.getString(titleRes), context.getString(hintRes), mSettings.getFilmsSkips(), onChange, this::show);
    }

    private static String dash(String text) {
        return text.isEmpty() ? "-" : text;
    }
}
