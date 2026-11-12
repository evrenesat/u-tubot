package com.liskovsoft.smartyoutubetv2.tv.ui.modern.widgets;

import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Outline;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.Rect;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.text.SpannableString;
import android.text.Spanned;
import android.text.TextUtils;
import android.text.style.ForegroundColorSpan;
import android.util.AttributeSet;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.ViewOutlineProvider;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;
import androidx.core.graphics.ColorUtils;

import com.liskovsoft.smartyoutubetv2.common.misc.FormatInfoPrefetcher;
import com.liskovsoft.smartyoutubetv2.common.misc.Skins;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.prefs.AiSListFilterData;
import com.liskovsoft.smartyoutubetv2.common.prefs.MainUIData;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;
import com.liskovsoft.smartyoutubetv2.tv.R;
import com.liskovsoft.smartyoutubetv2.tv.presenter.VideoCardPresenter;
import com.liskovsoft.smartyoutubetv2.tv.ui.modern.common.ModernColorScheme;
import com.liskovsoft.smartyoutubetv2.tv.ui.modern.common.ModernStyle;
import com.liskovsoft.smartyoutubetv2.tv.ui.modern.common.ModernTheme;
import com.liskovsoft.smartyoutubetv2.tv.ui.modern.common.ModernTiles;
import com.liskovsoft.smartyoutubetv2.tv.ui.widgets.embedplayer.EmbedPlayerView;
import com.liskovsoft.smartyoutubetv2.tv.util.ViewUtil;

/**
 * Tile of a video, a playlist or a channel.<br/>
 * Rounded thumbnail (circle for channels) with duration badge and resume bar, title and two metadata lines.
 * The focus ring and the playlist stack are drawn outside of the thumbnail bounds.
 */
public class ModernVideoCard extends LinearLayout {
    public static final int KIND_VIDEO = 0;
    public static final int KIND_PLAYLIST = 1;
    public static final int KIND_CHANNEL = 2;
    private static final long PREVIEW_START_DELAY_MS = 2_000;
    private static final long PREFETCH_DELAY_MS = 1_000;
    private static final long PREVIEW_STOP_DELAY_MS = 500;
    private static final double MIN_TEXT_CONTRAST = 4.5;
    private final Paint mRingPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint mStackPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint mBoxPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF mRect = new RectF();
    private final Path mStackPath = new Path();
    private float mRingInset;
    private float mRingRadius;
    private float mThumbRadius;
    private float mRingAlpha;
    private ValueAnimator mRingAnimator;
    private FrameLayout mThumbFrame;
    private ImageView mThumb;
    private View mDurationBox;
    private ImageView mDurationIcon;
    private TextView mDuration;
    private View mResume;
    private View mResumeProgress;
    private final Rect mTitleClip = new Rect();
    private TextView mTitle;
    private TextView mLine1;
    private LinearLayout mLine2Container;
    private TextView mLabel;
    private TextView mLine2;
    private int mPrimaryColor;
    private int mSecondaryColor;
    // The text area of a video or a playlist: the classic info field (its colors in the scheme, its text colors)
    private int mBoxColor;
    private int mBoxFocusedColor;
    private int mBoxTextColor;
    private int mBoxFocusedTextColor;
    private int mTextPadding;
    private int mTitleBottom;
    private CardMetadata mMeta;
    // The hybrid skin: the text of the classic cards in a box (see ModernStyle)
    // After the View constructor: the context is set
    private final boolean mHybrid = ModernStyle.isHybrid();
    private float mProgress;
    private int mKind = KIND_VIDEO;
    private int mChannelSize;
    private Video mVideo;
    private int mPreviewType = MainUIData.CARD_PREVIEW_DISABLED;
    private boolean mMultilineTitle = true;
    private boolean mTitleAutoScroll;
    private EmbedPlayerView mPreviewPlayer;
    private final Runnable mStartPreview = this::startPreview;
    private final Runnable mPrefetch = this::prefetch;

    public ModernVideoCard(Context context) {
        super(context);
    }

    public ModernVideoCard(Context context, @Nullable AttributeSet attrs) {
        super(context, attrs);
    }

    public ModernVideoCard(Context context, @Nullable AttributeSet attrs, int defStyleAttr) {
        super(context, attrs, defStyleAttr);
    }

    public static int kindOf(Video video) {
        // Channels section with the old look: the channels are items of the uploads group
        if (video.isChannel() || !video.hasVideo() && video.belongsToChannelUploads()) {
            return KIND_CHANNEL;
        }

        if (!video.hasVideo() && (video.hasPlaylist() || video.isPlaylistAsChannel() || video.isMix())) {
            return KIND_PLAYLIST;
        }

        return KIND_VIDEO;
    }

    @Override
    protected void onFinishInflate() {
        super.onFinishInflate();

        setWillNotDraw(false);

        mThumbFrame = findViewById(R.id.modern_card_thumb_frame);
        mThumb = findViewById(R.id.modern_card_thumb);
        mDurationBox = findViewById(R.id.modern_card_duration_box);
        mDurationIcon = findViewById(R.id.modern_card_duration_icon);
        mDuration = findViewById(R.id.modern_card_duration);
        mResume = findViewById(R.id.modern_card_resume);
        mResumeProgress = findViewById(R.id.modern_card_resume_progress);
        mTitle = findViewById(R.id.modern_card_title);
        mLine1 = findViewById(R.id.modern_card_line1);
        mLine2Container = findViewById(R.id.modern_card_line2_container);
        mLabel = findViewById(R.id.modern_card_label);
        mLine2 = findViewById(R.id.modern_card_line2);

        mPrimaryColor = ContextCompat.getColor(getContext(), R.color.modern_text_primary);
        mSecondaryColor = ContextCompat.getColor(getContext(), R.color.modern_text_secondary);
        mBoxColor = ModernColorScheme.cardBackground(getContext(), false);
        mBoxFocusedColor = ModernColorScheme.cardBackground(getContext(), true);
        mBoxTextColor = ContextCompat.getColor(getContext(), R.color.card_default_text);
        mBoxFocusedTextColor = ContextCompat.getColor(getContext(), R.color.card_selected_text_grey);
        mTextPadding = getResources().getDimensionPixelSize(R.dimen.modern_tile_text_padding_hybrid);
        mTitleBottom = getResources().getDimensionPixelSize(R.dimen.modern_tile_title_bottom);

        mRingPaint.setStyle(Paint.Style.STROKE);
        mRingPaint.setStrokeWidth(getResources().getDimension(R.dimen.modern_focus_ring_width));
        mRingPaint.setColor(ContextCompat.getColor(getContext(), R.color.modern_focus_ring));
        mRingInset = getResources().getDimension(R.dimen.modern_focus_ring_inset);
        mRingRadius = getResources().getDimension(R.dimen.modern_focus_ring_radius);
        mThumbRadius = getResources().getDimension(R.dimen.modern_tile_thumb_radius);
        mChannelSize = ModernTiles.size(getContext(), R.dimen.modern_channel_tile_size);
        mStackPaint.setColor(ContextCompat.getColor(getContext(), R.color.modern_white_20));

        // The marquee view adds its own vertical padding: keep the measured title layout
        mTitle.setPadding(0, 0, 0, mTitleBottom);

        if (mHybrid) {
            // The text of the classic cards: the title in their size, not bold, the other lines in their font (TextAppearance.Leanback)
            mTitle.setTextSize(TypedValue.COMPLEX_UNIT_PX, getResources().getDimension(R.dimen.modern_tile_title_size_hybrid));
            mTitle.setTypeface(Typeface.create("sans-serif", Typeface.NORMAL));
            Typeface condensed = Typeface.create("sans-serif-condensed", Typeface.NORMAL);
            mLine1.setTypeface(condensed);
            mLine2.setTypeface(condensed);
            mLabel.setTypeface(condensed);
        }

        applyLineHeight(mTitle, getResources().getDimensionPixelSize(mHybrid
                ? R.dimen.modern_tile_title_line_height_hybrid : R.dimen.modern_tile_title_line_height));
        clipThumbnail();
    }

    public ImageView getThumbView() {
        return mThumb;
    }

    public int getKind() {
        return mKind;
    }

    /**
     * Inline preview of the focused video (SmartTube "card preview" setting).
     */
    public void setPreviewType(int previewType) {
        mPreviewType = previewType;
    }

    /**
     * Card text settings: title on two lines (like the reference) or one,
     * a one line title that doesn't fit scrolls while the card has the focus (at the card text scroll speed).
     */
    public void setTitleOptions(boolean multiline, boolean autoScroll, float scrollSpeed) {
        mMultilineTitle = multiline;
        mTitleAutoScroll = autoScroll;
        ViewUtil.setTextScrollSpeed(mTitle, scrollSpeed); // card text scroll speed setting
    }

    /**
     * UI tweak setting: square thumbnails (and focus ring) when rounded corners are off.
     */
    public void setRoundedCorners(boolean rounded) {
        float thumbRadius = rounded ? getResources().getDimension(R.dimen.modern_tile_thumb_radius) : 0;
        float ringRadius = rounded ? getResources().getDimension(R.dimen.modern_focus_ring_radius) : getResources().getDimension(R.dimen.modern_focus_ring_width);

        if (thumbRadius != mThumbRadius) {
            mThumbRadius = thumbRadius;
            mRingRadius = ringRadius;
            invalidateThumbOutline();
            invalidate();
        }
    }

    public void bind(Video video) {
        stopPreview(true);
        mVideo = video;
        setTag(R.id.utubot_card_video, video); // read by the Summary panel (see UtubotPanelController)
        mKind = kindOf(video);
        // As the classic channel cards: the "AI" marker before the name of a listed channel
        mTitle.setText(mKind == KIND_CHANNEL && video.aiMarkList != -1 ? VideoCardPresenter.addMark(getContext(), video.getTitle(),
                R.string.aislist_mark, AiSListFilterData.instance(getContext()).getMarkColor(video.aiMarkList), false) : video.getTitle());

        // As the classic cards: the second title shortened for a short, the markers of Hide or mark content before it
        CardMetadata meta = CardMetadata.parse(VideoCardPresenter.getSecondTitle(video));
        mMeta = meta;
        setTextOrHide(mLabel, meta.label);
        setTextOrHide(mLine2, meta.line2);
        mLine2Container.setVisibility(meta.label == null && meta.line2 == null ? View.GONE : View.VISIBLE);
        applyTextPadding();
        // The first line with the markers
        applyTextState(isFocused(), true);

        // The badges of the classic cards: new content, live, else the duration. No "SHORTS" one: a short is known by its shape
        mDuration.setText(video.isShorts && !video.hasNewContent && !video.isLive ? video.badge
                : VideoCardPresenter.getBadgeText(getContext(), video));

        if (VideoCardPresenter.isBadgeHighlighted(video)) {
            mDurationBox.setBackground(ModernColorScheme.liveBackground(getContext()));
        } else {
            mDurationBox.setBackgroundResource(R.drawable.modern_duration_bg);
        }
        mDurationIcon.setVisibility(mKind == KIND_PLAYLIST ? View.VISIBLE : View.GONE);
        mDurationBox.setVisibility(mKind == KIND_CHANNEL || TextUtils.isEmpty(mDuration.getText()) ? View.GONE : View.VISIBLE);

        // Count progress that very close to zero. E.g. when user closed video immediately.
        mProgress = video.percentWatched <= 0 ? 0 : Math.max(video.percentWatched, 1) / 100f;
        mResume.setVisibility(mProgress > 0 && mKind == KIND_VIDEO ? View.VISIBLE : View.GONE);

        int gravity = mKind == KIND_CHANNEL ? Gravity.CENTER_HORIZONTAL : Gravity.START;
        mTitle.setGravity(gravity);
        mLine1.setGravity(gravity | Gravity.CENTER_VERTICAL);
        mLine2Container.setGravity(gravity | Gravity.CENTER_VERTICAL);
        setTitleScrolling(false);

        mStackPaint.setColor(ContextCompat.getColor(getContext(), R.color.modern_white_20));
        invalidateThumbOutline();
        updateResumeProgress();
        invalidate();
    }

    /**
     * Playlist stack color (derived from the thumbnail).
     */
    public void setStackColor(int color) {
        mStackPaint.setColor(color);
        invalidate();
    }

    /**
     * Card size depends on the focus state of its shelf. Channels keep a fixed size.
     */
    public void setThumbSize(int width, int height) {
        if (mKind == KIND_CHANNEL) {
            width = mChannelSize;
            height = mChannelSize;
        }

        setSize(mThumbFrame, width, height);
        setSize(mTitle, width, -1);
        setSize(mLine1, width, -1);
        setSize(mLine2Container, width, -1);
        updateResumeProgress();
    }

    private int titleLines() {
        return mKind == KIND_CHANNEL || !mMultilineTitle ? 1 : 2;
    }

    /**
     * A one line title scrolls while the card has the focus (card text auto scroll setting).<br/>
     * In the hybrid skin, as the classic cards: a title cut at the end of its lines scrolls on one line while the card has the
     * focus, so it can be read. It keeps the height of its lines: nothing below it moves.
     */
    private void setTitleScrolling(boolean scroll) {
        if (!mHybrid) {
            boolean marquee = scroll && mTitleAutoScroll && titleLines() == 1;

            if (marquee) {
                mTitle.setSingleLine(true);
                mTitle.setEllipsize(TextUtils.TruncateAt.MARQUEE);
                mTitle.setMarqueeRepeatLimit(-1);
                mTitle.setSelected(true);
            } else {
                mTitle.setSelected(false);
                mTitle.setSingleLine(false);
                mTitle.setMaxLines(titleLines());
                mTitle.setEllipsize(TextUtils.TruncateAt.END);
            }

            return;
        }

        if (scroll && mTitleAutoScroll && mTitle.getLayout() == null) {
            // Not measured yet: whether it's cut is known after the layout
            mTitle.post(() -> {
                if (isFocused() && mTitle.getLayout() != null) {
                    setTitleScrolling(true);
                }
            });
            return;
        }

        boolean marquee = scroll && mTitleAutoScroll && ViewUtil.isTruncated(mTitle);

        if (marquee) {
            int height = mTitle.getHeight();
            mTitle.setSingleLine(true);
            // After setSingleLine (one line, min and max): the height of the lines it had
            mTitle.setMinHeight(height);
            mTitle.setEllipsize(TextUtils.TruncateAt.MARQUEE);
            mTitle.setMarqueeRepeatLimit(-1);
            mTitle.setSelected(true);
        } else {
            mTitle.setSelected(false);
            mTitle.setSingleLine(false);
            mTitle.setMaxLines(titleLines());
            mTitle.setEllipsize(TextUtils.TruncateAt.END);
            mTitle.setMinHeight(0);
        }
    }

    public int getThumbHeight() {
        return mThumbFrame.getLayoutParams().height;
    }

    @Override
    protected void onFocusChanged(boolean gainFocus, int direction, @Nullable android.graphics.Rect previouslyFocusedRect) {
        super.onFocusChanged(gainFocus, direction, previouslyFocusedRect);

        applyTextState(gainFocus, false);
        invalidate(); // the text area
        animateRing(gainFocus ? 1 : 0);
        setTitleScrolling(gainFocus);

        if (gainFocus) {
            if (mKind == KIND_VIDEO && mVideo != null && mVideo.videoId != null) {
                if (mPreviewType != MainUIData.CARD_PREVIEW_DISABLED) {
                    Utils.postDelayed(mStartPreview, PREVIEW_START_DELAY_MS);
                } else {
                    // The inline preview loads the video itself
                    Utils.postDelayed(mPrefetch, PREFETCH_DELAY_MS);
                }
            }
        } else {
            Utils.removeCallbacks(mPrefetch);
            stopPreview(false);
        }
    }

    @Override
    public boolean performClick() {
        Utils.removeCallbacks(mPrefetch);
        stopPreview(true);
        return super.performClick();
    }

    @Override
    protected void onDetachedFromWindow() {
        stopPreview(true);
        super.onDetachedFromWindow();
    }

    /**
     * The focus rests on the video: load its formats so it opens without waiting.
     */
    private void prefetch() {
        if (mVideo != null && (hasFocus() || isFocused()) && Skins.getTraits().prefetchesFocusedVideo()) {
            FormatInfoPrefetcher.instance().prefetch(mVideo.videoId);
        }
    }

    private void startPreview() {
        if (mVideo == null || !hasFocus() && !isFocused()) {
            return;
        }

        if (mPreviewPlayer == null) {
            mPreviewPlayer = new EmbedPlayerView(getContext());
            mPreviewPlayer.setQuality(EmbedPlayerView.QUALITY_NORMAL);
            mPreviewPlayer.setUseController(false);
            mPreviewPlayer.setMute(mPreviewType == MainUIData.CARD_PREVIEW_MUTED);
            mPreviewPlayer.setBackgroundColor(Color.BLACK);
            mPreviewPlayer.setAlpha(0f);
            // Below the duration badge and the resume bar
            mThumbFrame.addView(mPreviewPlayer, 1, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            mPreviewPlayer.animate().alpha(1f).setDuration(ModernTheme.ANIM_PREVIEW_FADE_MS).setInterpolator(ModernTheme.previewFadeInterpolator());
        }

        mPreviewPlayer.openVideo(mVideo);
    }

    private void stopPreview(boolean immediately) {
        Utils.removeCallbacks(mStartPreview);

        if (mPreviewPlayer == null) {
            return;
        }

        EmbedPlayerView player = mPreviewPlayer;
        mPreviewPlayer = null;

        if (immediately) {
            player.finish();
            mThumbFrame.removeView(player);
        } else {
            player.setMute(true);
            player.animate().alpha(0f).setDuration(ModernTheme.ANIM_FAST_MS);
            Utils.postDelayed(() -> {
                player.finish();
                mThumbFrame.removeView(player);
            }, PREVIEW_STOP_DELAY_MS);
        }
    }

    @Override
    protected void onLayout(boolean changed, int l, int t, int r, int b) {
        super.onLayout(changed, l, t, r, b);

        // A scrolling title draws its text moved: never past its text area (the card doesn't clip its children), so in the
        // box it stays off the edges by the padding
        int left = mTitle.getPaddingLeft();
        int right = mTitle.getWidth() - mTitle.getPaddingRight();

        if (mTitleClip.left != left || mTitleClip.right != right || mTitleClip.height() != mTitle.getHeight()) {
            mTitleClip.set(left, 0, right, mTitle.getHeight());
            mTitle.setClipBounds(mTitleClip);
        }
    }

    /**
     * In the hybrid skin the text area of a video or a playlist is the info field of the classic cards: a box below the
     * thumbnail, one card with it (it fills the rounded corners at the bottom of the thumbnail). A channel has its name on the
     * page, as every tile of the modern skin.
     */
    private boolean hasTextBox() {
        return mHybrid && mKind != KIND_CHANNEL;
    }

    private void applyTextPadding() {
        int padding = hasTextBox() ? mTextPadding : 0;
        mTitle.setPadding(padding, 0, padding, mTitleBottom);
        mLine1.setPadding(padding, 0, padding, 0);
        mLine2Container.setPadding(padding, 0, padding, 0);
    }

    /**
     * The text colors of the classic cards on the box (light on the dark box, dark on the light box of the focused card), the
     * markers in their shade for it
     */
    private void applyTextState(boolean focused, boolean bound) {
        boolean box = hasTextBox();
        int textColor = box ? (focused ? mBoxFocusedTextColor : mBoxTextColor) : mSecondaryColor;
        mTitle.setTextColor(box ? textColor : focused ? mPrimaryColor : mSecondaryColor);
        mLine1.setTextColor(textColor);
        mLine2.setTextColor(textColor);
        mLabel.setTextColor(textColor);
        mLabel.setBackgroundResource(box && focused ? R.drawable.modern_badge_bg_on_light : R.drawable.modern_badge_bg);

        // Without the box the markers have one shade: set once
        if (mVideo != null && mMeta != null && (box || bound)) {
            CharSequence marks = VideoCardPresenter.getMarks(getContext(), mVideo, box && focused);
            setTextOrHide(mLine1, withMarks(box ? readable(marks, focused ? mBoxFocusedColor : mBoxColor) : marks, mMeta.line1));
        }
    }

    /**
     * The markers in the classic shade for the box, lighter on a dark box or darker on a light one when that shade is hard to
     * read on it (e.g. red on a dark box): at least the contrast of normal text (4.5:1).
     */
    @Nullable
    private static CharSequence readable(@Nullable CharSequence marks, int background) {
        if (!(marks instanceof Spanned) || Color.alpha(background) != 255) {
            return marks;
        }

        Spanned spanned = (Spanned) marks;
        ForegroundColorSpan[] spans = spanned.getSpans(0, spanned.length(), ForegroundColorSpan.class);
        SpannableString result = null;

        for (ForegroundColorSpan span : spans) {
            int color = span.getForegroundColor();
            int target = ColorUtils.calculateLuminance(background) < 0.5 ? Color.WHITE : Color.BLACK;
            int adjusted = color;

            for (int step = 1; step <= 20 && ColorUtils.calculateContrast(ColorUtils.setAlphaComponent(adjusted, 255), background) < MIN_TEXT_CONTRAST; step++) {
                adjusted = ColorUtils.blendARGB(color, target, step / 20f);
            }

            if (adjusted != color) {
                if (result == null) {
                    result = new SpannableString(marks);
                }

                int start = result.getSpanStart(span);
                int end = result.getSpanEnd(span);
                result.removeSpan(span);
                result.setSpan(new ForegroundColorSpan(adjusted), start, end, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
            }
        }

        return result != null ? result : marks;
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);

        if (!hasTextBox()) {
            return;
        }

        // Below the children: from behind the rounded bottom of the thumbnail to the end of the card
        float left = mThumbFrame.getLeft();
        float right = mThumbFrame.getRight();
        float top = mThumbFrame.getBottom() - mThumbRadius;
        float bottom = getHeight();
        mBoxPaint.setColor(isFocused() ? mBoxFocusedColor : mBoxColor);
        mRect.set(left, top, right, bottom);
        canvas.drawRoundRect(mRect, mThumbRadius, mThumbRadius, mBoxPaint);
        canvas.drawRect(left, top, right, Math.min(bottom, top + mThumbRadius), mBoxPaint);
    }

    @Override
    protected void dispatchDraw(Canvas canvas) {
        super.dispatchDraw(canvas);

        float left = mThumbFrame.getLeft();
        float top = mThumbFrame.getTop();
        float right = mThumbFrame.getRight();
        // Around the whole card: the thumbnail and its text area
        float bottom = hasTextBox() ? getHeight() : mThumbFrame.getBottom();

        if (mKind == KIND_PLAYLIST) {
            drawStack(canvas, left, top, right);
        }

        if (mRingAlpha <= 0) {
            return;
        }

        float halfStroke = mRingPaint.getStrokeWidth() / 2;
        mRect.set(left - mRingInset + halfStroke, top - mRingInset + halfStroke,
                right + mRingInset - halfStroke, bottom + mRingInset - halfStroke);
        mRingPaint.setAlpha(Math.round(mRingAlpha * 255));
        float radius = mKind == KIND_CHANNEL ? mRect.width() / 2 : mRingRadius - halfStroke;
        canvas.drawRoundRect(mRect, radius, radius, mRingPaint);
    }

    private void drawStack(Canvas canvas, float left, float top, float right) {
        float inset = getResources().getDimension(R.dimen.modern_stack_inset);
        float height = getResources().getDimension(R.dimen.modern_stack_height);
        float gap = getResources().getDimension(R.dimen.modern_stack_gap);
        float radius = getResources().getDimension(R.dimen.modern_stack_radius);
        float stackBottom = top - gap;
        float stackTop = stackBottom - height;

        // Rounded only at the top
        mStackPath.reset();
        mRect.set(left + inset, stackTop, right - inset, stackTop + radius * 2);
        mStackPath.addRoundRect(mRect, new float[] {radius, radius, radius, radius, 0, 0, 0, 0}, Path.Direction.CW);
        canvas.save();
        canvas.clipRect(left + inset, stackTop, right - inset, stackBottom);
        canvas.drawPath(mStackPath, mStackPaint);
        canvas.restore();
    }

    private void animateRing(float target) {
        if (mRingAnimator != null) {
            mRingAnimator.cancel();
        }

        mRingAnimator = ValueAnimator.ofFloat(mRingAlpha, target);
        mRingAnimator.setDuration(ModernTheme.ANIM_FAST_MS);
        mRingAnimator.setInterpolator(ModernTheme.fastInterpolator());
        mRingAnimator.addUpdateListener(animation -> {
            mRingAlpha = (float) animation.getAnimatedValue();
            invalidate();
        });
        mRingAnimator.start();
    }

    private void updateResumeProgress() {
        int width = mThumbFrame.getLayoutParams() != null ? mThumbFrame.getLayoutParams().width : 0;
        ViewGroup.LayoutParams params = mResumeProgress.getLayoutParams();
        params.width = Math.round(width * Math.min(mProgress, 1f));
        mResumeProgress.setLayoutParams(params);
    }

    /**
     * Rounded (or round) thumbnail from Android 5.0, square before.
     */
    private void clipThumbnail() {
        mThumbFrame.setOutlineProvider(new ViewOutlineProvider() {
            @Override
            public void getOutline(View view, Outline outline) {
                if (mKind == KIND_CHANNEL) {
                    outline.setOval(0, 0, view.getWidth(), view.getHeight());
                } else {
                    outline.setRoundRect(0, 0, view.getWidth(), view.getHeight(), mThumbRadius);
                }
            }
        });
        mThumbFrame.setClipToOutline(true);
    }

    private void invalidateThumbOutline() {
        mThumbFrame.invalidateOutline();
    }

    private static void applyLineHeight(TextView view, int lineHeightPx) {
        int fontHeight = view.getPaint().getFontMetricsInt(null);
        view.setLineSpacing(lineHeightPx - fontHeight, 1f);
    }

    private static CharSequence withMarks(@Nullable CharSequence marks, @Nullable CharSequence line) {
        if (TextUtils.isEmpty(marks)) {
            return line;
        }

        return TextUtils.isEmpty(line) ? marks : TextUtils.concat(marks, " " + Video.TERTIARY_TEXT_DELIM + " ", line);
    }

    private static void setTextOrHide(TextView view, CharSequence text) {
        view.setText(text);
        view.setVisibility(TextUtils.isEmpty(text) ? View.GONE : View.VISIBLE);
    }

    private static void setSize(View view, int width, int height) {
        ViewGroup.LayoutParams params = view.getLayoutParams();
        params.width = width;
        if (height > 0) {
            params.height = height;
        }
        view.setLayoutParams(params);
    }
}
