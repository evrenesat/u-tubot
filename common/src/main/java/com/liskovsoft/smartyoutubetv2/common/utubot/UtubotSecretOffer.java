package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.views.ViewManager;

/**
 * The one question before this TV sends a secret it holds to the server (plan decision D2): never silent.
 */
final class UtubotSecretOffer {
    interface Answer {
        void keepOnServer(boolean keep);
    }

    private UtubotSecretOffer() {
    }

    static int questionOf(String name) {
        return name.equals("films_addon_url") ? R.string.utubot_secret_offer_addon : R.string.utubot_secret_offer_token;
    }

    /**
     * @return true when the question is on the screen (not while a video plays or another dialog is open)
     */
    static boolean show(Context context, String name, Answer answer) {
        AppDialogPresenter dialog = AppDialogPresenter.instance(context);

        if (ViewManager.instance(context).isPlayerInForeground() || dialog.isDialogShown()) {
            return false;
        }

        String text = context.getString(questionOf(name));
        OptionItem question = UiOptionItem.from(text);
        question.setEnabled(false);
        final boolean[] answered = {false};
        OptionItem yes = UiOptionItem.from(context.getString(R.string.utubot_secret_offer_yes), option -> {
            answered[0] = true;
            dialog.closeDialog();
            answer.keepOnServer(true);
        });
        OptionItem no = UiOptionItem.from(context.getString(R.string.utubot_secret_offer_no), option -> {
            answered[0] = true;
            dialog.closeDialog();
            answer.keepOnServer(false);
        });

        dialog.appendSingleButton(question);
        dialog.appendSingleButton(yes);
        dialog.appendSingleButton(no);
        // Closed without an answer (Back): asked again at a later round; only "Not now" is remembered
        dialog.enableTransparent(true);
        dialog.enableExpandable(false);
        dialog.showDialog(text);

        return true;
    }
}
