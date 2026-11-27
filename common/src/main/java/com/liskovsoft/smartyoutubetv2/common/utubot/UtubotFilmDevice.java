package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Context;
import android.media.MediaCodecInfo;
import android.media.MediaCodecList;
import android.view.Display;
import android.view.WindowManager;

import androidx.annotation.Nullable;

/**
 * What this TV decodes (MediaCodecList) and which HDR its display shows (Display.HdrCapabilities), for {@link UtubotFilmFormat}.
 */
public final class UtubotFilmDevice implements UtubotFilmFormat.Device {
    private static final String MIME_HEVC = "video/hevc";
    private static final String MIME_AVC = "video/avc";
    private static final String MIME_AV1 = "video/av01";
    private static final String MIME_DOLBY_VISION = "video/dolby-vision";

    private final boolean mHevc;
    private final boolean mAvc;
    private final boolean mAv1;
    private final boolean mDolbyVision;
    private final boolean mHdr10;

    public UtubotFilmDevice(Context context) {
        mHevc = hasDecoder(MIME_HEVC);
        mAvc = hasDecoder(MIME_AVC);
        mAv1 = hasDecoder(MIME_AV1);
        mDolbyVision = hasDecoder(MIME_DOLBY_VISION);
        mHdr10 = displaysHdr10(context);
    }

    @Override
    public boolean decodes(UtubotFilmFormat.Codec codec) {
        switch (codec) {
            case HEVC:
                return mHevc;
            case H264:
                return mAvc;
            case AV1:
                return mAv1;
            default:
                return true;
        }
    }

    @Override
    public boolean decodesDolbyVision() {
        return mDolbyVision;
    }

    @Override
    public boolean displaysHdr10() {
        return mHdr10;
    }

    public String describe() {
        return "hevc=" + mHevc + " avc=" + mAvc + " av1=" + mAv1 + " dolbyVisionDecoder=" + mDolbyVision + " displayHdr10=" + mHdr10;
    }

    private static boolean hasDecoder(String mime) {
        try {
            for (MediaCodecInfo info : new MediaCodecList(MediaCodecList.REGULAR_CODECS).getCodecInfos()) {
                if (info.isEncoder()) {
                    continue;
                }

                for (String type : info.getSupportedTypes()) {
                    if (type.equalsIgnoreCase(mime)) {
                        return true;
                    }
                }
            }
        } catch (RuntimeException e) {
            return false;
        }

        return false;
    }

    private static boolean displaysHdr10(Context context) {
        WindowManager windowManager = (WindowManager) context.getSystemService(Context.WINDOW_SERVICE);
        Display display = windowManager == null ? null : windowManager.getDefaultDisplay();
        Display.HdrCapabilities capabilities = display == null ? null : display.getHdrCapabilities();

        if (capabilities == null) {
            return false;
        }

        for (int type : capabilities.getSupportedHdrTypes()) {
            if (type == Display.HdrCapabilities.HDR_TYPE_HDR10 || type == Display.HdrCapabilities.HDR_TYPE_HLG ||
                    type == Display.HdrCapabilities.HDR_TYPE_DOLBY_VISION) {
                return true;
            }
        }

        return false;
    }
}
