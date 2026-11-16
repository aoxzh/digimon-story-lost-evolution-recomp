# Language packs and switching

The title project treats each released image as a **language profile**:

- the ROM image (your dump or a locally patched image),
- a runner config with the exact SHA-1 and save-device settings,
- a generated bank directory,
- an independent save file and firmware identity.

`languages/manifest.json` is the single registry. `tools/lostevo.py` reads it
for `status`, `build`, `verify` and `play`.

## Profiles

| id | Image | Base | Notes |
|---|---|---|---|
| `en` | Operation Decoded T-En v1.1 (AP fix) | retail Japan | 60,598,900-byte trimmed dump; the runner pads it to 64 MiB at load |
| `ja` | retail Japan rev 0 | — | reference image; also the base for the Chinese patch |
| `zh-Hans` | Xzonn DSLEChsLocalization v1.0.1 | retail Japan | xdelta patch for ARM9, overlay 0, text, font and graphics Paks plus the banner |

The English and Chinese images have different ARM9 code (the English AP fix and
the Chinese font/text hooks), so they cannot share banks. The build therefore
emits `generated/recomp`, `generated/recomp-zh` and `generated/recomp-ja` and
registers all three with the same runner, each behind its exact SHA-1.

## Switching at launch

```bash
python tools/lostevo.py play
```

prints the registered languages, then launches the runner with the selected
ROM, config, `saves/lostevo-<id>.sav` and `saves/firmware-<id>.bin`. The choice
is persisted in `.state/selected-language.json`, so the next launch defaults to
it. A direct selection also works:

```bash
python tools/lostevo.py play --language zh-Hans
```

Switching restarts the game process; it is not an in-game text hot-swap. A true
hot-swap would require either (a) one ARM9 build that can load both file sets
and a game-side selector, or (b) a runner-side virtual filesystem that swaps
the file table while preserving the guest heap and state. Neither is part of
the current bring-up. Restarting is deterministic, keeps each language's save
separate, and matches how most multi-language ports handle a language change.

## Applying the Chinese patch

```bash
python tools/lostevo.py patch zh-Hans
```

What the tool does:

1. downloads `DSLEChsLocalization.v1.0.1.zip` from the pinned GitHub release;
2. verifies the release SHA-256
   `82bed3b65da7bfed459ea46af20ad420466ee08133b9cc6b611d1408f1b9e63d`;
3. extracts the `汉化补丁（用于日文 ROM）` member and verifies the `.xzp`
   SHA-256
   `610441fc479868086799ddea5a480e71f610166aafc5111b35101eb2eb08f855`;
4. opens the retail Japanese ROM, applies every xdelta member to the matching
   ARM9/overlay/Pak input, replaces direct `banner.bin` and `data/...` files
   (including `dwc/utility.bin`), and writes
   `roms/... [Zh-Hans v1.0.1].nds`;
5. refreshes the manifest and `game-zh.toml` with the actual hash and size.

The canonical NitroPatcher output has SHA-1
`45d12644e1a5b6dbf1d84d2898ed53d7fd455d1b`. This project uses an ndspy repack,
which preserves the same patched files but produces a different container
layout/hash (`e4798bff1c9a9753c1a32f2e3a50a3c921438f3e` in the recorded build).
The runner gates on the hash written by the tool, so either output works as
long as the config is refreshed.

The base Japanese ROM must match
`f180146f517712c177d6497125a24f35b0d6102f` (No-Intro Japan rev 0).
The patcher refuses other bases.

## Adding a new language

1. Put the ROM in `roms/`.
2. Add an entry to `languages/manifest.json` with an `id`, `name`,
   `native_name`, `edition`, `rom` path, `sha1`, `rom_size`, `config`,
   `bank_dir` and `save` path.
3. Either write `game-<id>.toml` by hand (copy `game.toml`) or let
   `prepare` generate it.
4. Run `python tools/lostevo.py build --language <id>`.
5. Run `python tools/lostevo.py verify --language <id>`.

The build tool writes the config's `sha1` and `rom_size` from the actual file,
so a stale manifest hash is corrected on the next build.

If the new image needs a ROM patch, add a `patch` object with `release_url`,
`release_sha256`, `patch_sha256`, `base_rom`, `base_sha1` and the optional
`canonical_output_sha1`. `apply_xzp` supports the NitroPatcher `.xzp` layout
used by this localization: `xdelta/arm9.bin`, `xdelta/overlay/*.bin`,
`xdelta/data/**`, and a direct `banner.bin`.

## Save isolation

Each profile has its own save and firmware state:

- `saves/lostevo-en.sav`
- `saves/lostevo-ja.sav`
- `saves/lostevo-zh-Hans.sav`
- `saves/firmware-<id>.bin`
- `saves/states-<id>/` (runner save states)

Do not rename or copy a save between profiles; the in-game data structures are
language-specific even when they share a game code.

## Credits

- **Operation Decoded** — English fan translation v1.1 (AP fix).
- **Xzonn / 遗失进化汉化组** — simplified-Chinese patch
  ([DSLEChsLocalization](https://github.com/Xzonn/DSLEChsLocalization)).
- **NitroPatcher** by Xzonn — the release patch format and canonical apply tool.

The localizations are fan works distributed by their authors. This repository
only contains tooling; ROMs, patched images and saves stay local.
