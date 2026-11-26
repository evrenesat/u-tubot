package com.liskovsoft.smartyoutubetv2.common.app.presenters.settings;

import android.content.Context;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.SettingsItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.SettingsCardsPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.base.BasePresenter;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotSettings;

import java.util.ArrayList;
import java.util.List;

/**
 * The General card of the System settings: the cards of the general settings on their own screen (System - General).
 * It was the Options card, the general settings panel was broken up into it.
 */
public class SystemGeneralSettingsPresenter extends BasePresenter<Void> implements SettingsCardsPresenter.Cards {
    private SystemGeneralSettingsPresenter(Context context) {
        super(context);
    }

    public static SystemGeneralSettingsPresenter instance(Context context) {
        return new SystemGeneralSettingsPresenter(context);
    }

    public void show() {
        SettingsCardsPresenter.instance(getContext()).show(this);
    }

    @Override
    public String getTitle(Context context) {
        return context.getString(R.string.settings_general);
    }

    @Override
    public List<SettingsItem> getItems(Context context) {
        List<SettingsItem> items = new ArrayList<>();
        items.add(new SettingsItem(context.getString(R.string.api_keys),
                () -> GeneralSettingsPresenter.instance(context).showApiKeys(), R.drawable.settings_api_keys));
        items.add(new SettingsItem(context.getString(R.string.category_background_playback),
                () -> GeneralSettingsPresenter.instance(context).showBackgroundPlayback(), R.drawable.settings_background_playback));
        if (UtubotSettings.isBuiltIn()) {
            items.add(new SettingsItem(context.getString(R.string.utubot_browse_refresh),
                    () -> GeneralSettingsPresenter.instance(context).showBrowseRefresh(), R.drawable.settings_home_rows));
        }
        items.add(new SettingsItem(context.getString(R.string.child_mode),
                () -> GeneralSettingsPresenter.instance(context).showChildMode(), R.drawable.settings_child_mode));
        items.add(new SettingsItem(context.getString(R.string.settings_disable_options),
                () -> GeneralSettingsPresenter.instance(context).showDisable(), R.drawable.settings_disable));
        items.add(new SettingsItem(context.getString(R.string.settings_exit_options),
                () -> GeneralSettingsPresenter.instance(context).showExit(), R.drawable.settings_exit));
        items.add(new SettingsItem(context.getString(R.string.header_history),
                () -> GeneralSettingsPresenter.instance(context).showHistory(), R.drawable.settings_history));
        items.add(new SettingsItem(context.getString(R.string.key_remapping),
                () -> GeneralSettingsPresenter.instance(context).showKeyRemapping(), R.drawable.settings_key_remapping));
        items.add(new SettingsItem(context.getString(R.string.settings_misc_options),
                () -> GeneralSettingsPresenter.instance(context).showMisc(), R.drawable.settings_misc));
        items.add(new SettingsItem(context.getString(R.string.network_settings),
                () -> GeneralSettingsPresenter.instance(context).showNetwork(), R.drawable.settings_network));
        items.add(new SettingsItem(context.getString(R.string.settings_password_options),
                () -> GeneralSettingsPresenter.instance(context).showPasswords(), R.drawable.settings_password));
        items.add(new SettingsItem(context.getString(R.string.settings_remember_options),
                () -> GeneralSettingsPresenter.instance(context).showRemember(), R.drawable.settings_remember));
        items.add(new SettingsItem(context.getString(R.string.screen_dimming),
                () -> GeneralSettingsPresenter.instance(context).showScreenDimming(), R.drawable.settings_screen_dimming));

        return items;
    }
}
