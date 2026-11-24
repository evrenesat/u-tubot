package com.liskovsoft.smartyoutubetv2.tv.utubot;

import android.content.Context;
import android.graphics.drawable.Drawable;

import androidx.core.content.ContextCompat;
import androidx.leanback.widget.Action;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;
import com.liskovsoft.smartyoutubetv2.tv.R;

/**
 * The player button of the director's cut picker: the u·tubot symbol, the label of the video menu's item. It is only added by the
 * built-in flavor, pointed at a backend.
 */
public class UtubotCutAction extends Action {
    public UtubotCutAction(Context context) {
        super(R.id.action_utubot_cut);

        Drawable icon = ContextCompat.getDrawable(context, R.drawable.settings_utubot);
        setIcon(icon);
        setLabel1(context.getString(R.string.utubot_cut_menu));
    }

    /**
     * The flavor has the layer, and the backend address is set: the button acts on the server's cuts
     */
    public static boolean isAvailable(Context context) {
        return UtubotSettings.isBuiltIn() && UtubotSettings.instance(context).isConfigured();
    }
}
