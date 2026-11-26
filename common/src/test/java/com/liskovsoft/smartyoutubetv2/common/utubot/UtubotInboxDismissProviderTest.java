package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.dialogs.menu.providers.channelgroup.UtubotInboxDismissProvider;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.InboxKind;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/**
 * The "Hide" entry of an Inbox tile (u-tubot #160): it is offered only on the Inbox tiles, never on a normal card.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotInboxDismissProviderTest {
    private final Context mContext = RuntimeEnvironment.getApplication();

    @Test
    public void itIsOfferedOnlyOnAnInboxTile() {
        UtubotInboxDismissProvider provider = new UtubotInboxDismissProvider(mContext, 3);

        Video inboxTile = new Video();
        inboxTile.inboxKind = InboxKind.CUT;

        Video normal = new Video();
        normal.videoId = "dQw4w9WgXcQ";
        normal.inboxKind = null;

        assertTrue(provider.isEnabled(inboxTile));
        assertFalse(provider.isEnabled(normal));
        assertFalse(provider.isEnabled(null));
    }

    @Test
    public void itIsAVideoMenuEntry() {
        UtubotInboxDismissProvider provider = new UtubotInboxDismissProvider(mContext, 3);

        assertEquals(UtubotInboxDismissProvider.MENU_TYPE_VIDEO, provider.getMenuType());
        assertEquals(R.string.utubot_inbox_dismiss, provider.getTitleResId());
    }
}
