package com.liskovsoft.smartyoutubetv2.tv.presenter;

import android.app.Activity;
import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Typeface;
import android.graphics.drawable.BitmapDrawable;
import android.graphics.drawable.Drawable;
import android.os.Build.VERSION;
import android.text.SpannableString;
import android.text.Spanned;
import android.text.TextUtils;
import android.text.style.ForegroundColorSpan;
import android.text.style.StyleSpan;
import android.util.Pair;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;

import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.WeakHashMap;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;
import androidx.leanback.widget.Presenter;
import com.bumptech.glide.Glide;
import com.bumptech.glide.RequestBuilder;
import com.bumptech.glide.load.DataSource;
import com.bumptech.glide.load.HttpException;
import com.bumptech.glide.load.engine.DiskCacheStrategy;
import com.bumptech.glide.load.engine.GlideException;
import com.bumptech.glide.request.RequestListener;
import com.bumptech.glide.request.target.Target;
import com.liskovsoft.sharedutils.helpers.Helpers;
import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.prefs.AiSListFilterData;
import com.liskovsoft.smartyoutubetv2.common.prefs.CategoryFilterData;
import com.liskovsoft.smartyoutubetv2.common.prefs.CollaborationsData;
import com.liskovsoft.smartyoutubetv2.common.prefs.MainUIData;
import com.liskovsoft.smartyoutubetv2.common.prefs.ExploreTopicsData;
import com.liskovsoft.smartyoutubetv2.common.prefs.ShowsData;
import com.liskovsoft.smartyoutubetv2.common.prefs.StreamedData;
import com.liskovsoft.smartyoutubetv2.common.prefs.TopChannelsData;
import com.liskovsoft.smartyoutubetv2.common.prefs.WatchLaterData;
import com.liskovsoft.smartyoutubetv2.common.utils.CardImageUrls;
import com.liskovsoft.smartyoutubetv2.common.utils.ClickbaitRemover;
import com.liskovsoft.smartyoutubetv2.common.utils.CompactInfo;
import com.liskovsoft.smartyoutubetv2.tv.R;
import com.liskovsoft.smartyoutubetv2.tv.presenter.base.LongClickPresenter;
import com.liskovsoft.smartyoutubetv2.tv.ui.browse.video.GridFragmentHelper;
import com.liskovsoft.smartyoutubetv2.tv.ui.widgets.complexcardview.ComplexImageCardView;
import com.liskovsoft.smartyoutubetv2.tv.util.ViewUtil;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotPolicy;

/*
 * A CardPresenter is used to generate Views and bind Objects to them on demand.
 * It contains an Image CardView
 */
public class VideoCardPresenter extends LongClickPresenter {
    private static final String TAG = VideoCardPresenter.class.getSimpleName();
    // The urls the card images are tried from, and the ones that aren't there, of all the cards
    private static final CardImageUrls sImageUrls = new CardImageUrls();
    private int mDefaultBackgroundColor = -1;
    private int mDefaultTextColor = -1;
    private int mSelectedBackgroundColor = -1;
    private int mSelectedTextColor = -1;
    private int mCardPreviewType;
    private int mThumbQuality;
    private int mWidth;
    private int mHeight;
    private CardHold mHold;
    // The image a card shows: the url asked for, and the one it came from (the original, when that one failed)
    private final Map<View, Pair<String, String>> mShownImages = new WeakHashMap<>();

    /**
     * A new card shows when its image is in, together with the others bound with it (see CardHold)
     */
    public void enableImageHold() {
        enableImageHold(new CardHold());
    }

    /**
     * Shares the hold with the other presenters of the view (e.g. of the shorts, of the rows), so all their cards bound together show together
     */
    public void enableImageHold(CardHold hold) {
        mHold = hold;
    }

    @Override
    public ViewHolder onCreateViewHolder(ViewGroup parent) {
        Context context = parent.getContext();

        mDefaultBackgroundColor =
            ContextCompat.getColor(context, Helpers.getThemeAttr(context, R.attr.cardDefaultBackground));
        mDefaultTextColor =
                ContextCompat.getColor(context, R.color.card_default_text);
        mSelectedBackgroundColor =
                ContextCompat.getColor(context, Helpers.getThemeAttr(context, R.attr.cardSelectedBackground));
        mSelectedTextColor =
                ContextCompat.getColor(context, R.color.card_selected_text_grey);

        mCardPreviewType = getCardPreviewType(context);
        mThumbQuality = getThumbQuality(context);

        boolean isCardMultilineTitleEnabled = isCardMultilineTitleEnabled(context);
        boolean isCardMultilineSubtitleEnabled = isCardMultilineSubtitleEnabled(context);
        boolean isCardTextAutoScrollEnabled = isCardTextAutoScrollEnabled(context);
        float cardTextScrollSpeed = getCardTextScrollSpeed(context);

        updateDimensions(context);

        ComplexImageCardView cardView = new ComplexImageCardView(context) {
            @Override
            public void setSelected(boolean selected) {
                updateCardBackgroundColor(this, selected);
                updateMarkShade(this, selected);
                super.setSelected(selected);
            }
        };

        cardView.setTitleLinesNum(isCardMultilineTitleEnabled ? 2 : 1);
        cardView.setContentLinesNum(isCardMultilineSubtitleEnabled ? 2 : 1);
        cardView.enableTextAutoScroll(isCardTextAutoScrollEnabled);
        cardView.setTextScrollSpeed(cardTextScrollSpeed);
        cardView.setFocusable(true);
        cardView.setFocusableInTouchMode(true);
        cardView.enableBadge(isBadgeEnabled());
        cardView.enableTitle(isTitleEnabled());
        cardView.enableContent(isContentEnabled());
        cardView.setBackgroundColor(mDefaultBackgroundColor); // background is temporarily visible during animations
        //if (VERSION.SDK_INT >= 23 && MainUIData.instance(context).isUiTweakEnabled(MainUIData.UI_TWEAK_ROUNDED_CORNERS)) {
        //    cardView.setForeground(ContextCompat.getDrawable(context, R.drawable.lb_card_outline));
        //}
        updateCardBackgroundColor(cardView, false);
        return new ViewHolder(cardView);
    }

    private void updateCardBackgroundColor(ComplexImageCardView view, boolean selected) {
        int backgroundColor = selected ? mSelectedBackgroundColor : mDefaultBackgroundColor;
        int textColor = selected ? mSelectedTextColor : mDefaultTextColor;

        // Both background colors should be set because the view's
        // background is temporarily visible during animations.
        // NOTE: has visual bug with rounded corners
        //view.setBackgroundColor(backgroundColor);

        View infoField = view.findViewById(R.id.info_field);
        if (infoField != null) {
            infoField.setBackgroundColor(backgroundColor);
        }

        TextView titleText = view.findViewById(R.id.title_text);
        if (titleText != null) {
            titleText.setTextColor(textColor);
        }
        TextView contentText = view.findViewById(R.id.content_text);
        if (contentText != null) {
            contentText.setTextColor(textColor);
        }
    }

    @Override
    public void onBindViewHolder(Presenter.ViewHolder viewHolder, Object item) {
        super.onBindViewHolder(viewHolder, item);

        Video video = (Video) item;

        ComplexImageCardView cardView = (ComplexImageCardView) viewHolder.view;
        Context context = cardView.getContext();
        cardView.setTag(R.id.utubot_card_video, video); // read by the Summary panel (see UtubotPanelController)

        cardView.setTitleText(video.getTitle());
        cardView.setContentText(getContentText(context, video, cardView.isSelected()));
        // Count progress that very close to zero. E.g. when user closed video immediately.
        cardView.setProgress(video.percentWatched > 0 && video.percentWatched < 1 ? 1 : Math.round(video.percentWatched));
        cardView.setBadgeText(getBadgeText(context, video));
        cardView.setBadgeColor(isBadgeHighlighted(video) ?
                ContextCompat.getColor(context, R.color.dark_red) : ContextCompat.getColor(context, R.color.black));

        if (mCardPreviewType != MainUIData.CARD_PREVIEW_DISABLED) {
            cardView.setPreview(video);
            cardView.setMute(mCardPreviewType == MainUIData.CARD_PREVIEW_MUTED);
        }

        cardView.setMainImageDimensions(mWidth, mHeight);

        if (context instanceof Activity && ((Activity) context).isDestroyed()) {
            // Glide.with(context): IllegalArgumentException: You cannot start a load for a destroyed activity
            return;
        }

        String imageUrl = getCardImageUrl(video, mThumbQuality);

        // Bound again in place (e.g. synced): the image it shows stays, rather than blinking while it's loaded again
        if (isImageShown(cardView, imageUrl)) {
            return;
        }

        mShownImages.remove(cardView);

        // A new or recycled card has no image (see onUnbindViewHolder). One bound again in place (e.g. synced) has it, so it isn't hidden.
        boolean isHeld = mHold != null && cardView.getMainImageView().getDrawable() == null;

        if (isHeld) {
            mHold.hold(cardView);
        }

        // A new image of a card bound again in place (e.g. DeArrow's): the one it shows stays till the new one is in
        Drawable shownImage = isHeld ? null : copyOfShownImage(cardView);

        // Each failed url falls back to the next one, the last to the placeholder
        List<String> urls = sImageUrls.get(imageUrl, video.cardImageUrl, video.videoId);
        RequestBuilder<Drawable> request = null;

        for (int i = urls.size() - 1; i >= 0; i--) {
            String url = urls.get(i);
            RequestBuilder<Drawable> fallback = request;

            request = Glide.with(context)
                    //.asBitmap() // disable animation (webp, gif)
                    .load(url)
                    .placeholder(shownImage)
                    .apply(ViewUtil.glideOptions())
                    // A still image, unlike the animated ones the options are for: kept in memory, so a card bound again
                    // (e.g. back in a section) shows it at once rather than reading it from disk or downloading it again
                    .skipMemoryCache(false)
                    // improve image compression on low end devices
                    .override(mWidth, mHeight)
                    // com.liskovsoft.smartyoutubetv2.tv.util.CacheGlideModule
                    // Cache makes app crashing on old android versions
                    .diskCacheStrategy(VERSION.SDK_INT > 21 ? getDiskCacheStrategy(url) : DiskCacheStrategy.NONE)
                    .listener(mErrorListener)
                    .addListener(new ImageListener(cardView, imageUrl, isHeld, fallback == null));

            request = fallback != null ? request.error(fallback) : request.error(R.drawable.card_placeholder); // R.color.lb_grey
        }

        request.into(cardView.getMainImageView());
    }

    @Override
    public void onUnbindViewHolder(Presenter.ViewHolder viewHolder) {
        super.onUnbindViewHolder(viewHolder);

        ComplexImageCardView cardView = (ComplexImageCardView) viewHolder.view;

        if (mHold != null) {
            mHold.drop(cardView);
        }

        mShownImages.remove(cardView);

        // Remove references to images so that the garbage collector can free up memory.
        cardView.setBadgeImage(null);
        cardView.setMainImage(null);

        // Cleanup Glide resources. https://chatgpt.com/share/682120c5-e428-8010-b848-371b2dec0cd5
        Glide.with(cardView.getContext().getApplicationContext()).clear(cardView.getMainImageView());
    }

    /**
     * The second title, shortened for a short (see CompactInfo), after the "AI", "Collab", "Watch later", "Show", "Top channel", "Topic",
     * category ("Music", "Gaming", "Sports", "News", "Tech") and "Streamed" or "Live" markers the video has.
     * The "Streamed" marker takes the word off the date ("Streamed • 5 hours ago").
     */
    private static CharSequence getContentText(Context context, Video video, boolean selected) {
        return addMarks(context, video, getSecondTitle(video), selected);
    }

    /**
     * The second title without the markers: shortened for a short, without the "Streamed" word its marker says instead
     */
    public static CharSequence getSecondTitle(Video video) {
        CharSequence secondTitle = video.isStreamedMarked ? CompactInfo.removeStreamed(video.getSecondTitle()) : video.getSecondTitle();
        return video.isShorts ? CompactInfo.compact(secondTitle) : secondTitle;
    }

    /**
     * Only the markers of the video ("AI • Collab • Streamed"), null when it has none (e.g. for the cards of another skin)
     *
     * @param selected the card has a light background: the markers take their darker shade
     */
    @Nullable
    public static CharSequence getMarks(Context context, Video video, boolean selected) {
        CharSequence marks = addMarks(context, video, null, selected);
        return TextUtils.isEmpty(marks) ? null : marks;
    }

    /**
     * The text after the markers of the video, in the order of the settings
     */
    private static CharSequence addMarks(Context context, Video video, CharSequence text, boolean selected) {
        if (video.isStreamedMarked) {
            text = addMark(context, text, R.string.streamed_label, StreamedData.instance(context).getMarkColor(), selected);
        }

        if (video.isLiveMarked) {
            text = addMark(context, text, R.string.live_label, StreamedData.instance(context).getMarkColor(), selected);
        }

        if (video.categoryMarks != 0) {
            text = addCategoryMarks(context, text, video.categoryMarks, selected);
        }

        if (video.isExploreTopicMarked) {
            text = addMark(context, text, R.string.explore_topic_label, ExploreTopicsData.instance(context).getMarkColor(), selected);
        }

        if (video.isTopChannelMarked) {
            text = addMark(context, text, R.string.top_channel_label, TopChannelsData.instance(context).getMarkColor(), selected);
        }

        if (video.isShowMarked) {
            text = addMark(context, text, R.string.show_label, ShowsData.instance(context).getMarkColor(), selected);
        }

        if (video.isInWatchLater) {
            text = addMark(context, text, R.string.watch_later_label, WatchLaterData.instance(context).getMarkColor(), selected);
        }

        if (video.isCollaboration) {
            text = addMark(context, text, R.string.collaboration_mark, CollaborationsData.instance(context).getMarkColor(), selected);
        }

        if (video.aiMarkList != -1) {
            text = addMark(context, text, R.string.aislist_mark, AiSListFilterData.instance(context).getMarkColor(video.aiMarkList), selected);
        }

        if (video.utubotMark != null) {
            text = addMark(context, text, video.utubotMark, UtubotPolicy.MARK_COLOR, selected);
        }

        return text;
    }

    /**
     * The badge on the image: new content, live, a short (not in the Shorts section, where every card is one), else the
     * video's own (its duration)
     */
    public static String getBadgeText(Context context, Video video) {
        return video.hasNewContent ? context.getString(R.string.badge_new_content) :
                video.isLive ? context.getString(R.string.badge_live) :
                video.isShorts && !video.belongsToShorts() ? context.getString(R.string.header_shorts).toUpperCase(Locale.getDefault()) :
                video.badge;
    }

    /**
     * The badge stands out (dark red in the classic look) for new content, a live or an upcoming video
     */
    public static boolean isBadgeHighlighted(Video video) {
        return video.hasNewContent || video.isLive || video.isUpcoming;
    }

    /**
     * The urls the card images are tried from, and the ones that aren't there, of all the cards (of every skin)
     */
    public static CardImageUrls getImageUrls() {
        return sImageUrls;
    }

    /**
     * In the order of the settings: each marker goes before the text, so the last category comes first
     *
     * @param categoryMarks bits by the index of the filter (see CategoryFilterData.all)
     */
    private static CharSequence addCategoryMarks(Context context, CharSequence text, int categoryMarks, boolean selected) {
        CategoryFilterData[] filters = CategoryFilterData.all(context);

        for (int i = filters.length - 1; i >= 0; i--) {
            if ((categoryMarks & (1 << i)) != 0) {
                text = addMark(context, text, filters[i].getLabelResId(), filters[i].getMarkColor(), selected);
            }
        }

        return text;
    }

    /**
     * @param markColor the saved ARGB color of the marker or {@link AiSListFilterData#MARK_COLOR_OFF} (the card text color)
     */
    public static CharSequence addMark(Context context, CharSequence secondTitle, int markResId, int markColor, boolean selected) {
        return addMark(context, secondTitle, context.getString(markResId), markColor, selected);
    }

    public static CharSequence addMark(Context context, CharSequence secondTitle, String markLabel, int markColor, boolean selected) {
        SpannableString mark = new SpannableString(markLabel);
        mark.setSpan(new StyleSpan(Typeface.BOLD), 0, mark.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);

        if (markColor != AiSListFilterData.MARK_COLOR_OFF) {
            mark.setSpan(new MarkSpan(markColor, selected), 0, mark.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        }

        return !TextUtils.isEmpty(secondTitle) ? TextUtils.concat(mark, " " + Video.TERTIARY_TEXT_DELIM + " ", secondTitle) : mark;
    }

    /**
     * The selected card has a light background, so the markers switch to their darker shade
     */
    private static void updateMarkShade(ComplexImageCardView view, boolean selected) {
        CharSequence result = getMarkShaded(view.getContentText(), selected);

        if (result != null) {
            view.setContentText(result);
        }
    }

    /**
     * @return the text with the markers in the shade of the card state or null when they already are (or there's none)
     */
    static CharSequence getMarkShaded(CharSequence text, boolean selected) {
        if (!(text instanceof Spanned)) {
            return null;
        }

        Spanned spanned = (Spanned) text;
        MarkSpan[] spans = spanned.getSpans(0, spanned.length(), MarkSpan.class);

        if (spans.length == 0 || spans[0].mSelected == selected) {
            return null;
        }

        SpannableString result = new SpannableString(text);

        for (MarkSpan span : spans) {
            int start = result.getSpanStart(span);
            int end = result.getSpanEnd(span);
            result.removeSpan(span);
            result.setSpan(new MarkSpan(span.mColor, selected), start, end, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        }

        return result;
    }

    /**
     * Colors a marker ("AI", "Collab", "Watch later", "Show", "Top channel", "Streamed", "Live") with the shade of the saved color that suits the card background
     */
    private static class MarkSpan extends ForegroundColorSpan {
        private final int mColor;
        private final boolean mSelected;

        MarkSpan(int color, boolean selected) {
            super(AiSListFilterData.getMarkShade(color, selected));
            mColor = color;
            mSelected = selected;
        }
    }

    private void updateDimensions(Context context) {
        Pair<Integer, Integer> dimens = getCardDimensPx(context);

        mWidth = dimens.first;
        mHeight = dimens.second;
    }
    
    protected String getCardImageUrl(Video video, int thumbQuality) {
        return ClickbaitRemover.updateThumbnail(video, thumbQuality);
    }

    /**
     * The downloaded image is kept along with the card's size of it
     */
    protected DiskCacheStrategy getDiskCacheStrategy(String url) {
        return DiskCacheStrategy.ALL;
    }

    protected Pair<Integer, Integer> getCardDimensPx(Context context) {
        return GridFragmentHelper.getCardDimensPx(context, R.dimen.card_width, R.dimen.card_height, MainUIData.instance(context).getVideoGridScale());
    }

    protected boolean isCardTextAutoScrollEnabled(Context context) {
        return MainUIData.instance(context).isCardTextAutoScrollEnabled();
    }

    protected int getCardPreviewType(Context context) {
        return MainUIData.instance(context).getCardPreviewType();
    }

    protected boolean isCardMultilineTitleEnabled(Context context) {
        return MainUIData.instance(context).isCardMultilineTitleEnabled();
    }

    protected boolean isCardMultilineSubtitleEnabled(Context context) {
        return MainUIData.instance(context).isCardMultilineSubtitleEnabled();
    }

    protected float getCardTextScrollSpeed(Context context) {
        return MainUIData.instance(context).getCardTextScrollSpeed();
    }

    protected int getThumbQuality(Context context) {
        return MainUIData.instance(context).getThumbQuality();
    }

    protected boolean isContentEnabled() {
        return true;
    }

    protected boolean isTitleEnabled() {
        return true;
    }

    protected boolean isBadgeEnabled() {
        return true;
    }

    private final RequestListener<Drawable> mErrorListener = new RequestListener<Drawable>() {
        @Override
        public boolean onLoadFailed(@Nullable GlideException e, Object model, Target<Drawable> target, boolean isFirstResource) {
            Log.e(TAG, "Glide load failed: " + e);

            if (model instanceof String && isNotFound(e)) {
                sImageUrls.setMissing((String) model);
            }

            return false;
        }

        @Override
        public boolean onResourceReady(Drawable resource, Object model, Target<Drawable> target, DataSource dataSource, boolean isFirstResource) {
            return false;
        }
    };

    /**
     * The url isn't there (404): the next one is tried right away from now on (see CardImageUrls)
     */
    public static boolean isNotFound(@Nullable GlideException e) {
        if (e == null) {
            return false;
        }

        for (Throwable cause : e.getRootCauses()) {
            if (cause instanceof HttpException && ((HttpException) cause).getStatusCode() == 404) {
                return true;
            }
        }

        return false;
    }

    /**
     * A copy of the image the card shows, or null when it shows none. Not the image itself: its bitmap goes back to Glide's pool
     * when the new load starts.
     */
    @Nullable
    private static Drawable copyOfShownImage(ComplexImageCardView cardView) {
        Drawable shown = cardView.getMainImageView().getDrawable();

        if (shown instanceof BitmapDrawable) {
            Bitmap bitmap = ((BitmapDrawable) shown).getBitmap();

            if (bitmap == null || bitmap.isRecycled()) {
                return null;
            }

            Bitmap.Config config = bitmap.getConfig() != null ? bitmap.getConfig() : Bitmap.Config.ARGB_8888;
            Bitmap copy = bitmap.copy(config, false);

            return copy != null ? new BitmapDrawable(cardView.getResources(), copy) : null;
        }

        Drawable.ConstantState state = shown != null ? shown.getConstantState() : null;

        return state != null ? state.newDrawable(cardView.getResources()) : null;
    }

    private boolean isImageShown(ComplexImageCardView cardView, String imageUrl) {
        Pair<String, String> shown = mShownImages.get(cardView);

        return imageUrl != null && shown != null && cardView.getMainImageView().getDrawable() != null &&
                (imageUrl.equals(shown.first) || imageUrl.equals(shown.second));
    }

    /**
     * Notes the image the card shows, and shows the held card when it's in. Each url falls back to the next one
     * (see onBindViewHolder), so only the failure of the last counts.
     */
    private final class ImageListener implements RequestListener<Drawable> {
        private final ComplexImageCardView mCard;
        private final String mImageUrl;
        private final boolean mIsHeld;
        private final boolean mIsLast;

        ImageListener(ComplexImageCardView card, String imageUrl, boolean isHeld, boolean isLast) {
            mCard = card;
            mImageUrl = imageUrl;
            mIsHeld = isHeld;
            mIsLast = isLast;
        }

        @Override
        public boolean onLoadFailed(@Nullable GlideException e, Object model, Target<Drawable> target, boolean isFirstResource) {
            if (mIsLast && mIsHeld) {
                mHold.ready(mCard);
            }

            return false;
        }

        @Override
        public boolean onResourceReady(Drawable resource, Object model, Target<Drawable> target, DataSource dataSource, boolean isFirstResource) {
            mShownImages.put(mCard, new Pair<>(mImageUrl, model instanceof String ? (String) model : null));

            if (mIsHeld) {
                mHold.ready(mCard);
            }

            return false;
        }
    }

    private final RequestListener<Bitmap> mErrorListener2 = new RequestListener<Bitmap>() {
        @Override
        public boolean onLoadFailed(@Nullable GlideException e, Object model, Target<Bitmap> target, boolean isFirstResource) {
            Log.e(TAG, "Glide load failed: " + e);
            return false;
        }

        @Override
        public boolean onResourceReady(Bitmap resource, Object model, Target<Bitmap> target, DataSource dataSource, boolean isFirstResource) {
            return false;
        }
    };
}
