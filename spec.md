# Flight Time Cartogram: Exploratory Prototypes

## The Core Insight

Geography lies. A map shows Tokyo and Sydney as roughly equidistant from LA, but one is 11 hours away and the other is 15. Hub cities cluster together in "travel space" while remote places balloon outward. Nobody's built a good interactive visualization of this—the pieces exist, but they haven't been assembled into something playful and shareable.

---

## Prototype 1: The Breathing Map

### Concept
Click a city. It slides to center. Every other city animates to its new position based on flight time from your selection. The world "breathes" differently from each origin.

### Core Interaction
- Tap/click any city dot → it becomes the new origin
- All cities animate outward to distance = flight time (hours)
- Bearing preserved (Tokyo stays "northwest-ish" from LA)
- Spring physics: overshoot + settle, cities feel like they have mass

### Visual Design
- **Dots**: sized by connectivity (hubs = big, regionals = small)
- **Color**: encode true geographic bearing as hue (north=blue, south=red, etc.) so spatial intuition partially survives the warp
- **Trails**: brief ghosting shows where cities *were* before they moved
- **Labels**: top 20 cities always labeled, others on hover
- **Background**: faint continental outlines at 10% opacity as "ghost geography"

### Data Requirements
- ~100-200 cities with lat/lon
- Pairwise flight times (or at minimum: time from each city to every other, can be asymmetric)
- Connectivity score (number of direct routes or passenger volume)

### Tech Stack Options
- **d3.js + force simulation**: reconfigure rest lengths on origin switch, let physics settle
- **Framer Motion + React**: smoother spring animations, easier state management
- **Canvas/WebGL**: if 200+ cities cause DOM perf issues

### Open Questions
- How to handle missing routes? Show as "infinite" distance? Fade out?
- Should we show the numeric time on hover or let the spatial distance speak?
- Mobile: tap is fine, but how to browse without a cursor?

---

## Prototype 2: Side-by-Side Comparisons

### Concept
Show 2-4 warped maps simultaneously with different origins. The *differential* is the insight—NYC snaps close to London but stretches from São Paulo.

### Layout Options
- 2x2 grid with sync'd hover (highlight same city across all views)
- Swipeable cards on mobile
- "Compare" mode: pick 2 origins, see cities colored by which origin they're closer to

### Why This Matters
Single-origin view shows one perspective. Comparison reveals **hub privilege**—some origins make everywhere accessible, others make everywhere far.

### Specific Comparisons Worth Highlighting
- London vs São Paulo (Atlantic asymmetry)
- Dubai vs Singapore (competing mega-hubs)
- Denver vs Chicago (US domestic hub vs spoke)
- Tokyo vs Sydney (Asia-Pacific structure)

---

## Prototype 3: The Asymmetry Explorer

### Concept
Flight times aren't symmetric. A→B ≠ B→A due to:
- Prevailing winds (jet stream)
- Hub structures (connections only work one direction at certain times)
- Timezone effects on scheduling

Show both directions simultaneously.

### Visual Approach
- Two dots per city-pair connected by a line
- Line thickness = magnitude of asymmetry
- Arrow direction = which way is faster
- Click a city to see all its asymmetric relationships

### Data Challenge
This requires *scheduled* flight times, not just great-circle estimates. Probably needs real OAG/Cirium data or scraping.

---

## Prototype 4: Historical Morph

### Concept
Same origin, watch the map change from 1970 → 2024 as routes opened, hubs emerged, budget carriers exploded.

### Key Eras
- **Pre-deregulation** (before 1978): limited routes, national carriers
- **Hub-and-spoke emergence** (1980s-90s): Delta/Atlanta, United/Chicago
- **Gulf carrier rise** (2000s-10s): Dubai/Doha/Abu Dhabi become global connectors
- **Budget airline explosion**: Ryanair, Southwest, etc. create weird new shortcuts
- **Concorde era**: briefly, NYC-London was 3 hours

### Interaction
- Timeline scrubber
- Play button for animation
- "What changed?" annotations at key moments

### Data Challenge
Historical schedules are hard to find. Might need to approximate or focus on a few well-documented routes.

---

## Prototype 5: Personal Accessibility Map

### Concept
"How connected am I?" Enter YOUR home airport, see your personal topology.

### Features
- Input: home airport (autocomplete)
- Output: warped map from your perspective
- Overlays: "places I can reach in <4 hours" / "<8 hours" / ">12 hours"
- Shareable: generate a card/image "My world from DEN"

### Why It's Shareable
Everyone wants to see their own situation. "Look how far everything is from Omaha" is relatable content.

---

## Prototype 6: The Missed Connection

### Concept
Show how the map warps when you *just miss* a connection.

### Interaction
- Select origin + destination
- Slider: "your delay" (0 to 4 hours)
- Watch the destination (and everything connected through it) drift farther as delay increases
- 2-hour delay might make Tokyo go from 14 hours to 26 hours away

### Emotional Payload
This is the "visceral dread" visualization. Makes schedule fragility tangible.

---

## Data Strategy

### Minimum Viable Dataset
- ~100 major airports with coordinates
- Estimated flight times (can use great-circle distance + 500mph + 45min overhead as rough proxy)
- Works for prototyping interactions

### Better Dataset
- OpenFlights database (free, ~7,000 routes)
- Compute shortest path through network for non-direct routes
- Still won't capture schedule-dependent connections

### Ideal Dataset
- OAG or Cirium scheduled data
- Actual departure/arrival times
- Can compute real connection times including layovers
- Expensive / requires partnership

### Recommendation
Start with synthetic/estimated data to prove the interaction model. If it's compelling, pursue real data partnerships.

---

## Success Criteria

### For Prototypes
- Does switching origins feel satisfying? (spring physics matter)
- Can you "read" the map—does spatial intuition survive?
- Do people want to click around and explore?
- Is the insight ("hubs cluster, remote places stretch") immediately obvious?

### For a Polished Product
- Shareable (generate images/cards)
- Embeddable (travel blogs, news articles)
- Accessible (works on mobile, keyboard nav, screen reader descriptions)
- Fast (200 cities animate at 60fps)

---

## Non-Goals (For Now)

- Real-time flight tracking
- Booking integration
- Price data
- Multi-leg trip planning
- Carbon footprint calculations (interesting but scope creep)

---

## Next Steps

1. **Build Prototype 1** with ~30 hardcoded cities and fake flight times. Prove the breathing map interaction feels good.
2. **Test bearing-preservation vs pure radial**—does keeping "Tokyo in the northwest" help or confuse?
3. **Get feedback on spring physics tuning**—how much bounce feels playful vs annoying?
4. **If interaction works**, expand to 100+ cities with OpenFlights data.
5. **If people love it**, pursue real schedule data for asymmetry/historical views.

---

## Appendix: Why This Doesn't Exist Yet

- Data wrangling is annoying (flight times aren't a simple lookup)
- Cartographers are conservative (bouncy toy maps feel "unserious")
- Interaction designers don't care about geography
- Falls between disciplines—too frivolous for GIS, too data-heavy for creative coding, too niche for product companies

This is a gap worth filling.