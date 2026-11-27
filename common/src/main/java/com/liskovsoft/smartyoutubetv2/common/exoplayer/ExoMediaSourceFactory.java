package com.liskovsoft.smartyoutubetv2.common.exoplayer;

import android.annotation.SuppressLint;
import android.content.Context;
import android.net.Uri;
import android.text.TextUtils;
import androidx.annotation.NonNull;
import com.google.android.exoplayer2.C;
import com.google.android.exoplayer2.ext.cronet.CronetDataSourceFactory;
import com.google.android.exoplayer2.ext.cronet.CronetEngineWrapper;
import com.google.android.exoplayer2.ext.okhttp.OkHttpDataSourceFactory;
import com.google.android.exoplayer2.extractor.DefaultExtractorsFactory;
import com.google.android.exoplayer2.source.ExtractorMediaSource;
import com.google.android.exoplayer2.source.MediaSource;
import com.google.android.exoplayer2.source.dash.DashChunkSource;
import com.google.android.exoplayer2.source.dash.DashMediaSource;
import com.google.android.exoplayer2.source.dash.DefaultDashChunkSource;
import com.google.android.exoplayer2.source.dash.manifest.DashManifest;
import com.google.android.exoplayer2.source.dash.manifest.DashManifestParser;
import com.google.android.exoplayer2.source.dash.manifest.DashManifestParser2;
import com.google.android.exoplayer2.source.dash.manifest.Period;
import com.google.android.exoplayer2.source.dash.manifest.ProgramInformation;
import com.google.android.exoplayer2.source.dash.manifest.UtcTimingElement;
import com.google.android.exoplayer2.source.hls.HlsMediaSource;
import com.google.android.exoplayer2.source.sabr.DefaultSabrChunkSource;
import com.google.android.exoplayer2.source.sabr.SabrChunkSource;
import com.google.android.exoplayer2.source.sabr.SabrMediaSource;
import com.google.android.exoplayer2.source.sabr.manifest.SabrManifest;
import com.google.android.exoplayer2.source.sabr.manifest.SabrManifestParser;
import com.google.android.exoplayer2.source.smoothstreaming.DefaultSsChunkSource;
import com.google.android.exoplayer2.source.smoothstreaming.SsMediaSource;
import com.google.android.exoplayer2.upstream.DataSource;
import com.google.android.exoplayer2.upstream.DefaultBandwidthMeter;
import com.google.android.exoplayer2.upstream.DefaultDataSourceFactory;
import com.google.android.exoplayer2.upstream.DefaultHttpDataSourceFactory;
import com.google.android.exoplayer2.upstream.HttpDataSource;
import com.google.android.exoplayer2.util.Util;
import com.liskovsoft.mediaserviceinterfaces.data.MediaItemFormatInfo;
import com.liskovsoft.sharedutils.cronet.CronetManager;
import com.liskovsoft.sharedutils.helpers.FileHelpers;
import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.sharedutils.okhttp.OkHttpManager;
import com.liskovsoft.smartyoutubetv2.common.diagnostics.Connections;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.errors.DashDefaultLoadErrorHandlingPolicy;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.errors.SabrDefaultLoadErrorHandlingPolicy;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.errors.TrackErrorFixer;
import com.liskovsoft.smartyoutubetv2.common.prefs.PlayerTweaksData;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;
import com.liskovsoft.googlecommon.common.helpers.DefaultHeaders;

import java.io.IOException;
import java.io.InputStream;
import java.util.List;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import okhttp3.OkHttpClient;

public class ExoMediaSourceFactory {
    private static final String TAG = ExoMediaSourceFactory.class.getSimpleName();
    @SuppressLint("StaticFieldLeak")
    //private static ExoMediaSourceFactory sInstance;
    private static final int MAX_SEGMENTS_PER_LOAD = 1; // default - 1 (1-5)
    private static final int SABR_READ_TIMEOUT_MS = 4_000;
    /**
     * Of the segments of a video's formats: as SABR's. The default's 20 s is the long buffering's (see BufferingDetector), so a
     * request that hangs at the start was never retried before the error fixer changed the client or the DNS.
     */
    private static final int DASH_READ_TIMEOUT_MS = SABR_READ_TIMEOUT_MS;
    private static final String USER_AGENT = DefaultHeaders.APP_USER_AGENT;
    @SuppressLint("StaticFieldLeak")
    private static final DefaultBandwidthMeter BANDWIDTH_METER = new DefaultBandwidthMeter();
    private final Context mContext;
    private static final Uri DASH_MANIFEST_URI = Uri.parse("https://example.com/test.mpd");
    private static final String DASH_MANIFEST_EXTENSION = "mpd";
    private static final String HLS_PLAYLIST_EXTENSION = "m3u8";
    private static final boolean USE_BANDWIDTH_METER = false;
    private TrackErrorFixer mTrackErrorFixer;
    private DataSource.Factory mMediaDataSourceFactory;
    private DataSource.Factory mSabrMediaDataSourceFactory;
    private DataSource.Factory mDashMediaDataSourceFactory;

    public ExoMediaSourceFactory(Context context) {
        mContext = context;
        ValidatedNetworkState.install(context);
    }

    public MediaSource fromSabrFormatInfo(MediaItemFormatInfo formatInfo) {
        return buildSabrMediaSource(formatInfo);
    }

    public MediaSource fromDashFormatInfo(MediaItemFormatInfo formatInfo) {
        return buildDashMediaSource(formatInfo);
    }

    public MediaSource fromDashManifest(InputStream dashManifest) {
        return buildMPDMediaSource(DASH_MANIFEST_URI, dashManifest);
    }

    public MediaSource fromDashManifestUrl(String dashManifestUrl) {
        return buildMediaSource(Uri.parse(dashManifestUrl), DASH_MANIFEST_EXTENSION);
    }

    public MediaSource fromHlsPlaylist(String hlsPlaylist) {
        return buildMediaSource(Uri.parse(hlsPlaylist), HLS_PLAYLIST_EXTENSION);
    }

    public MediaSource fromUrlList(List<String> urlList) {
        MediaSource[] mediaSources = new MediaSource[urlList.size()];

        for (int i = 0; i < urlList.size(); i++) {
            mediaSources[i] = buildMediaSource(Uri.parse(urlList.get(i)), null);
        }

        //return mediaSources.length == 1 ? mediaSources[0] : new ConcatenatingMediaSource(mediaSources); // or playlist
        return mediaSources[0]; // item with max resolution
    }

    /**
     * A single progressive stream (a Real-Debrid direct link, an MP4/MKV, anything {@link Util#inferContentType} reads as a file the
     * extractor plays): one media source, next to {@link #fromUrlList} which takes a list of format alternatives.
     */
    public MediaSource fromProgressiveUrl(String url) {
        return buildMediaSource(Uri.parse(url), null);
    }

    /**
     * Returns a new DataSource factory.
     *
     * @param useBandwidthMeter Whether to set {@link #BANDWIDTH_METER} as a listener to the new
     *                          DataSource factory.
     * @return A new DataSource factory.
     */
    private DataSource.Factory buildDataSourceFactory(boolean useBandwidthMeter) {
        return buildDataSourceFactory(useBandwidthMeter, (int) OkHttpManager.getReadTimeoutMs());
    }

    private DataSource.Factory buildDataSourceFactory(boolean useBandwidthMeter, int readTimeoutMs) {
        DefaultBandwidthMeter bandwidthMeter = useBandwidthMeter ? BANDWIDTH_METER : null;
        HttpDataSource.Factory httpFactory = buildHttpDataSourceFactory(useBandwidthMeter, readTimeoutMs);
        DataSource.Factory factory = new DefaultDataSourceFactory(mContext, bandwidthMeter, httpFactory);

        if (httpFactory instanceof OkHttpDataSourceFactory) {
            return factory; // its client times connections and responses (see Connections#LISTENER)
        }

        // The video starts' timing of the other engines' requests
        return () -> Connections.timeOpenings(factory.createDataSource());
    }

    /**
     * Returns a new HttpDataSource factory.
     *
     * @param useBandwidthMeter Whether to set {@link #BANDWIDTH_METER} as a listener to the new
     *                          DataSource factory.
     * @return A new HttpDataSource factory.
     */
    private HttpDataSource.Factory buildHttpDataSourceFactory(boolean useBandwidthMeter, int readTimeoutMs) {
        PlayerTweaksData tweaksData = PlayerTweaksData.instance(mContext);
        // IPv6 doesn't connect: only OkHttp can leave it out, the saved engine is used again after a restart
        int source = OkHttpManager.isIpv6Disabled() ? PlayerTweaksData.PLAYER_DATA_SOURCE_OKHTTP : tweaksData.getPlayerDataSource();
        DefaultBandwidthMeter bandwidthMeter = useBandwidthMeter ? BANDWIDTH_METER : null;
        return source == PlayerTweaksData.PLAYER_DATA_SOURCE_OKHTTP ? buildOkHttpDataSourceFactory(bandwidthMeter, readTimeoutMs) :
                        source == PlayerTweaksData.PLAYER_DATA_SOURCE_CRONET && CronetManager.getEngine(mContext) != null ? buildCronetDataSourceFactory(bandwidthMeter, readTimeoutMs) :
                                buildDefaultHttpDataSourceFactory(bandwidthMeter, readTimeoutMs);
    }

    @SuppressWarnings("deprecation")
    private MediaSource buildMediaSource(Uri uri, String overrideExtension) {
        int type = TextUtils.isEmpty(overrideExtension) ? Util.inferContentType(uri) : Util.inferContentType("." + overrideExtension);
        switch (type) {
            case C.TYPE_SS:
                SsMediaSource ssSource =
                        new SsMediaSource.Factory(
                                getSsChunkSourceFactory(),
                                getMediaDataSourceFactory()
                        )
                                .createMediaSource(uri);
                if (mTrackErrorFixer != null) {
                    ssSource.addEventListener(Utils.sHandler, mTrackErrorFixer);
                }
                return ssSource;
            case C.TYPE_DASH:
                DashMediaSource dashSource =
                        new DashMediaSource.Factory(
                                getDashChunkSourceFactory(),
                                getMediaDataSourceFactory()
                        )
                                .setManifestParser(new LiveDashManifestParser()) // Don't make static! Need state reset for each live source.
                                .setLoadErrorHandlingPolicy(new DashDefaultLoadErrorHandlingPolicy())
                                .createMediaSource(uri);
                if (mTrackErrorFixer != null) {
                    dashSource.addEventListener(Utils.sHandler, mTrackErrorFixer);
                }
                return dashSource;
            case C.TYPE_HLS:
                HlsMediaSource hlsSource = new HlsMediaSource.Factory(getMediaDataSourceFactory()).createMediaSource(uri);
                if (mTrackErrorFixer != null) {
                    hlsSource.addEventListener(Utils.sHandler, mTrackErrorFixer);
                }
                return hlsSource;
            case C.TYPE_OTHER:
                ExtractorMediaSource extractorSource = new ExtractorMediaSource.Factory(getMediaDataSourceFactory())
                        .setExtractorsFactory(new DefaultExtractorsFactory())
                        .createMediaSource(uri);
                if (mTrackErrorFixer != null) {
                    extractorSource.addEventListener(Utils.sHandler, mTrackErrorFixer);
                }
                return extractorSource;
            default: {
                throw new IllegalStateException("Unsupported type: " + type);
            }
        }
    }

    private MediaSource buildSabrMediaSource(MediaItemFormatInfo formatInfo) {
        // Are you using FrameworkSampleSource or ExtractorSampleSource when you build your player?
        SabrMediaSource sabrSource = new SabrMediaSource.Factory(
                getSabrChunkSourceFactory(),
                null
        )
                .setLoadErrorHandlingPolicy(new SabrDefaultLoadErrorHandlingPolicy())
                .createMediaSource(getSabrManifest(formatInfo));
        if (mTrackErrorFixer != null) {
            sabrSource.addEventListener(Utils.sHandler, mTrackErrorFixer);
        }
        return sabrSource;
    }

    private MediaSource buildDashMediaSource(MediaItemFormatInfo formatInfo) {
        // Are you using FrameworkSampleSource or ExtractorSampleSource when you build your player?
        DashChunkSource.Factory chunkSourceFactory;
        if (!formatInfo.isLive()) {
            chunkSourceFactory = getDashFormatsChunkSourceFactory();
        } else if (LiveSegmentPrefetcher.isNeeded(formatInfo.getSegmentDurationUs())) {
            chunkSourceFactory = getLivePrefetchChunkSourceFactory();
        } else {
            chunkSourceFactory = getDashChunkSourceFactory(); // see getDashFormatsChunkSourceFactory
        }
        DashMediaSource dashSource = new DashMediaSource.Factory(
                chunkSourceFactory,
                null
        )
                .setLoadErrorHandlingPolicy(new DashDefaultLoadErrorHandlingPolicy())
                .createMediaSource(getManifest(formatInfo));
        if (mTrackErrorFixer != null) {
            dashSource.addEventListener(Utils.sHandler, mTrackErrorFixer);
        }
        return dashSource;
    }

    private MediaSource buildMPDMediaSource(Uri uri, InputStream mpdContent) {
        // Are you using FrameworkSampleSource or ExtractorSampleSource when you build your player?
        DashMediaSource dashSource = new DashMediaSource.Factory(
                getDashChunkSourceFactory(),
                null
        )
                .setLoadErrorHandlingPolicy(new DashDefaultLoadErrorHandlingPolicy())
                .createMediaSource(getManifest(uri, mpdContent));
        if (mTrackErrorFixer != null) {
            dashSource.addEventListener(Utils.sHandler, mTrackErrorFixer);
        }
        return dashSource;
    }

    private MediaSource buildMPDMediaSource(Uri uri, String mpdContent) {
        if (mpdContent == null || mpdContent.isEmpty()) {
            Log.e(TAG, "Can't build media source. MpdContent is null or empty. " + mpdContent);
            return null;
        }

        // Are you using FrameworkSampleSource or ExtractorSampleSource when you build your player?
        DashMediaSource dashSource = new DashMediaSource.Factory(
                new DefaultDashChunkSource.Factory(getMediaDataSourceFactory()),
                null
        )
                .createMediaSource(getManifest(uri, mpdContent));
        if (mTrackErrorFixer != null) {
            dashSource.addEventListener(Utils.sHandler, mTrackErrorFixer);
        }
        return dashSource;
    }

    private SabrManifest getSabrManifest(MediaItemFormatInfo formatInfo) {
        SabrManifestParser parser = new SabrManifestParser();
        return parser.parse(formatInfo);
    }

    private DashManifest getManifest(MediaItemFormatInfo formatInfo) {
        DashManifestParser2 parser = new DashManifestParser2();
        return parser.parse(formatInfo);
    }

    private DashManifest getManifest(Uri uri, InputStream mpdContent) {
        DashManifestParser parser = new StaticDashManifestParser();
        DashManifest result;
        try {
            result = parser.parse(uri, mpdContent);
        } catch (IOException e) {
            throw new IllegalStateException("Malformed mpd file:\n" + mpdContent, e);
        }
        return result;
    }

    private DashManifest getManifest(Uri uri, String mpdContent) {
        DashManifestParser parser = new StaticDashManifestParser();
        DashManifest result;
        try {
            result = parser.parse(uri, FileHelpers.toStream(mpdContent));
        } catch (IOException e) {
            throw new IllegalStateException("Malformed mpd file:\n" + mpdContent, e);
        }
        return result;
    }

    /**
     * Use OkHttp for networking
     */
    private HttpDataSource.Factory buildOkHttpDataSourceFactory(DefaultBandwidthMeter bandwidthMeter, int readTimeoutMs) {
        // Shares the connection pool
        OkHttpClient client = OkHttpManager.instance().getClient().newBuilder()
                .readTimeout(readTimeoutMs, TimeUnit.MILLISECONDS)
                .eventListenerFactory(Connections.LISTENER)
                .build();
        OkHttpDataSourceFactory dataSourceFactory = new OkHttpDataSourceFactory(client, USER_AGENT,
                bandwidthMeter);
        addCommonHeaders(dataSourceFactory);
        return dataSourceFactory;
    }

    private HttpDataSource.Factory buildCronetDataSourceFactory(DefaultBandwidthMeter bandwidthMeter, int readTimeoutMs) {
        CronetDataSourceFactory dataSourceFactory =
                new CronetDataSourceFactory(
                        new CronetEngineWrapper(CronetManager.getEngine(mContext)),
                        Executors.newSingleThreadExecutor(),
                        null,
                        bandwidthMeter,
                        (int) OkHttpManager.getConnectTimeoutMs(),
                        readTimeoutMs,
                        true,
                        USER_AGENT);
        addCommonHeaders(dataSourceFactory);
        return dataSourceFactory;
    }

    /**
     * Use built-in component for networking
     */
    private HttpDataSource.Factory buildDefaultHttpDataSourceFactory(DefaultBandwidthMeter bandwidthMeter, int readTimeoutMs) {
        DefaultHttpDataSourceFactory dataSourceFactory = new DefaultHttpDataSourceFactory(
                USER_AGENT, bandwidthMeter, (int) OkHttpManager.getConnectTimeoutMs(),
                readTimeoutMs, true); // allowCrossProtocolRedirects = true

        addCommonHeaders(dataSourceFactory); // cause troubles for some users
        return dataSourceFactory;
    }

    private static void addCommonHeaders(HttpDataSource.Factory dataSourceFactory) {
        // Doesn't work
        // Trying to fix 429 error (too many requests)
        //String authorization = RetrofitOkHttpHelper.getAuthHeaders().get("Authorization");
        //
        //if (authorization != null) {
        //    dataSourceFactory.getDefaultRequestProperties().set("Authorization", authorization);
        //}

        //HeaderManager headerManager = new HeaderManager(context);
        //HashMap<String, String> headers = headerManager.getHeaders();

        // NOTE: "Accept-Encoding" should not be set manually (gzip is added by default).

        //for (String header : headers.keySet()) {
        //    if (EXO_HEADERS.contains(header)) {
        //        dataSourceFactory.getDefaultRequestProperties().set(header, headers.get(header));
        //    }
        //}

        // Emulate browser request
        //dataSourceFactory.getDefaultRequestProperties().set("accept", "*/*");
        //dataSourceFactory.getDefaultRequestProperties().set("accept-encoding", "identity"); // Next won't work: gzip, deflate, br
        //dataSourceFactory.getDefaultRequestProperties().set("accept-language", "en-US,en;q=0.9");
        //dataSourceFactory.getDefaultRequestProperties().set("dnt", "1");
        //dataSourceFactory.getDefaultRequestProperties().set("origin", "https://www.youtube.com");
        //dataSourceFactory.getDefaultRequestProperties().set("referer", "https://www.youtube.com/");
        //dataSourceFactory.getDefaultRequestProperties().set("sec-fetch-dest", "empty");
        //dataSourceFactory.getDefaultRequestProperties().set("sec-fetch-mode", "cors");
        //dataSourceFactory.getDefaultRequestProperties().set("sec-fetch-site", "cross-site");

        // WARN: Compression won't work with legacy streams.
        // "Accept-Encoding" should not be set manually (gzip is added by default).
        // Otherwise you should do decompression yourself.
        // Source: https://stackoverflow.com/questions/18898959/httpurlconnection-not-decompressing-gzip/42346308#42346308
        //dataSourceFactory.getDefaultRequestProperties().set("Accept-Encoding", AppConstants.ACCEPT_ENCODING_DEFAULT);
    }

    public void setTrackErrorFixer(TrackErrorFixer trackErrorFixer) {
        mTrackErrorFixer = trackErrorFixer;
    }

    public void release() {
        mMediaDataSourceFactory = null;
        mSabrMediaDataSourceFactory = null;
        mDashMediaDataSourceFactory = null;
    }

    @NonNull
    private DefaultSsChunkSource.Factory getSsChunkSourceFactory() {
        return new DefaultSsChunkSource.Factory(getMediaDataSourceFactory());
    }

    @NonNull
    private SabrChunkSource.Factory getSabrChunkSourceFactory() {
        return new DefaultSabrChunkSource.Factory(getSabrMediaDataSourceFactory(), MAX_SEGMENTS_PER_LOAD);
    }

    @NonNull
    private DashChunkSource.Factory getDashChunkSourceFactory() {
        return new DefaultDashChunkSource.Factory(getMediaDataSourceFactory(), MAX_SEGMENTS_PER_LOAD);
    }

    /**
     * SABR answers within milliseconds when healthy. A media network that doesn't answer
     * (e.g. an ISP cache node hanging on cache misses) must fail fast, so the chunk source
     * switches to the alternate network before the buffer runs dry.
     */
    private DataSource.Factory getSabrMediaDataSourceFactory() {
        if (mSabrMediaDataSourceFactory == null) {
            mSabrMediaDataSourceFactory = buildDataSourceFactory(USE_BANDWIDTH_METER, SABR_READ_TIMEOUT_MS);
        }

        return mSabrMediaDataSourceFactory;
    }

    /**
     * Of a video's formats (see #fromDashFormatInfo), not a live stream's: its segments may be answered late. One the server doesn't
     * have yet is held until it exists (hang=1), up to a segment's duration (5 s), and an edge that doesn't have one cached took 9 s at
     * times (upstream SmartTube #6009). Cut at 4 s, such a segment failed every retry and the playback with them.
     */
    private DashChunkSource.Factory getDashFormatsChunkSourceFactory() {
        return new DefaultDashChunkSource.Factory(getDashMediaDataSourceFactory(), MAX_SEGMENTS_PER_LOAD);
    }

    /**
     * Of a live stream with short segments (see LiveSegmentPrefetcher): a new one for each stream, as it keeps the stream's segments.
     * Not the formats' read timeout (see getDashFormatsChunkSourceFactory).
     */
    private DashChunkSource.Factory getLivePrefetchChunkSourceFactory() {
        return new DefaultDashChunkSource.Factory(new LiveSegmentPrefetcher(getMediaDataSourceFactory()), MAX_SEGMENTS_PER_LOAD);
    }

    /**
     * A host that doesn't answer is left for the ones the YouTube app falls back to (see GoogleVideoFallback)
     */
    private DataSource.Factory getDashMediaDataSourceFactory() {
        if (mDashMediaDataSourceFactory == null) {
            mDashMediaDataSourceFactory = GoogleVideoFallbackDataSource.wrap(buildDataSourceFactory(USE_BANDWIDTH_METER, DASH_READ_TIMEOUT_MS));
        }

        return mDashMediaDataSourceFactory;
    }

    /**
     * Of the live streams, HLS and progressive URLs. A host that doesn't answer is left as the formats' (see
     * getDashMediaDataSourceFactory). Not SABR's (see getSabrMediaDataSourceFactory).
     */
    private DataSource.Factory getMediaDataSourceFactory() {
        if (mMediaDataSourceFactory == null) {
            mMediaDataSourceFactory = GoogleVideoFallbackDataSource.wrap(buildDataSourceFactory(USE_BANDWIDTH_METER));
        }

        return mMediaDataSourceFactory;
    }

    // EXO: 2.10 - 2.12
    private static class StaticDashManifestParser extends DashManifestParser {
        @Override
        protected DashManifest buildMediaPresentationDescription(
                long availabilityStartTime,
                long durationMs,
                long minBufferTimeMs,
                boolean dynamic,
                long minUpdateTimeMs,
                long timeShiftBufferDepthMs,
                long suggestedPresentationDelayMs,
                long publishTimeMs,
                ProgramInformation programInformation,
                UtcTimingElement utcTiming,
                Uri location,
                List<Period> periods) {
            return new DashManifest(
                    availabilityStartTime,
                    durationMs,
                    minBufferTimeMs,
                    false,
                    minUpdateTimeMs,
                    timeShiftBufferDepthMs,
                    suggestedPresentationDelayMs,
                    publishTimeMs,
                    programInformation,
                    utcTiming,
                    location,
                    periods);
        }
    }

    // EXO: 2.13
    //private static class StaticDashManifestParser extends DashManifestParser {
    //    @Override
    //    protected DashManifest buildMediaPresentationDescription(
    //            long availabilityStartTime,
    //            long durationMs,
    //            long minBufferTimeMs,
    //            boolean dynamic,
    //            long minUpdateTimeMs,
    //            long timeShiftBufferDepthMs,
    //            long suggestedPresentationDelayMs,
    //            long publishTimeMs,
    //            @Nullable ProgramInformation programInformation,
    //            @Nullable UtcTimingElement utcTiming,
    //            @Nullable ServiceDescriptionElement serviceDescription,
    //            @Nullable Uri location,
    //            List<Period> periods) {
    //        return new DashManifest(
    //                availabilityStartTime,
    //                durationMs,
    //                minBufferTimeMs,
    //                false,
    //                minUpdateTimeMs,
    //                timeShiftBufferDepthMs,
    //                suggestedPresentationDelayMs,
    //                publishTimeMs,
    //                programInformation,
    //                utcTiming,
    //                serviceDescription,
    //                location,
    //                periods);
    //    }
    //}
}
