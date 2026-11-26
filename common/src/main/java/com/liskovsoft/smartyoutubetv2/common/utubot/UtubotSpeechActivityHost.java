package com.liskovsoft.smartyoutubetv2.common.utubot;

import android.content.Intent;

/**
 * The activity a voice description runs in forwards its results here, so the permission request and
 * the platform recogniser (both started with {@code startActivityForResult}) reach the in-flight
 * {@link UtubotSpeechInput}. The view that shows the mic implements this.
 */
public interface UtubotSpeechActivityHost {
    void onUtubotSpeechActivityResult(int requestCode, int resultCode, Intent data);
}
