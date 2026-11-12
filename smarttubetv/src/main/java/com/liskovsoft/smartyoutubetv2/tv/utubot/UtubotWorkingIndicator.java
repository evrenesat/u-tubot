package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.view.View;
import android.view.animation.LinearInterpolator;

import com.liskovsoft.smartyoutubetv2.tv.R;

/**
 * Three pulsing dots that say u-tubot is working. Cheap on a TV: a small view, redrawn a few times per second, and the animation
 * runs only while the indicator is active, attached and shown.
 */
public class UtubotWorkingIndicator extends View {
    private static final int MAX_ALPHA = 255;
    private static final int MIN_ALPHA = 80;
    private static final float MIN_SCALE = 0.55f;
    private final Paint mPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final int mDots;
    private final int mSteps;
    private final int mDotSize;
    private final int mGap;
    private final long mCycleMs;
    private ValueAnimator mAnimator;
    private boolean mIsActive;
    private int mStep;

    public UtubotWorkingIndicator(Context context) {
        super(context);
        mDots = getResources().getInteger(R.integer.utubot_indicator_dots);
        mSteps = getResources().getInteger(R.integer.utubot_indicator_steps);
        mCycleMs = getResources().getInteger(R.integer.utubot_indicator_cycle_ms);
        mDotSize = getResources().getDimensionPixelSize(R.dimen.utubot_indicator_dot_size);
        mGap = getResources().getDimensionPixelSize(R.dimen.utubot_indicator_dot_gap);
        mPaint.setColor(getResources().getColor(R.color.utubot_indicator_dot));
        setFocusable(false);
        setVisibility(GONE);
    }

    /**
     * Shows the dots and animates them, or hides them and stops
     */
    public void setActive(boolean active) {
        mIsActive = active;
        setVisibility(active ? VISIBLE : GONE);
        updateAnimation();
    }

    public boolean isActive() {
        return mIsActive;
    }

    /**
     * Whether the animation runs: it needs the indicator active and on screen
     */
    public boolean isAnimating() {
        return mAnimator != null && mAnimator.isRunning();
    }

    /**
     * How much of its pulse a dot is at: 0 (smallest, faintest) to 1. The dots follow one another around the cycle.
     *
     * @param step the position in the cycle, 0 to steps - 1
     */
    static float pulse(int step, int steps, int dot, int dots) {
        float phase = ((float) step / steps - (float) dot / dots + 1f) % 1f;

        return (float) (0.5 - 0.5 * Math.cos(2 * Math.PI * phase));
    }

    @Override
    protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        setMeasuredDimension(mDots * mDotSize + (mDots - 1) * mGap, mDotSize);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        float radius = mDotSize / 2f;

        for (int dot = 0; dot < mDots; dot++) {
            float pulse = pulse(mStep, mSteps, dot, mDots);
            mPaint.setAlpha(MIN_ALPHA + Math.round((MAX_ALPHA - MIN_ALPHA) * pulse));
            float scale = MIN_SCALE + (1f - MIN_SCALE) * pulse;
            canvas.drawCircle(dot * (mDotSize + mGap) + radius, radius, radius * scale, mPaint);
        }
    }

    @Override
    protected void onAttachedToWindow() {
        super.onAttachedToWindow();
        updateAnimation();
    }

    @Override
    protected void onDetachedFromWindow() {
        super.onDetachedFromWindow();
        updateAnimation();
    }

    @Override
    protected void onVisibilityChanged(View changedView, int visibility) {
        super.onVisibilityChanged(changedView, visibility);
        updateAnimation();
    }

    @Override
    protected void onWindowVisibilityChanged(int visibility) {
        super.onWindowVisibilityChanged(visibility);
        updateAnimation();
    }

    private void updateAnimation() {
        boolean shouldRun = mIsActive && isAttachedToWindow() && getVisibility() == VISIBLE && getWindowVisibility() == VISIBLE;

        if (shouldRun && mAnimator == null) {
            mAnimator = ValueAnimator.ofInt(0, mSteps);
            mAnimator.setDuration(mCycleMs);
            mAnimator.setInterpolator(new LinearInterpolator());
            mAnimator.setRepeatCount(ValueAnimator.INFINITE);
            mAnimator.addUpdateListener(animator -> {
                int step = (int) animator.getAnimatedValue() % mSteps;

                if (step != mStep) {
                    mStep = step;
                    invalidate();
                }
            });
            mAnimator.start();
        } else if (!shouldRun && mAnimator != null) {
            mAnimator.cancel();
            mAnimator = null;
        }
    }
}
