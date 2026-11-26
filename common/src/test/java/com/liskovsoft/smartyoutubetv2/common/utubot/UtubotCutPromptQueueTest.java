package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCutWaitlist.Entry;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;

import org.junit.Before;
import org.junit.Test;

import java.util.ArrayList;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/**
 * The one-at-a-time "Director's cut ready: ... Play?" questions (issue 96): Yes opens the cut's video, No stays where the viewer is,
 * and the next ready cut waits for the answer.
 */
public class UtubotCutPromptQueueTest {
    private final List<UtubotCutPromptQueue.Item> mPresented = new ArrayList<>();
    private final List<UtubotCutPromptQueue.Answer> mAnswers = new ArrayList<>();
    private final List<UtubotCutPromptQueue.Item> mOpened = new ArrayList<>();
    private boolean mCanPresent = true;
    private UtubotCutPromptQueue mQueue;

    @Before
    public void setUp() {
        mQueue = new UtubotCutPromptQueue((item, answer) -> {
            if (!mCanPresent) {
                return false;
            }

            mPresented.add(item);
            mAnswers.add(answer);
            return true;
        }, mOpened::add);
    }

    @Test
    public void yes_opensThatVideoWithItsCut() {
        UtubotCutPromptQueue.Item item = item("cut1", "The demo");
        mQueue.add(item);

        mAnswers.get(0).play();

        assertEquals(1, mOpened.size());
        assertTrue(mOpened.get(0) == item);
        assertTrue(mQueue.isEmpty());
    }

    @Test
    public void no_leavesTheViewerWhereTheyAre() {
        mQueue.add(item("cut1", "The demo"));

        mAnswers.get(0).stay();

        assertTrue(mOpened.isEmpty());
        assertTrue(mQueue.isEmpty());
    }

    @Test
    public void severalReadyCuts_areAskedOneAtATime() {
        UtubotCutPromptQueue.Item first = item("cut1", "The demo");
        UtubotCutPromptQueue.Item second = item("cut2", "The talk");
        mQueue.add(first);
        mQueue.add(second);

        assertEquals(1, mPresented.size());
        assertTrue(mPresented.get(0) == first);

        mAnswers.get(0).stay();

        assertEquals(2, mPresented.size());
        assertTrue(mPresented.get(1) == second);

        mAnswers.get(1).play();

        assertEquals(1, mOpened.size());
        assertTrue(mOpened.get(0) == second);
        assertTrue(mQueue.isEmpty());
        assertEquals(2, mPresented.size());
    }

    @Test
    public void aQuestionThatCannotBeShown_yetIsAskedOnTheNextTry() {
        mCanPresent = false;
        mQueue.add(item("cut1", "The demo"));

        assertTrue(mPresented.isEmpty());
        assertFalse(mQueue.isEmpty());

        mCanPresent = true;
        mQueue.retry();

        assertEquals(1, mPresented.size());
        mAnswers.get(0).stay();
        assertTrue(mQueue.isEmpty());
    }

    @Test
    public void anAnsweredQuestion_isNotAnsweredTwice() {
        mQueue.add(item("cut1", "The demo"));

        mAnswers.get(0).play();
        mAnswers.get(0).stay();

        assertEquals(1, mOpened.size());
        assertTrue(mQueue.isEmpty());
    }

    private static UtubotCutPromptQueue.Item item(String requestId, String title) {
        Cut cut = new Cut();
        cut.videoId = "Lqig_Ui9Hh0";
        cut.label = "No filler";
        cut.keptMs = 192_000;

        return new UtubotCutPromptQueue.Item(new Entry(requestId, cut.videoId, title, 1000), cut);
    }
}
