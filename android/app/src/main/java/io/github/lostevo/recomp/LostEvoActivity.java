package io.github.lostevo.recomp;

import android.graphics.Rect;
import android.os.Bundle;
import android.util.Log;
import android.view.View;

import androidx.core.content.ContextCompat;
import androidx.core.util.Consumer;
import androidx.window.layout.DisplayFeature;
import androidx.window.layout.FoldingFeature;
import androidx.window.layout.WindowInfoTracker;
import androidx.window.layout.WindowLayoutInfo;
import androidx.window.java.layout.WindowInfoTrackerCallbackAdapter;

import org.libsdl.app.SDLActivity;

/**
 * SDL activity with foldable posture awareness.
 *
 * <p>AndroidX WindowManager reports the hinge/crease rectangle and whether it
 * currently separates the window. The rectangle is forwarded in window pixels
 * to libmain, which converts it to permille fractions and recomposes the
 * single-screen canvas around it (tabletop: top screen above the hinge, touch
 * screen + controls below; book: left/right split).</p>
 */
public class LostEvoActivity extends SDLActivity {
    private static final String TAG = "LostEvoFold";

    private static native void nativeSetFoldState(int left, int top, int right,
                                                  int bottom, int orientation,
                                                  boolean separating,
                                                  int windowWidth,
                                                  int windowHeight);

    private WindowInfoTrackerCallbackAdapter tracker;
    private Consumer<WindowLayoutInfo> listener;
    private WindowLayoutInfo lastInfo;
    private boolean retryPosted;
    private int testFoldOrientation;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        String testFold = getIntent().getStringExtra("test_fold");
        if ("horizontal".equals(testFold)) {
            testFoldOrientation = 1;
        } else if ("vertical".equals(testFold)) {
            testFoldOrientation = 2;
        }
        try {
            tracker = new WindowInfoTrackerCallbackAdapter(
                    WindowInfoTracker.getOrCreate(this));
            listener = this::onWindowLayoutInfo;
            tracker.addWindowLayoutInfoListener(
                    this, ContextCompat.getMainExecutor(this), listener);
        } catch (Throwable error) {
            // A device without the AndroidX foldable backend must still run.
            Log.w(TAG, "window layout tracking unavailable", error);
        }
    }

    private void onWindowLayoutInfo(WindowLayoutInfo info) {
        lastInfo = info;
        applyLastInfo();
    }

    private void applyLastInfo() {
        WindowLayoutInfo info = lastInfo;
        View decor = getWindow() != null ? getWindow().getDecorView() : null;
        int width = decor != null ? decor.getWidth() : 0;
        int height = decor != null ? decor.getHeight() : 0;
        if (decor != null && (width <= 0 || height <= 0) && !retryPosted) {
            retryPosted = true;
            decor.post(() -> {
                retryPosted = false;
                applyLastInfo();
            });
            return;
        }

        boolean separating = false;
        int orientation = 0;
        Rect bounds = null;
        if (info != null) {
            for (DisplayFeature feature : info.getDisplayFeatures()) {
                if (!(feature instanceof FoldingFeature)) {
                    continue;
                }
                FoldingFeature fold = (FoldingFeature) feature;
                if (!fold.isSeparating()) {
                    continue;
                }
                separating = true;
                orientation =
                        fold.getOrientation() == FoldingFeature.Orientation.HORIZONTAL
                                ? 1 : 2;
                bounds = fold.getBounds();
                break;
            }
        }

        // Deterministic posture simulation for layout audits; never used by
        // the launcher path.
        if (testFoldOrientation != 0 && width > 0 && height > 0) {
            separating = true;
            orientation = testFoldOrientation;
            if (orientation == 1) {
                bounds = new Rect(0, height / 2 - 12, width, height / 2 + 12);
            } else {
                bounds = new Rect(width / 2 - 12, 0, width / 2 + 12, height);
            }
        }

        try {
            if (!separating || bounds == null || width <= 0 || height <= 0) {
                nativeSetFoldState(0, 0, 0, 0, 0, false, width, height);
            } else {
                nativeSetFoldState(bounds.left, bounds.top, bounds.right,
                        bounds.bottom, orientation, true, width, height);
            }
        } catch (UnsatisfiedLinkError error) {
            Log.w(TAG, "native fold state unavailable", error);
        }
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            applyLastInfo();
        }
    }

    @Override
    public void onConfigurationChanged(android.content.res.Configuration config) {
        super.onConfigurationChanged(config);
        applyLastInfo();
    }

    @Override
    protected void onDestroy() {
        if (tracker != null && listener != null) {
            try {
                tracker.removeWindowLayoutInfoListener(listener);
            } catch (Throwable ignored) {
                // Activity teardown must not fail on a listener race.
            }
            tracker = null;
            listener = null;
        }
        super.onDestroy();
    }
}
