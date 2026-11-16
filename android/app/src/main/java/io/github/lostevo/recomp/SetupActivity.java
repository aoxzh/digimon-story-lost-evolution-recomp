package io.github.lostevo.recomp;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.text.TextUtils;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;

/**
 * First-run file import and language selection.
 *
 * <p>The APK contains no ROM, BIOS or save data. This activity uses the
 * Storage Access Framework to copy the user's own dumps into the app's
 * internal {@code files/} directory, then starts the SDL runner. It uses SAF
 * deliberately: Android 11+ denies direct native access to shared storage.</p>
 */
public class SetupActivity extends Activity {
    public static final String ACTION_SETUP = "io.github.lostevo.recomp.SETUP";
    public static final String EXTRA_FORCE = "force_setup";

    private static final int REQ_ROM = 100;
    private static final int REQ_BIOS9 = 101;
    private static final int REQ_BIOS7 = 102;

    private static final String[] LANGUAGE_IDS = {"en", "ja", "zh"};
    private static final String[] LANGUAGE_NAMES = {"English", "日本語", "简体中文"};
    private static final String[] CONFIG_ASSETS = {"game.toml", "game-ja.toml", "game-zh.toml"};
    private static final String[] ROM_NAMES = {"lostevo-en.nds", "lostevo-ja.nds", "lostevo-zh.nds"};

    private String language = "en";
    private TextView statusView;
    private Button startButton;
    private RadioGroup languageGroup;
    private int statusGeneration;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        ensureDirectories();
        language = readActiveLanguage();
        if (savedInstanceState != null) {
            String saved = savedInstanceState.getString("language");
            if (saved != null) {
                language = saved;
            }
        }
        boolean force = getIntent().getBooleanExtra(EXTRA_FORCE, false)
                || ACTION_SETUP.equals(getIntent().getAction());
        if (!force && profileReady(language)) {
            startGame();
            return;
        }
        if (force && profileReady(language)) {
            // Keep the UI open so the user can switch languages.
        }
        buildUi();
        refreshStatus();
    }

    private void buildUi() {
        int padding = dp(24);
        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(padding, padding, padding, padding);
        root.setBackgroundColor(Color.rgb(16, 20, 28));
        scroll.addView(root);

        TextView title = new TextView(this);
        title.setText("Digimon Story: Lost Evolution");
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        title.setTextColor(Color.WHITE);
        root.addView(title);

        TextView intro = new TextView(this);
        intro.setText("本应用不包含 ROM、BIOS、存档或游戏数据。\n"
                + "请选择你自己的 .nds ROM；BIOS dump 可选，不选择时使用内置的开源 FreeBIOS。"
                + "文件只会复制到应用内部目录。\n"
                + "This app contains no game data. Pick your own .nds ROM; BIOS dumps are optional "
                + "(the bundled open-source FreeBIOS is used without them).");
        intro.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        intro.setTextColor(Color.rgb(190, 200, 215));
        intro.setPadding(0, dp(12), 0, dp(18));
        root.addView(intro);

        TextView languageLabel = new TextView(this);
        languageLabel.setText("游戏语言 / Language");
        languageLabel.setTextColor(Color.WHITE);
        languageLabel.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        root.addView(languageLabel);

        languageGroup = new RadioGroup(this);
        languageGroup.setOrientation(RadioGroup.VERTICAL);
        for (int i = 0; i < LANGUAGE_IDS.length; ++i) {
            RadioButton button = new RadioButton(this);
            button.setId(i + 1);
            button.setText(LANGUAGE_NAMES[i]);
            button.setTextColor(Color.rgb(220, 228, 240));
            button.setChecked(LANGUAGE_IDS[i].equals(language));
            final String id = LANGUAGE_IDS[i];
            button.setOnClickListener(v -> {
                language = id;
                refreshStatus();
            });
            languageGroup.addView(button);
        }
        root.addView(languageGroup);

        root.addView(sectionButton("选择 ROM (.nds)", REQ_ROM));
        root.addView(sectionButton("可选：BIOS ARM9 (biosnds9.rom, 4 KiB)", REQ_BIOS9));
        root.addView(sectionButton("可选：BIOS ARM7 (biosnds7.rom, 16 KiB)", REQ_BIOS7));

        statusView = new TextView(this);
        statusView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        statusView.setTextColor(Color.rgb(170, 220, 190));
        statusView.setPadding(0, dp(16), 0, dp(12));
        statusView.setTextIsSelectable(true);
        root.addView(statusView);

        startButton = new Button(this);
        startButton.setText("开始游戏 / Start");
        startButton.setTextSize(TypedValue.COMPLEX_UNIT_SP, 17);
        startButton.setOnClickListener(v -> {
            if (!profileReady(language)) {
                refreshStatus();
                Toast.makeText(this, "ROM 尚未就绪 / ROM not ready", Toast.LENGTH_SHORT).show();
                return;
            }
            startGame();
        });
        LinearLayout.LayoutParams startParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(56));
        startParams.topMargin = dp(8);
        root.addView(startButton, startParams);

        TextView note = new TextView(this);
        note.setText("提示：安装后再次进入本页可从桌面图标长按 →「文件设置」；"
                + "已就绪时会直接进入游戏。");
        note.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        note.setTextColor(Color.rgb(140, 150, 165));
        note.setPadding(0, dp(14), 0, 0);
        root.addView(note);

        setContentView(scroll);
    }

    private Button sectionButton(String text, int request) {
        Button button = new Button(this);
        button.setText(text);
        button.setAllCaps(false);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        params.topMargin = dp(10);
        button.setLayoutParams(params);
        button.setOnClickListener(v -> openDocument(request));
        return button;
    }

    private void openDocument(int request) {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("*/*");
        try {
            startActivityForResult(intent, request);
        } catch (Exception error) {
            Toast.makeText(this, "无法打开文件选择器：" + error, Toast.LENGTH_LONG).show();
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (resultCode != RESULT_OK || data == null || data.getData() == null) {
            return;
        }
        Uri uri = data.getData();
        File target;
        long expectedSize = -1;
        if (requestCode == REQ_ROM) {
            target = romFile(language);
            expectedSize = 16L * 1024 * 1024;
        } else if (requestCode == REQ_BIOS9) {
            target = biosFile("biosnds9.rom");
            expectedSize = 4096;
        } else if (requestCode == REQ_BIOS7) {
            target = biosFile("biosnds7.rom");
            expectedSize = 16384;
        } else {
            return;
        }
        try {
            copyUri(uri, target);
            long size = target.length();
            if (requestCode == REQ_BIOS9 && size != 4096) {
                target.delete();
                throw new IOException("biosnds9.rom 必须是 4096 字节，实际 " + size);
            }
            if (requestCode == REQ_BIOS7 && size != 16384) {
                target.delete();
                throw new IOException("biosnds7.rom 必须是 16384 字节，实际 " + size);
            }
            if (requestCode == REQ_ROM && size < expectedSize) {
                target.delete();
                throw new IOException("ROM 文件过小（" + size + " 字节）");
            }
            refreshStatus();
        } catch (Exception error) {
            target.delete();
            Toast.makeText(this, "导入失败：" + error.getMessage(),
                    Toast.LENGTH_LONG).show();
            refreshStatus();
        }
    }

    private void refreshStatus() {
        ensureConfigAsset(language);
        ++statusGeneration;
        int generation = statusGeneration;
        if (statusView != null) {
            statusView.setText(buildStatusText(false));
            startButton.setEnabled(profileReady(language));
        }
        // Hash verification may take a moment on a 60 MB ROM.
        new Thread(() -> {
            String warning = validateRom(language, romFile(language));
            if (generation != statusGeneration) {
                return;
            }
            runOnUiThread(() -> {
                if (statusView == null || generation != statusGeneration) {
                    return;
                }
                statusView.setText(buildStatusText(true) + (warning == null
                        ? "" : "\n\n⚠ " + warning));
                startButton.setEnabled(profileReady(language) && warning == null);
            });
        }, "lostevo-setup-validation").start();
    }

    private String buildStatusText(boolean validated) {
        StringBuilder text = new StringBuilder();
        text.append("ROM: ");
        text.append(describeFile(romFile(language), "未选择"));
        text.append('\n').append("BIOS ARM9: ");
        text.append(describeFile(biosFile("biosnds9.rom"), "未选择（FreeBIOS）"));
        text.append('\n').append("BIOS ARM7: ");
        text.append(describeFile(biosFile("biosnds7.rom"), "未选择（FreeBIOS）"));
        text.append('\n').append("配置: ");
        text.append(describeFile(configFile(language), "使用内置配置"));
        if (!validated) {
            text.append("\n\n正在校验文件…");
        }
        return text.toString();
    }

    private String describeFile(File file, String missing) {
        if (!file.isFile()) {
            return missing;
        }
        return file.getName() + "  (" + file.length() + " B)";
    }

    private String validateRom(String lang, File rom) {
        if (!rom.isFile() || rom.length() < 16L * 1024 * 1024) {
            return null;
        }
        String expected = expectedRomSha1(lang);
        if (TextUtils.isEmpty(expected)) {
            return null;
        }
        try {
            String actual = sha1(rom);
            if (!actual.equalsIgnoreCase(expected)) {
                return "ROM SHA-1 与「" + languageName(lang) + "」配置不匹配。\n"
                        + "实际: " + actual + "\n期望: " + expected
                        + "\n请确认语言选择与 ROM 版本。";
            }
        } catch (Exception error) {
            return "无法读取 ROM: " + error.getMessage();
        }
        return null;
    }

    private String expectedRomSha1(String lang) {
        try (InputStream input = getAssets().open(configAsset(lang))) {
            byte[] data = new byte[8192];
            int count = input.read(data);
            String config = new String(data, 0, Math.max(0, count),
                    StandardCharsets.UTF_8);
            for (String line : config.split("\\R")) {
                String trimmed = line.trim();
                if (trimmed.startsWith("sha1") && trimmed.contains("=")) {
                    String value = trimmed.substring(trimmed.indexOf('=') + 1)
                            .trim().replace("\"", "");
                    if (value.matches("[0-9a-fA-F]{40}")) {
                        return value.toLowerCase(Locale.ROOT);
                    }
                }
            }
        } catch (IOException ignored) {
            // Config asset missing: the runner still performs its own gate.
        }
        return null;
    }

    private static String sha1(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-1");
        try (InputStream input = new FileInputStream(file)) {
            byte[] buffer = new byte[1 << 20];
            int count;
            while ((count = input.read(buffer)) > 0) {
                digest.update(buffer, 0, count);
            }
        }
        StringBuilder hex = new StringBuilder(40);
        for (byte value : digest.digest()) {
            hex.append(String.format(Locale.ROOT, "%02x", value & 0xFF));
        }
        return hex.toString();
    }

    private void copyUri(Uri uri, File target) throws IOException {
        target.getParentFile().mkdirs();
        File temporary = new File(target.getParentFile(),
                target.getName() + ".importing");
        try (InputStream input = getContentResolver().openInputStream(uri);
             OutputStream output = new FileOutputStream(temporary)) {
            if (input == null) {
                throw new IOException("无法读取所选文件");
            }
            byte[] buffer = new byte[1 << 20];
            int count;
            while ((count = input.read(buffer)) > 0) {
                output.write(buffer, 0, count);
            }
        } catch (IOException error) {
            temporary.delete();
            throw error;
        }
        if (!temporary.renameTo(target)) {
            temporary.delete();
            throw new IOException("无法写入 " + target);
        }
    }

    private void startGame() {
        ensureConfigAsset(language);
        writeActiveLanguage(language);
        Intent intent = new Intent(this, LostEvoActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP);
        String testFold = getIntent().getStringExtra("test_fold");
        if (!TextUtils.isEmpty(testFold)) {
            intent.putExtra("test_fold", testFold);
        }
        startActivity(intent);
        finish();
    }

    private boolean profileReady(String lang) {
        // BIOS dumps are optional: the native wrapper boots FreeBIOS unless
        // both dumps are present with the right sizes.
        File rom = romFile(lang);
        return rom.isFile() && rom.length() >= 16L * 1024 * 1024;
    }

    private void ensureDirectories() {
        new File(getFilesDir(), "roms").mkdirs();
        new File(getFilesDir(), "bios").mkdirs();
        new File(getFilesDir(), "config").mkdirs();
        new File(getFilesDir(), "saves").mkdirs();
    }

    private void ensureConfigAsset(String lang) {
        File target = configFile(lang);
        if (target.isFile() && target.length() > 0) {
            return;
        }
        target.getParentFile().mkdirs();
        try (InputStream input = getAssets().open(configAsset(lang));
             OutputStream output = new FileOutputStream(target)) {
            byte[] buffer = new byte[8192];
            int count;
            while ((count = input.read(buffer)) > 0) {
                output.write(buffer, 0, count);
            }
        } catch (IOException error) {
            Toast.makeText(this, "内置配置复制失败：" + error.getMessage(),
                    Toast.LENGTH_LONG).show();
        }
    }

    private String readActiveLanguage() {
        File file = activeLanguageFile();
        if (!file.isFile()) {
            return "en";
        }
        try (InputStream input = new FileInputStream(file)) {
            byte[] data = new byte[16];
            int count = input.read(data);
            String value = new String(data, 0, Math.max(0, count),
                    StandardCharsets.UTF_8).trim();
            for (String id : LANGUAGE_IDS) {
                if (id.equals(value)) {
                    return id;
                }
            }
        } catch (IOException ignored) {
            // Fall through to the default.
        }
        return "en";
    }

    private void writeActiveLanguage(String lang) {
        try (OutputStream output = new FileOutputStream(activeLanguageFile())) {
            output.write(lang.getBytes(StandardCharsets.UTF_8));
        } catch (IOException error) {
            Toast.makeText(this, "无法保存语言设置：" + error.getMessage(),
                    Toast.LENGTH_LONG).show();
        }
    }

    private File romFile(String lang) {
        int index = indexOfLanguage(lang);
        return new File(new File(getFilesDir(), "roms"), ROM_NAMES[index]);
    }

    private File configFile(String lang) {
        return new File(new File(getFilesDir(), "config"), lang + ".toml");
    }

    private File biosFile(String name) {
        return new File(new File(getFilesDir(), "bios"), name);
    }

    private File activeLanguageFile() {
        return new File(new File(getFilesDir(), "config"), "active-language");
    }

    private static int indexOfLanguage(String lang) {
        for (int i = 0; i < LANGUAGE_IDS.length; ++i) {
            if (LANGUAGE_IDS[i].equals(lang)) {
                return i;
            }
        }
        return 0;
    }

    private static String configAsset(String lang) {
        return CONFIG_ASSETS[indexOfLanguage(lang)];
    }

    private static String languageName(String lang) {
        return LANGUAGE_NAMES[indexOfLanguage(lang)];
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        outState.putString("language", language);
    }
}
