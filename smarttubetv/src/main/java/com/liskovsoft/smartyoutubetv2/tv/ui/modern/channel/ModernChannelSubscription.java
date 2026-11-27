package com.liskovsoft.smartyoutubetv2.tv.ui.modern.channel;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.tv.R;

public final class ModernChannelSubscription {
    private ModernChannelSubscription() {
    }

    public static boolean isSubscribed(Video channel) {
        return channel != null && (channel.isSubscribed || channel.belongsToSubscriptions() || channel.belongsToChannelUploads());
    }

    public static int iconOf(boolean subscribed) {
        return subscribed ? R.drawable.modern_ic_notifications_filled : R.drawable.modern_ic_notifications;
    }

    public static int titleOf(boolean subscribed) {
        return subscribed ? R.string.action_unsubscribe : R.string.action_subscribe;
    }
}
