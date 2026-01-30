# Color Gradient Design

## Status: Not Yet Implemented

## Problem

Current color mapping uses 10 discrete bands (2h each, green → purple).
Hard boundaries between bands — a 3h59m cell looks identical to a 2h01m cell,
then jumps abruptly at 4h. Wastes visual bandwidth.

## Solution: Continuous HSL Ramp + Gamma Slider

Two changes:
1. Replace discrete band lookup with continuous HSL interpolation
2. Add a gamma slider to let the user focus color resolution where they care

### Continuous Color Function

```
t = clamp(hours / 24, 0, 1)
hue = lerp(140, 270, t)       // green → purple
sat = lerp(80, 60, t)         // slightly desaturate far destinations
lum = lerp(55, 20, t)         // darken toward far end
→ hsl(hue, sat%, lum%)
```

No lookup table, no bands. Every cell gets a unique color proportional to
its exact travel time. ~15 lines of code, no dependencies.

Note: HSL interpolation is imperfect (perceptual non-uniformity around
yellow/cyan), but good enough for this use case. Upgrade path to oklab
if it looks muddy.

### Gamma Slider

Warps the linear mapping with a power curve:

```
t = (hours / 24) ^ gamma
```

#### Effect of gamma values

```
gamma=0.3              gamma=1.0              gamma=3.0
 0h     12h     24h     0h     12h     24h     0h     12h     24h
 |██████░░░░░░░░|       |████████░░░░░░|       |████████████░░|
 green·····purple       green·····purple       green······purple
 (spread near end)      (linear)               (spread far end)
```

- **gamma < 1** — more color differentiation for short trips (2-8h),
  long trips compress into deep purple. the default sweet spot for
  "what can i reach easily"
- **gamma = 1** — even spread, equivalent to current behavior but smooth
- **gamma > 1** — more resolution for distant destinations, nearby all
  looks green. useful for exploring "what's hard to reach"

### UI

```
┌──────────────────────────────────┐
│ color focus:                     │
│ near [·····|·····] far    [auto] │
└──────────────────────────────────┘
```

- slider maps gamma range ~0.2 to ~3.0 on a log scale
- center position = gamma 1.0 (linear)
- dragging left = gamma < 1 (spread near)
- dragging right = gamma > 1 (spread far)
- label: "color focus: near ←→ far" (don't expose the word "gamma")

### Auto-Fit Button

Computes optimal gamma from the current data distribution:

```
median_hours = median of all visible cell travel times
gamma = ln(0.5) / ln(median_hours / 24)
```

This sets gamma so the median travel time maps to `t=0.5` (the visual
midpoint of the color ramp). User can nudge from there.

### Legend

Replace discrete color swatches with a continuous gradient bar:

```
┌────────────────────────────────┐
│ ██████████████████████████████ │  ← continuous gradient
│ 0h    4h    8h   12h   18h 24h│  ← tick marks
└────────────────────────────────┘
```

Tick marks shift with gamma — when gamma < 1, the ticks bunch up toward
the right (reflecting compressed long-time colors).

### Changes Required

- `getTimeBandColor()` → replace with continuous `getTimeColor(minutes, gamma)`
- `TIME_BANDS` array → remove (or keep as tooltip reference only)
- legend HTML → swap swatches for a canvas/CSS gradient bar
- add slider + auto button to settings panel
- gamma state stored alongside origin selection

### Migration

Backwards compatible — gamma=1.0 with the same hue endpoints will look
nearly identical to current discrete bands, just smoother.
