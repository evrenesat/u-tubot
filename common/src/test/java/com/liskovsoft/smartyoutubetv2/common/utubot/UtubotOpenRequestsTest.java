package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotOpenRequestsTest {
    private final UtubotOpenRequests mRequests = new UtubotOpenRequests();

    @Test
    public void aRequestIsTakenOnce() {
        Video video = new Video();
        mRequests.post(UtubotOpenRequests.Kind.SUMMARY, video, 1000);

        UtubotOpenRequests.Request request = mRequests.take(1500);

        assertNotNull(request);
        assertEquals(UtubotOpenRequests.Kind.SUMMARY, request.kind);
        assertSame(video, request.video);
        assertNull(mRequests.take(1500));
    }

    @Test
    public void aRequestNobodyTookInTimeIsDropped() {
        mRequests.post(UtubotOpenRequests.Kind.ANSWER, new Video(), 1000);

        assertNull(mRequests.take(1000 + UtubotOpenRequests.EXPIRY_MS + 1));
    }

    @Test
    public void theLatestRequestWins() {
        mRequests.post(UtubotOpenRequests.Kind.SUMMARY, new Video(), 1000);
        mRequests.post(UtubotOpenRequests.Kind.ANSWER, new Video(), 1100);

        assertEquals(UtubotOpenRequests.Kind.ANSWER, mRequests.take(1200).kind);
    }

    @Test
    public void clearDropsIt() {
        mRequests.post(UtubotOpenRequests.Kind.SUMMARY, new Video(), 1000);
        mRequests.clear();

        assertNull(mRequests.take(1001));
    }
}
