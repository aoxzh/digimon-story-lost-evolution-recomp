# Digimon Story: Lost Evolution Recomp 0.1.0

First public release.

**Windows:** download `DigimonLostEvolutionRecomp-0.1.0-windows-x64.zip`,
unzip it, put your ROM(s) in `roms\` and double-click `play.bat`. The first
start fetches a pinned, hash-checked compiler kit (about 250 MiB) and builds
the game from your ROM in roughly 5-15 minutes; later starts are immediate.
The `-sources.zip` is the same tooling without the framework sources, for
building on Linux/macOS (see the README).

- One build runs the Japanese retail, Operation Decoded English and Xzonn
  simplified-Chinese editions, each gated by its exact ROM SHA-1. The Chinese
  image is made from your Japanese dump automatically.
- No BIOS dump needed: boots on the bundled FreeBIOS. Your own dumps in
  `run\bios\` are used when present.
- Single-screen layout by default; stacked and two-window layouts available.
- 12 save-state slots per language; separate saves per language.
- Experimental Android ARM64 app (build it yourself), BIOS dumps optional.

Verified through the opening field dialogue. Later gameplay is untested;
please report problems.

These downloads contain no ROM, BIOS, firmware, save or recompiled game code.
