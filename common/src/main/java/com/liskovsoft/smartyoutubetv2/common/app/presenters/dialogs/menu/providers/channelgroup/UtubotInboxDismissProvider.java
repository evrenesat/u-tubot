package com.liskovsoft.smartyoutubetv2.common.app.presenters.dialogs.menu.providers.channelgroup;

import android.content.Context;

import androidx.annotation.NonNull;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.BrowsePresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.dialogs.menu.VideoMenuPresenter.VideoMenuCallback;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.dialogs.menu.providers.ContextMenuProvider;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotManager;
import com.liskovsoft.smartyoutubetv2.common.utils.AppDialogUtil;
import com.liskovsoft.sharedutils.rx.RxHelper;

import java.util.Collections;

/**
 * The "Hide" entry of an Inbox tile (long-press). Hides the result on the server (a read-only flag, the item can be
 * created again) and removes it from the grid (see UtubotInboxSection): it stays in the user's results but not in the Inbox
 */
public class UtubotInboxDismissProvider extends ContextMenuProvider {
    public UtubotInboxDismissProvider(@NonNull Context context, int idx) {
        super(context, idx);
    }

    @Override
    public int getTitleResId() {
        return R.string.utubot_inbox_dismiss;
    }

    @Override
    public void onClicked(Video item, VideoMenuCallback callback) {
        AppDialogUtil.showConfirmationDialog(getContext(), getContext().getString(R.string.utubot_inbox_dismiss_confirm), () -> {
            // Best-effort: hide the item on the server and locally
            RxHelper.execute(UtubotManager.instance(getContext()).dismissInbox(Collections.singletonList(item.inboxId)));
            BrowsePresenter.instance(getContext()).removeItem(item);
        });
    }

    @Override
    public boolean isEnabled(Video item) {
        return item != null && item.inboxKind != null;
    }

    @Override
    public int getMenuType() {
        return MENU_TYPE_VIDEO;
    }
}
