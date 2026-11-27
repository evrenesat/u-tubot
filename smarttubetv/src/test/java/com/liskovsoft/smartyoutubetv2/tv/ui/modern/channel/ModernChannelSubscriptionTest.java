package com.liskovsoft.smartyoutubetv2.tv.ui.modern.channel;

import com.liskovsoft.mediaserviceinterfaces.data.MediaGroup;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;
import com.liskovsoft.smartyoutubetv2.tv.R;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class ModernChannelSubscriptionTest {
    @Test
    public void subscribedState_comesFromTheChannelOrItsSection() {
        Video channel = channel();
        assertFalse(ModernChannelSubscription.isSubscribed(channel));

        channel.isSubscribed = true;
        assertTrue(ModernChannelSubscription.isSubscribed(channel));

        assertTrue(ModernChannelSubscription.isSubscribed(inGroup(MediaGroup.TYPE_SUBSCRIPTIONS)));
        assertTrue(ModernChannelSubscription.isSubscribed(inGroup(MediaGroup.TYPE_CHANNEL_UPLOADS)));
        assertFalse(ModernChannelSubscription.isSubscribed(inGroup(MediaGroup.TYPE_CHANNEL)));
        assertFalse(ModernChannelSubscription.isSubscribed(null));
    }

    @Test
    public void pill_followsTheState() {
        assertEquals(R.drawable.modern_ic_notifications, ModernChannelSubscription.iconOf(false));
        assertEquals(R.drawable.modern_ic_notifications_filled, ModernChannelSubscription.iconOf(true));
        assertEquals(R.string.action_subscribe, ModernChannelSubscription.titleOf(false));
        assertEquals(R.string.action_unsubscribe, ModernChannelSubscription.titleOf(true));
    }

    private static Video channel() {
        Video channel = new Video();
        channel.channelId = "UCtest";
        return channel;
    }

    private static Video inGroup(int type) {
        Video channel = channel();
        VideoGroup group = new VideoGroup();
        group.setType(type);
        channel.setGroup(group);
        return channel;
    }
}
