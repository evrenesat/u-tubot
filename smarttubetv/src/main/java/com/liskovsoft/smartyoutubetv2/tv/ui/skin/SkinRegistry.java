package com.liskovsoft.smartyoutubetv2.tv.ui.skin;

import android.app.Activity;
import android.app.Application;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.PlaybackPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.views.ViewManager;
import com.liskovsoft.smartyoutubetv2.common.misc.MotherActivity;
import com.liskovsoft.smartyoutubetv2.common.misc.SkinTraits;
import com.liskovsoft.smartyoutubetv2.common.misc.Skins;
import com.liskovsoft.smartyoutubetv2.common.prefs.MainUIData;
import com.liskovsoft.smartyoutubetv2.tv.ui.dialogs.AppDialogActivity;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.WeakHashMap;

/**
 * The skins of the app, in display order, and the one applied: the activities are registered for it (ViewManager).<br/>
 * The skin picked (MainUIData, of each account) is applied when no video is open, so a player of the old skin never runs next
 * to the activities of the new one. An activity of the old skin is replaced by the new one as it comes back (see MotherActivity),
 * the views to go back to are the new skin's at once.
 */
public final class SkinRegistry implements Skins.Provider {
    private static final String TAG = SkinRegistry.class.getSimpleName();
    private static SkinRegistry sInstance;
    private final List<Skin> mSkins = new ArrayList<>();
    // The classic activity of each view, in the order they're registered
    private final Map<Class<?>, Class<? extends Activity>> mClassicActivities = new LinkedHashMap<>();
    // The views without a parent (the root ones)
    private final List<Class<?>> mRootViews = new ArrayList<>();
    private Class<? extends Activity> mClassicRoot;
    private Skin mApplied;
    // The activities alive, so the ones of an old skin aren't left in the background (singleInstance: each in its own task)
    private final Set<Activity> mActivities = Collections.newSetFromMap(new WeakHashMap<>());

    SkinRegistry(List<Skin> skins) {
        mSkins.addAll(skins);
    }

    public static SkinRegistry instance() {
        if (sInstance == null) {
            // In the order of the Skins settings: Hybrid, the default of new users, between the two it mixes
            sInstance = new SkinRegistry(Arrays.asList(new ClassicSkin(), new HybridSkin(), new ModernSkin()));
        }

        return sInstance;
    }

    /**
     * The classic activity that shows a view
     *
     * @param isRoot it has no parent (e.g. Home)
     */
    public void addView(Class<?> viewClass, Class<? extends Activity> classic, boolean isRoot) {
        mClassicActivities.put(viewClass, classic);

        if (isRoot) {
            mRootViews.add(viewClass);
        }
    }

    /**
     * The activity the others go back to in the classic look
     */
    public void setClassicRoot(Class<? extends Activity> classicRoot) {
        mClassicRoot = classicRoot;
    }

    /**
     * Registers the activities of the skin picked. Once the views are added (see {@link #addView}).
     */
    public void init(Context context) {
        if (context.getApplicationContext() instanceof Application) {
            ((Application) context.getApplicationContext()).registerActivityLifecycleCallbacks(new ActivityTracker());
        }

        Skins.setProvider(this);
        apply(context, getEffectiveSkin(context));
    }

    public List<Skin> getSkins() {
        return Collections.unmodifiableList(mSkins);
    }

    /**
     * @return the classic skin for an id no skin has (e.g. a backup of a newer version)
     */
    @NonNull
    public Skin getSkin(int skinId) {
        for (Skin skin : mSkins) {
            if (skin.getId() == skinId) {
                return skin;
            }
        }

        return mSkins.get(0);
    }

    @NonNull
    public Skin getPickedSkin(Context context) {
        return getSkin(MainUIData.instance(context).getSkinId());
    }

    /**
     * The skin the device actually gets. On a large touch screen (a tablet) the leanback (classic) layout is unusable without a
     * remote, so it is shown as the modern, touch-friendly skin instead; the stored choice is kept, so a TV still gets classic.
     */
    @NonNull
    Skin getEffectiveSkin(Context context) {
        Skin picked = getPickedSkin(context);

        if (Tablets.isLargeTouchScreen(context) && picked.getId() == MainUIData.SKIN_CLASSIC) {
            return getSkin(MainUIData.SKIN_MODERN);
        }

        return picked;
    }

    /**
     * The skin the activities are registered for
     */
    @NonNull
    public Skin getAppliedSkin() {
        return mApplied != null ? mApplied : mSkins.get(0);
    }

    @Override
    public List<Integer> getSkinIds() {
        List<Integer> result = new ArrayList<>();

        for (Skin skin : mSkins) {
            result.add(skin.getId());
        }

        return result;
    }

    @Override
    public int getSkinNameResId(int skinId) {
        return getSkin(skinId).getNameResId();
    }

    @Override
    public int getAppliedSkinId() {
        return getAppliedSkin().getId();
    }

    @Override
    public SkinTraits getTraits(int skinId) {
        return getSkin(skinId);
    }

    @Override
    public void applyPickedSkin(Context context) {
        Skin picked = getEffectiveSkin(context);

        if (picked == getAppliedSkin()) {
            return;
        }

        // Never under a video: the player of the new skin can't take over the one that's open. Applied once it's closed.
        if (PlaybackPresenter.instance(context).getView() != null) {
            Log.d(TAG, "A video is open. The skin is applied when it's closed.");
            return;
        }

        Map<Class<? extends Activity>, Class<? extends Activity>> replacements = apply(context, picked);

        // The ones in the background are never shown again (the views to go back to are the new skin's)
        for (Activity activity : new ArrayList<>(mActivities)) {
            if (activity != context && !activity.isFinishing() && !(activity instanceof AppDialogActivity)
                    && replacements.containsKey(activity.getClass())) {
                finish(activity);
            }
        }
    }

    @Override
    public boolean isPickedSkinInPlace(Context context) {
        Skin picked = getPickedSkin(context);
        Skin applied = getAppliedSkin();

        if (picked == applied) {
            return true;
        }

        if (picked.resolveRoot(mClassicRoot) != applied.resolveRoot(mClassicRoot)) {
            return false;
        }

        for (Map.Entry<Class<?>, Class<? extends Activity>> entry : mClassicActivities.entrySet()) {
            if (picked.resolve(entry.getKey(), entry.getValue()) != applied.resolve(entry.getKey(), entry.getValue())) {
                return false;
            }
        }

        return true;
    }

    @Override
    public boolean replace(Activity activity) {
        Class<? extends Activity> target = getReplacement(activity.getClass());

        if (target == null) {
            return false;
        }

        Log.d(TAG, "Replacing %s with %s...", activity.getClass().getSimpleName(), target.getSimpleName());

        if (activity instanceof MotherActivity) {
            ((MotherActivity) activity).onReplaced();
        }

        Intent intent = new Intent(activity, target);
        Intent old = activity.getIntent();

        if (old != null && old.getExtras() != null) {
            intent.putExtras(old.getExtras());
        }

        try {
            activity.startActivity(intent);
        } catch (RuntimeException e) { // ActivityNotFoundException, SecurityException
            Log.e(TAG, "Can't start %s: %s", target.getSimpleName(), e.getMessage());
            return false;
        }

        finish(activity);

        return true;
    }

    private static void finish(Activity activity) {
        Log.d(TAG, "Finishing %s of the old skin...", activity.getClass().getSimpleName());

        if (activity instanceof MotherActivity) {
            ((MotherActivity) activity).finishReplaced();
        } else {
            activity.finish();
        }
    }

    /**
     * The activity of the applied skin that shows the same view as this one, null when it's this one or there's none (e.g.
     * a dialog activity no view is registered for)
     */
    @Nullable
    Class<? extends Activity> getReplacement(Class<? extends Activity> activityClass) {
        Skin applied = getAppliedSkin();

        for (Map.Entry<Class<?>, Class<? extends Activity>> entry : mClassicActivities.entrySet()) {
            Class<? extends Activity> current = applied.resolve(entry.getKey(), entry.getValue());

            if (current == activityClass) {
                return null; // already the applied skin's
            }

            for (Skin skin : mSkins) {
                if (skin != applied && skin.resolve(entry.getKey(), entry.getValue()) == activityClass) {
                    return current;
                }
            }
        }

        return null;
    }

    /**
     * @return the activity of the new skin for each one of the old skin it replaces
     */
    private Map<Class<? extends Activity>, Class<? extends Activity>> apply(Context context, Skin skin) {
        Log.d(TAG, "Applying the %s skin...", skin.getClass().getSimpleName());

        Skin old = mApplied;
        Class<? extends Activity> root = skin.resolveRoot(mClassicRoot);
        Map<Class<? extends Activity>, Class<? extends Activity>> replacements = new HashMap<>();

        ViewManager viewManager = ViewManager.instance(context);
        viewManager.unregisterAll();
        viewManager.setRoot(root);

        for (Map.Entry<Class<?>, Class<? extends Activity>> entry : mClassicActivities.entrySet()) {
            Class<?> viewClass = entry.getKey();
            Class<? extends Activity> activity = skin.resolve(viewClass, entry.getValue());
            viewManager.register(viewClass, activity, mRootViews.contains(viewClass) ? null : root);

            Class<? extends Activity> oldActivity = old != null ? old.resolve(viewClass, entry.getValue()) : null;

            if (oldActivity != null && oldActivity != activity) {
                replacements.put(oldActivity, activity);
            }
        }

        viewManager.replaceActivities(replacements);

        mApplied = skin;

        return replacements;
    }

    private class ActivityTracker implements Application.ActivityLifecycleCallbacks {
        @Override
        public void onActivityCreated(@NonNull Activity activity, @Nullable Bundle savedInstanceState) {
            mActivities.add(activity);
        }

        @Override
        public void onActivityDestroyed(@NonNull Activity activity) {
            mActivities.remove(activity);
        }

        @Override
        public void onActivityStarted(@NonNull Activity activity) {
            // NOP
        }

        @Override
        public void onActivityResumed(@NonNull Activity activity) {
            // NOP
        }

        @Override
        public void onActivityPaused(@NonNull Activity activity) {
            // NOP
        }

        @Override
        public void onActivityStopped(@NonNull Activity activity) {
            // NOP
        }

        @Override
        public void onActivitySaveInstanceState(@NonNull Activity activity, @NonNull Bundle outState) {
            // NOP
        }
    }
}
