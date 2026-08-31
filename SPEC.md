# SPEC — Umbra

Real-time dark-mode overlay for Windows. Covers the whole screen or a region you choose,
and rewrites the colours underneath it: light becomes dark, dark becomes light, and the
colours in between keep their hue instead of flipping to their opposite.

## 1. Problem

Naive screen inversion (`out = 1 - rgb`) is what Windows Magnifier and most tools do. It is
wrong for reading: blue becomes orange, red becomes cyan, every photo becomes a negative,
and pure white becomes pure black (harsher than any real dark theme).

A *proper* dark mode inverts **lightness only** and leaves **hue** alone, then compresses the
result into a comfortable range (`#0d0d0d` .. `#ebebeb`) rather than slamming to pure black
and pure white.

## 2. Approach

Windows' **Magnification API** applies a 5x5 GDI+ colour matrix to screen content inside the
desktop compositor. This is the correct mechanism:

- runs on the GPU, no screen capture, no copy, no frame latency
- no feedback loop (the magnifier excludes the overlay's own windows)
- affects everything: apps, PDFs, terminals, browsers, the cursor

Trade-off accepted: a 5x5 matrix is an **affine** transform, so the pipeline must be linear.
Non-linear effects (true HSL round-trip, gamma-correct inversion, per-pixel photo detection)
are out of scope. Section 3 shows the linear formulation is sufficient and, in fact,
equivalent to lightness inversion for the cases that matter.

Two engines behind one interface (Strategy):

| Engine | Mechanism | Scope |
|---|---|---|
| `FullscreenEngine` | `MagSetFullscreenColorEffect` | entire desktop, all monitors |
| `RegionEngine` | `WC_MAGNIFIER` control at 1.0x in a click-through layered host window | one rectangle |

## 3. Colour model (the core contract)

Input and output are sRGB in `[0,1]`. Let `w` be luma weights (default Rec.709
`0.2126, 0.7152, 0.0722`), and `L = w . rgb`.

**Core transform**, parameterised by saturation retention `s`:

```
out = (1 - L) + s * (rgb - L)
    = s*rgb - (1 + s)*L + 1
```

Read as: invert the lightness, keep the chroma (scaled by `s`).

As a 5x5 row-vector matrix: `M[i][j] = s*delta_ij - (1+s)*w_i`, translation row `(1,1,1)`.

`s` is a single knob spanning every useful mode:

| `s` | Behaviour | White | Black | Pure blue |
|---|---|---|---|---|
| `-1` | classic negative (hue flips) | black | white | yellow |
| `0`  | inverted greyscale | black | white | grey |
| `1`  | **hue-preserving dark mode** | black | white | light blue |
| `>1` | vivid (chroma boosted to offset perceived washout) | black | white | saturated light blue |

`s = 1` with equal weights is exactly NegativeScreen's "smart invert"; Rec.709 weights make
it perceptually correct rather than merely averaged.

**Post stages**, applied in this order, all affine and folded into the same matrix:

1. `contrast`  — `out = (out - 0.5)*c + 0.5`
2. `range`     — `out = lo + (hi - lo)*out`   (default `lo=0.05`, `hi=0.92`)
3. `warmth`    — per-channel gain, reduces blue for night use
4. `strength`  — final blend `M = lerp(Identity, M_dark, t)`; `t=0` is **exactly** identity

`strength` is the outermost blend so that dialing it to 0 restores the screen bit-exactly.

### Why range compression matters
Beyond comfort, it reduces gamut clipping. `s=1` can push a saturated channel above 1.0;
clipping shifts hue, which is the artefact this whole design exists to avoid. Pulling the
ceiling to `0.92` keeps more colours in gamut.

## 4. Contracts

```
compose(A, B)            -> matrix applying A then B          (row-vector convention)
apply(M, rgb)            -> clamped rgb' in [0,1]^3
build(params)            -> 5x5 matrix
Engine.start()/stop()/set_effect(M)/set_region(rect)
select_region()          -> Rect | None      (separate process, cancellable)
```

Invariants (unit tested):

- `build(strength=0)` == identity, and `apply` is a no-op for all inputs
- `s=1, lo=0, hi=1, c=1`: white -> black, black -> white, mid-grey -> mid-grey
- `s=1`: hue is preserved — argmax/argmin channel ordering of a colour is unchanged
- `s=-1`: output equals exactly `1 - rgb`
- `s=0`: output is achromatic (r == g == b) for every input
- `lo/hi`: white maps to `lo`, black maps to `hi`
- `compose` is associative; `compose(I, M) == M`
- every produced matrix maps `[0,1]^3` into `[0,1]^3` after clamping, with no NaN

## 5. Edge cases and constraints

- **Not supported under WOW64.** Requires 64-bit Python. Detect and fail with a clear message.
- **Full-screen colour effect is Windows 8+.** Region engine works on Vista+.
- **Stuck-inverted screen.** If the process is killed, the effect can persist. Mitigations:
  `atexit` + console-ctrl handler + top-level exception handler all reset to identity, plus a
  standalone `umbra reset` command.
- **Windows "Color filters" accessibility setting** conflicts; detect and warn.
- **DRM / protected video** (Netflix, some players) renders in a hardware overlay the
  magnifier cannot read — those regions stay untransformed. Documented, not fixable.
- **DPI.** Process is Per-Monitor-Aware-V2 so region coordinates are physical pixels.
- **Region engine must exclude its own host window** from magnification via
  `MagSetWindowFilterList(MW_FILTERMODE_EXCLUDE)`, or it feeds back on itself.
- **Multi-monitor region select** must span the virtual desktop, not just the primary display.
- Region select runs as a **separate process** so its GUI loop cannot conflict with, or crash,
  the main Win32 message loop.

## 6. Measured accuracy

`umbra.reference` holds light/dark colour pairs from GitHub Primer, VS Code and
Tailwind. `umbra compare` scores any preset against them in Oklab.

| transform | mean dE | leave-one-out |
|---|---|---|
| naive negative | 0.219 | — |
| HSL lightness inversion | 0.129 | — |
| plain luma inversion (`dark`) | 0.090 | — (never fitted) |
| free 3x3+offset least-squares fit | 0.064 | 0.080 |
| **tuned 4-parameter family (`theme`)** | **0.064** | **0.076** |

The free 12-parameter fit overfits 18 pairs: it wins in-sample and loses on
cross-validation. The 4-parameter family generalises better *and* stays
hue-preserving by construction, so it is what ships.

Structural ceiling, confirmed by the residuals: an affine transform cannot keep
bright saturated accents bright (`amber-600` -> `amber-400`), because that is a
decision about contrast against the new background rather than a function of the
input colour. Worst-case dE 0.20 on amber. Fixing it requires a non-linear
saturation-aware transform and therefore a different engine.

## 7. Out of scope (v1)

Non-linear/gamma-correct inversion, photo detection, per-application rules, system tray icon,
macOS/Linux backends.
