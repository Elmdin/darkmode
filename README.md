# Umbra

*Real-time dark mode for Windows — the `3MagicLabs/darkmode` project.*

Real-time dark mode over your whole laptop screen, or any rectangle of it that you drag out.

Everything light becomes dark, everything dark becomes light — and the colours in between
keep their hue instead of flipping to their opposite. Blue stays blue. Red stays red.

```
  page white   #ffffff  ->  #0d0d0d      link blue    #1a59d9  ->  #6da5ff
  black text   #000000  ->  #ebebeb      error red    #cc2626  ->  #ff8c8c
  mid grey     #808080  ->  #7c7c7c      warn amber   #f2b21a  ->  #824b00
```

Run `umbra preview` to see that table in colour, for every preset, before putting anything
on your screen.

## Is it a *real* dark theme?

Partly, and `umbra compare` tells you exactly how much. It scores each preset
against light/dark colour pairs from shipped design systems — GitHub Primer,
VS Code, Tailwind — in Oklab, where ~0.02 is just noticeable and ~0.10 reads as a
different colour.

```
preset      white ->  black ->      dE
theme          0.120     0.940  0.0645     <- default, tuned against that data
dark           0.050     0.920  0.0897     <- plain lightness inversion
negative       0.000     1.000  0.2189     <- what Windows Magnifier does
```

The `theme` preset was fitted to those pairs and is **16% closer** than plain
inversion by leave-one-out cross-validation. It lands on VS Code's `#1e1e1e`
editor background to within 0.003 and Tailwind's `blue-400` to within 0.008.

**And there is a ceiling.** A real dark theme is not a function of the light
theme — humans chose each value — so some of it cannot be reproduced by any
per-pixel transform:

- **Bright saturated accents.** Tailwind's `amber-600` `#d97706` becomes
  `amber-400` `#fbbf24` — it stays *bright*, because an accent has to carry
  contrast against a dark background. Inverting lightness necessarily darkens
  it. This is Umbra's worst case (dE 0.20) and it is structural, not a tuning
  miss.
- **Mid-tone text.** `#6b7280` muted text becomes *lighter* `#9ca3af`, not
  darker. No inversion of any kind reproduces that.
- **Photos.** There is no content detection at the compositor level, so images
  are transformed along with everything else.

Doing those properly needs a non-linear, saturation-aware transform, which the
compositor's affine colour matrix cannot express. See *Known limits*.

## Why not just invert

Windows Magnifier and most "invert screen" tools compute `out = 1 - rgb`. That flips hue:
blue turns orange, red turns cyan, every photo becomes a negative, and a white page becomes
pure `#000000`, which is harsher than any real dark theme.

Umbra inverts **lightness** and leaves **hue** alone. Split each pixel into luma and chroma,
invert only the luma, keep the chroma:

```
L   = 0.2126·r + 0.7152·g + 0.0722·b        (Rec.709 luma)
out = (1 - L) + saturation · (rgb - L)
```

At `saturation = 1` this reduces to adding a per-pixel constant to all three channels.
Channel *differences* are untouched, so hue and chroma are preserved **exactly**, not
approximately. Then the result is compressed into `[0.05, 0.92]` rather than `[0, 1]`, so a
white page lands on `#0d0d0d` and black text on `#ebebeb` — a real dark theme, not a raw
negative.

One knob spans every mode worth having:

| `--saturation` | behaviour | pure blue becomes |
|---|---|---|
| `-1` | classic negative (hue flips) | yellow |
| `0` | inverted greyscale | grey |
| `1` | **hue-preserving dark mode** (default) | light blue |
| `>1` | vivid — chroma boosted to offset perceived washout | saturated light blue |

## How it works

No screen capture. Umbra hands a 5×5 colour matrix to the Windows **Magnification API**,
which applies it inside the desktop compositor on the GPU. Nothing is copied or re-drawn by
us, so there is no frame latency and no feedback loop.

- **Whole screen** — `MagSetFullscreenColorEffect`. Every monitor, cursor included.
- **A region** — a magnifier control at 1.0× inside a click-through, always-on-top window
  pinned over your rectangle. Click straight through it; it never takes focus, and it
  excludes its own windows from what it reads.

## Install and run

Needs **64-bit Python 3.8+ on Windows** and nothing else — no pip install, no
dependencies. (The Magnification API does not work under WOW64, so 32-bit Python
cannot do this.)

```
git clone https://github.com/3MagicLabs/darkmode.git
cd darkmode
umbra.bat
```

Double-clicking `umbra.bat` works too. Leave the console window open — closing it
restores your screen. From a terminal you can pass options:

```
umbra                          whole screen, default look
umbra --select                 drag a rectangle first
umbra --region 0,0,1280,800    a specific rectangle
umbra --preset warm            amber night mode
umbra --preset dark --strength 0.7 --contrast 1.1
umbra preview                  colour swatches, in the terminal
umbra compare                  score the presets against real dark themes
umbra doctor                   check this machine can run it
umbra reset                    clear a stuck effect after a hard kill
```

**Leave the console window open.** Closing it restores your screen.

## Hotkeys

Global, so they work whatever has focus.

| | |
|---|---|
| `Ctrl+Alt+D` | toggle on/off |
| `Ctrl+Alt+F` | cover the whole screen |
| `Ctrl+Alt+R` | drag out a new region |
| `Ctrl+Alt+[` / `]` | previous / next preset |
| `Ctrl+Alt+↑` / `↓` | stronger / weaker |
| `Ctrl+Alt+←` / `→` | less / more contrast |
| `Ctrl+Alt+W` | cycle warmth (night-light amber) |
| `Ctrl+Alt+Q` | quit and restore |

If another app already owns one, Umbra says so and carries on without it. Rebind it in the
config file.

## Presets

| | |
|---|---|
| `theme` | **the default**: tuned against real design-system dark themes |
| `dark` | plain hue-preserving lightness inversion, untuned |
| `soft` | lower contrast, easier for long reading |
| `midnight` | deeper background, dimmer foreground — good on OLED |
| `vivid` | chroma boosted, for washed-out-looking screens |
| `warm` | dark plus an amber night shift |
| `mono` | inverted greyscale, no colour at all |
| `negative` | plain inversion, for comparison |
| `off` | no effect |

Settings persist to `%APPDATA%\umbra\config.json`, including any hotkey rebinds.

## Known limits

- **DRM video** (Netflix, some players) renders in a hardware overlay the compositor cannot
  read. Those regions stay untransformed. Not fixable from here.
- **Saturated primaries clip one channel.** Hue-preserving inversion has to overshoot the
  sRGB cube on pure red/green/blue, and the transform is affine so it cannot clamp
  mid-pipeline. Clipping is monotone, so the colour stays the right hue — only its
  brightness is off. `umbra preview` reports the overshoot for any preset.
- **Windows "Colour filters"** fights Umbra for the same compositor slot. `umbra doctor`
  detects it and tells you where to turn it off.
- **Photos are inverted too.** There is no content detection at the compositor level;
  `--strength` lets you dial the whole effect back.
- **Bright saturated accents darken** where a designed theme would keep them bright.
  Fixing this needs a non-linear saturation-aware transform, which means abandoning
  the compositor matrix for a capture-and-shader pipeline: dependencies, real frame
  latency, a feedback loop to manage, and no effect on DRM content. Measured against
  the same data, a non-linear rule scores ~0.083 versus the current 0.064 in-sample —
  it fixes amber and green but is worse elsewhere, so it is not an unambiguous win.
  Ask if you want it built.

## Development

```
python -m pytest              250 tests, no Windows required
python -m umbra preview       verify the colour maths visually, anywhere
python -m umbra compare       score presets against real dark themes
./sync-to-windows.sh          copy to the Windows filesystem to run it
```

The colour pipeline (`colormatrix`, `transforms`, `geometry`) is pure Python with no
Windows dependency, which is why it can be tested on any machine. `SPEC.md` has the full
contract, invariants, and edge cases.

## License

MIT — see [LICENSE](LICENSE).
