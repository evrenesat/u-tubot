package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCutWaitlist.Entry;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.Cut;

import java.util.ArrayDeque;
import java.util.Deque;

/**
 * The "Director's cut ready: ... Play?" pop-ups, one at a time (issue 96). A cut that becomes ready waits here until the one before it
 * is answered; Yes opens the video with the cut, No (or Back) leaves the viewer exactly where they are.
 */
public final class UtubotCutPromptQueue {
    /** One ready cut: the order it answers and the cut to apply */
    public static final class Item {
        public final Entry entry;
        public final Cut cut;

        public Item(Entry entry, Cut cut) {
            this.entry = entry;
            this.cut = cut;
        }
    }

    public interface Presenter {
        /**
         * Shows the question. False when it cannot be shown now (no screen, or another dialog is up); the item stays first in line.
         */
        boolean present(Item item, Answer answer);
    }

    public interface Answer {
        void play();

        void stay();
    }

    public interface Opener {
        void open(Item item);
    }

    private final Presenter mPresenter;
    private final Opener mOpener;
    private final Deque<Item> mQueue = new ArrayDeque<>();
    private boolean mShowing;

    public UtubotCutPromptQueue(Presenter presenter, Opener opener) {
        mPresenter = presenter;
        mOpener = opener;
    }

    public void add(Item item) {
        if (item == null) {
            return;
        }

        mQueue.addLast(item);
        pump();
    }

    /**
     * The screen or the dialog that blocked a question is gone (or the retry timer fired): try the first one again.
     */
    public void retry() {
        pump();
    }

    public void clear() {
        mQueue.clear();
        mShowing = false;
    }

    public boolean isEmpty() {
        return mQueue.isEmpty() && !mShowing;
    }

    private void pump() {
        if (mShowing || mQueue.isEmpty()) {
            return;
        }

        Item item = mQueue.peekFirst();
        Answer answer = new Answer() {
            private boolean mAnswered;

            @Override
            public void play() {
                if (mAnswered || !mShowing || mQueue.peekFirst() != item) {
                    return;
                }

                mAnswered = true;
                end(item);
                mOpener.open(item);
                pump();
            }

            @Override
            public void stay() {
                if (mAnswered || !mShowing || mQueue.peekFirst() != item) {
                    return;
                }

                mAnswered = true;
                end(item);
                pump();
            }
        };

        // Set before the call: a presenter that answers at once (a test) still has to find a shown question
        mShowing = true;

        if (!mPresenter.present(item, answer) && mShowing && mQueue.peekFirst() == item) {
            mShowing = false;
        }
    }

    private void end(Item item) {
        mShowing = false;

        if (mQueue.peekFirst() == item) {
            mQueue.removeFirst();
        }
    }
}
