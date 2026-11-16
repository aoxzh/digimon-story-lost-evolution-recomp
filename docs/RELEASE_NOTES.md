# Digimon Story: Lost Evolution Recomp 0.1.0

First public source release. Build it from your own ROM; see the README.

- One runner for the Japanese retail, Operation Decoded English and Xzonn
  simplified-Chinese editions, each gated by its exact ROM SHA-1.
- No BIOS dump needed: boots on the bundled FreeBIOS. Your own dumps in
  `run/bios/` are used when present.
- Single-screen layout by default; stacked and two-window layouts available.
- 12 save-state slots per language; separate saves per language.
- The Chinese image is made from your Japanese dump with a pinned,
  hash-checked download of the fan patch.
- Experimental Android ARM64 app (build it yourself), with BIOS dumps now
  optional there as well.

Verified through the opening field dialogue. Later gameplay is untested;
please report problems.

This release contains no ROM, BIOS, firmware, save or recompiled game code.
