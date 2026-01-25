# Flight Time Isochrone Map - Implementation Spec

## Overview

Build an interactive map showing **multimodal travel time isochrones** from a configurable origin (default: Bristol, UK). Colors overlaid on real geography show total door-to-door travel time bands, combining ground transport to airport + flight time + ground transport at destination.

This is a Rome2Rio / Galton-style visualization: normal map projection, colored regions representing time-distance.

---

## Core Concept

**The insight we're visualizing**: A place 500 miles away but 5 minutes from a major airport hub is "closer" in travel-hours than a place 200 miles away requiring a 3-hour drive. Geography lies; travel time tells truth.

**Key differentiator from existing isochrone tools**: 
- Existing isochrone APIs max out at 60min and only support ground transport
- We're showing 1-14+ hour travel times combining air + ground
- All calculations done locally—no external routing APIs

---

## Tech Stack

- **MapLibre GL JS** - open source, no API key required
- **React** with raw MapLibre (not react-map-gl, keep dependencies minimal)
- **GeoJSON** for isochrone polygons
- **OpenFreeMap** tiles (https://openfreemap.org) - completely free, no key needed
- **Flight data**: User's flight MCPs or hardcoded dataset
- **Ground transport**: Haversine + speed assumptions (no external API)

---

## Data Model

### Origin Configuration
```typescript
interface Origin {
  name: string;           // "Bristol, UK"
  coordinates: [number, number]; // [lng, lat]
  nearestAirport: {
    code: string;         // "BRS" 
    name: string;         // "Bristol Airport"
    coordinates: [number, number];
    groundTimeMinutes: number; // time from origin to this airport
  };
  alternativeAirports: Array<{
    code: string;
    name: string;
    coordinates: [number, number];
    groundTimeMinutes: number;
  }>;  // e.g., LHR (2h by train), BHX (1.5h)
}
```

### Destination Grid
```typescript
interface GridCell {
  id: string;
  centroid: [number, number];
  polygon: GeoJSON.Polygon;
  totalTravelTimeMinutes: number | null; // null = unreachable
  breakdown: {
    groundToAirportMinutes: number;
    flightMinutes: number;
    groundFromAirportMinutes: number;
  };
  nearestAirport: string; // airport code used for this cell
}
```

### Time Bands (Galton-style)
```typescript
const TIME_BANDS = [
  { maxHours: 2,  color: '#22c55e', label: '< 2h' },
  { maxHours: 4,  color: '#84cc16', label: '2-4h' },
  { maxHours: 6,  color: '#eab308', label: '4-6h' },
  { maxHours: 8,  color: '#f97316', label: '6-8h' },
  { maxHours: 10, color: '#ef4444', label: '8-10h' },
  { maxHours: 12, color: '#dc2626', label: '10-12h' },
  { maxHours: 14, color: '#991b1b', label: '12-14h' },
  { maxHours: Infinity, color: '#450a0a', label: '14h+' },
];
```

---

## Travel Time Estimation

### Ground Transport Assumptions (No External API)

All ground transport estimated via haversine distance + regional speed assumptions:

```typescript
interface GroundSpeedProfile {
  urban: number;      // km/h within 20km of city center
  suburban: number;   // km/h 20-50km from city center  
  rural: number;      // km/h 50km+ from city center
  highway: number;    // km/h for known highway corridors
}

const DEFAULT_SPEEDS: GroundSpeedProfile = {
  urban: 25,      // traffic, stops
  suburban: 45,   // mixed
  rural: 70,      // open roads
  highway: 100,   // motorways
};

// Special cases - known rail/transit links
const FIXED_GROUND_TIMES: Record<string, Record<string, number>> = {
  'Bristol': {
    'BRS': 25,    // 25 min to Bristol Airport
    'LHR': 120,   // 2h by train to Heathrow
    'LGW': 150,   // 2.5h to Gatwick
    'BHX': 90,    // 1.5h to Birmingham
  },
  // Add more origins as needed
};

function estimateGroundTime(
  from: [number, number],
  to: [number, number],
  originCity?: string,
  destCode?: string
): number {
  // Check for known fixed times first
  if (originCity && destCode && FIXED_GROUND_TIMES[originCity]?.[destCode]) {
    return FIXED_GROUND_TIMES[originCity][destCode];
  }
  
  // Otherwise estimate from distance
  const distanceKm = haversineDistance(from, to);
  
  // Simple model: assume suburban average
  // Could enhance with urban/rural detection later
  const avgSpeedKmh = 40;
  return Math.round((distanceKm / avgSpeedKmh) * 60);
}
```

### Flight Time Sources

**Option A: User's Flight MCPs**
If available, query MCP for actual flight times:
```typescript
// Pseudocode - adapt to actual MCP interface
async function getFlightTime(from: string, to: string): Promise<number | null> {
  const result = await flightMCP.query({ origin: from, destination: to });
  return result?.durationMinutes ?? null;
}
```

**Option B: Hardcoded Dataset**
Fallback/default - manually curated routes:
```typescript
const FLIGHT_DATA: Record<string, Record<string, number>> = {
  'LHR': {
    'JFK': 480, 'LAX': 660, 'SFO': 660, 'ORD': 540,
    'CDG': 75, 'AMS': 75, 'FRA': 90, 'MAD': 150,
    'DXB': 420, 'SIN': 780, 'HKG': 720, 'NRT': 720,
    // ... expand as needed
  },
  'BRS': {
    'CDG': 90, 'AMS': 80, 'DUB': 55, 'EDI': 70,
    'AGP': 165, 'FAO': 175, 'PMI': 145,
    // ... regional routes
  },
  // Add more origin airports
};
```

**Option C: Great Circle Estimation**
For routes not in dataset, estimate from distance:
```typescript
function estimateFlightTime(fromCoords: [number, number], toCoords: [number, number]): number {
  const distanceKm = haversineDistance(fromCoords, toCoords);
  
  // Assumptions:
  // - 800 km/h cruise speed
  // - 30 min for takeoff/climb + descent/landing
  // - Add buffer for non-direct routing
  
  const cruiseTimeMin = (distanceKm / 800) * 60;
  const overhead = 30;
  const routingBuffer = cruiseTimeMin * 0.1; // 10% extra for non-direct
  
  return Math.round(cruiseTimeMin + overhead + routingBuffer);
}
```

### Total Travel Time Calculation

```typescript
function calculateTotalTravelTime(
  origin: Origin,
  destinationCoords: [number, number],
  destinationAirport: Airport
): TravelTimeResult {
  // 1. Find best origin airport (shortest total time)
  const airportOptions = [origin.nearestAirport, ...origin.alternativeAirports];
  
  let bestTime = Infinity;
  let bestRoute: RouteBreakdown | null = null;
  
  for (const originAirport of airportOptions) {
    // Ground: origin → airport
    const groundTo = estimateGroundTime(
      origin.coordinates,
      originAirport.coordinates,
      origin.name,
      originAirport.code
    );
    
    // Airport overhead (security, boarding, etc)
    const airportOverhead = 90; // minutes
    
    // Flight time
    const flight = getFlightTime(originAirport.code, destinationAirport.code)
      ?? estimateFlightTime(originAirport.coordinates, destinationAirport.coordinates);
    
    // Skip if no flight exists and distance is short (would drive)
    if (flight === null) continue;
    
    // Arrival overhead (deplane, customs, bags)
    const arrivalOverhead = isInternational(originAirport, destinationAirport) ? 60 : 30;
    
    // Ground: destination airport → destination
    const groundFrom = estimateGroundTime(
      destinationAirport.coordinates,
      destinationCoords
    );
    
    const total = groundTo + airportOverhead + flight + arrivalOverhead + groundFrom;
    
    if (total < bestTime) {
      bestTime = total;
      bestRoute = {
        originAirport: originAirport.code,
        destinationAirport: destinationAirport.code,
        groundToMinutes: groundTo,
        airportOverheadMinutes: airportOverhead,
        flightMinutes: flight,
        arrivalOverheadMinutes: arrivalOverhead,
        groundFromMinutes: groundFrom,
        totalMinutes: total,
      };
    }
  }
  
  return { totalMinutes: bestTime, route: bestRoute };
}
```

---

## Flight Data Strategy

### Primary: MCP Integration

The user has flight MCPs available. The implementation should:

1. **Define an interface** for flight data queries:
```typescript
interface FlightDataProvider {
  // Get direct flight time between two airports
  getFlightTime(from: string, to: string): Promise<number | null>;
  
  // Get all destinations reachable from an airport
  getDestinations(from: string): Promise<string[]>;
  
  // Check if route exists
  routeExists(from: string, to: string): Promise<boolean>;
}
```

2. **Implement MCP adapter** (user will customize):
```typescript
class MCPFlightProvider implements FlightDataProvider {
  // Adapt to user's specific MCP interface
  async getFlightTime(from: string, to: string): Promise<number | null> {
    // TODO: User implements based on their MCP
    throw new Error('Implement MCP integration');
  }
  // ...
}
```

3. **Fallback to static data** when MCP unavailable:
```typescript
class StaticFlightProvider implements FlightDataProvider {
  private data = HARDCODED_FLIGHTS;
  
  async getFlightTime(from: string, to: string): Promise<number | null> {
    return this.data[from]?.[to] ?? null;
  }
  // ...
}
```

### Secondary: Hardcoded Dataset

Baseline data for MVP / fallback. Focus on routes from UK airports:

```typescript
const HARDCODED_FLIGHTS = {
  // Bristol Airport (BRS) - regional
  'BRS': {
    'DUB': 55, 'EDI': 70, 'GLA': 75,           // UK/Ireland
    'AMS': 80, 'CDG': 90, 'BRU': 75,           // Near Europe
    'AGP': 165, 'PMI': 145, 'FAO': 175,        // Spain/Portugal
    'NCE': 120, 'GVA': 105,                     // France/Swiss
  },
  
  // London Heathrow (LHR) - major hub
  'LHR': {
    // Europe
    'CDG': 75, 'AMS': 75, 'FRA': 90, 'MAD': 150, 'FCO': 150,
    'ATH': 225, 'IST': 240, 'LIS': 165,
    
    // North America
    'JFK': 480, 'EWR': 480, 'BOS': 450, 'ORD': 540,
    'LAX': 660, 'SFO': 660, 'SEA': 600, 'MIA': 570,
    'YYZ': 480, 'YVR': 600,
    
    // Middle East
    'DXB': 420, 'DOH': 400, 'TLV': 285,
    
    // Asia
    'SIN': 780, 'HKG': 720, 'NRT': 720, 'ICN': 690,
    'BKK': 690, 'DEL': 510,
    
    // Africa
    'JNB': 660, 'CPT': 720, 'CAI': 300,
    
    // Oceania
    'SYD': 1320, 'MEL': 1350, 'AKL': 1500, // typically via stopover
  },
  
  // London Gatwick (LGW) - secondary hub
  'LGW': {
    'JFK': 490, 'MCO': 540,                    // US leisure
    'BCN': 120, 'PMI': 135, 'TFS': 270,       // Europe leisure
  },
  
  // Birmingham (BHX)
  'BHX': {
    'DXB': 430, 'AMS': 70, 'CDG': 85,
  },
};
```

### Tertiary: Great Circle Estimation

For any route not in dataset/MCP, estimate from coordinates:

```typescript
function estimateFlightFromDistance(
  fromCoords: [number, number],
  toCoords: [number, number]
): number {
  const distanceKm = haversineDistance(fromCoords, toCoords);
  
  // Model based on real flight data regression:
  // ~800 km/h effective speed for long haul
  // ~600 km/h effective for short haul (more overhead proportionally)
  
  const isShortHaul = distanceKm < 1500;
  const effectiveSpeed = isShortHaul ? 600 : 800;
  
  const flightMin = (distanceKm / effectiveSpeed) * 60;
  const fixedOverhead = 25; // takeoff + landing
  
  return Math.round(flightMin + fixedOverhead);
}
```

---

## Grid Generation

### Approach: Hexagonal Grid
Use H3 or similar for consistent cell sizes:

```typescript
import { latLngToCell, cellToBoundary } from 'h3-js';

function generateGrid(
  bounds: { north: number; south: number; east: number; west: number },
  resolution: number = 4 // ~1700 km² cells at res 4, ~250 km² at res 5
): GridCell[] {
  const cells: GridCell[] = [];
  // Generate H3 cells covering bounds
  // For each cell, find nearest airport and compute travel time
  return cells;
}
```

### Alternative: Voronoi from Airports
Generate Voronoi polygons around destination airports, color by travel time to that airport.

---

## UI Components

### Map View
```
┌─────────────────────────────────────────────────────────┐
│  [Origin selector ▼]  [Show airports ☑]  [Show grid ☑]  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│                    ┌───────────┐                        │
│                    │  LEGEND   │                        │
│                    │ < 2h  ███ │                        │
│     ████████       │ 2-4h  ███ │                        │
│   ██████████████   │ 4-6h  ███ │                        │
│  ███████████████   │ ...       │                        │
│   █████LHR██████   └───────────┘                        │
│     ████████                                            │
│       ████    [MAP WITH COLORED REGIONS]                │
│                                                         │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  Hover: Paris (CDG) - 3h 45m total                      │
│  └─ 2h train to LHR + 90min overhead + 1h 15m flight    │
└─────────────────────────────────────────────────────────┘
```

### Interactions
- **Hover**: Show detailed breakdown for any cell/region
- **Click**: Pin tooltip, show routing details
- **Origin selector**: Change starting point
- **Toggle layers**: Show/hide airports, flight routes, grid

---

## Implementation Steps

### Step 1: Basic Map (1-2 hours)
- [ ] Set up React + MapLibre
- [ ] Display base map centered on UK/Europe
- [ ] Add origin marker

### Step 2: Static Isochrones (2-3 hours)
- [ ] Create hardcoded GeoJSON for time bands
- [ ] Style with fill colors + transparency
- [ ] Add legend component

### Step 3: Airport Layer (1 hour)
- [ ] Add markers for airports
- [ ] Show routes on hover (optional)

### Step 4: Dynamic Computation (3-4 hours)
- [ ] Implement travel time estimation
- [ ] Generate grid cells
- [ ] Color cells by computed time

### Step 5: Interactivity (2 hours)
- [ ] Hover tooltips with breakdown
- [ ] Origin selector
- [ ] Layer toggles

### Step 6: Polish (2 hours)
- [ ] Mobile responsive
- [ ] Loading states
- [ ] Error handling

---

## File Structure

```
src/
├── components/
│   ├── Map.tsx              # Main map component
│   ├── Legend.tsx           # Color legend
│   ├── OriginSelector.tsx   # Dropdown to change origin
│   └── Tooltip.tsx          # Hover/click info panel
├── data/
│   ├── airports.ts          # Airport locations + codes
│   ├── flights.ts           # Flight routes + times
│   └── origins.ts           # Pre-configured origins
├── lib/
│   ├── travelTime.ts        # Travel time calculations
│   ├── grid.ts              # Grid generation (H3 or custom)
│   └── geo.ts               # Haversine, projections, etc.
├── styles/
│   └── map.css              # MapLibre overrides
└── App.tsx
```

---

## Open Questions for Implementer

1. **Grid resolution**: How fine? Coarser = faster, finer = more accurate but slow. Recommend H3 resolution 3-4 for continental scale.

2. **Bounds**: Start with Europe + North America. Can expand to global later.

3. **Airport selection logic**: Current spec tries ALL origin airports and picks fastest total time. This handles the "is it faster to train to LHR or fly direct from BRS?" question automatically.

4. **Hub routing**: MVP assumes direct flights only. Phase 2 could add: "if no direct flight, try routing via LHR/FRA/DXB".

5. **Ground transport edge cases**:
   - Islands (need ferry time?)
   - Mountain regions (slower roads?)
   - For MVP, just use distance-based estimate with regional overrides

---

## MCP Integration Notes

The user has flight MCPs available. Implementation should:

1. **Abstract the data source** behind `FlightDataProvider` interface
2. **Provide a stub** that user can fill in with their MCP calls
3. **Include fallback** to static data so app works without MCP
4. **Cache aggressively** - flight times don't change often

Example integration point:
```typescript
// User edits this file to connect their MCP
// src/data/flightProvider.ts

import { FlightDataProvider } from '../lib/types';

// Option 1: Use MCP
export const flightProvider: FlightDataProvider = {
  async getFlightTime(from, to) {
    // User's MCP call here
    const result = await myFlightMCP.lookup(from, to);
    return result?.duration ?? null;
  },
  // ...
};

// Option 2: Use static data (default)
// import { StaticFlightProvider } from './staticFlights';
// export const flightProvider = new StaticFlightProvider();
```

---

## Sample Output (Pseudocode)

```javascript
// After computation, GeoJSON looks like:
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {
        "travelTimeMinutes": 225,
        "timeBand": "2-4h",
        "color": "#84cc16",
        "nearestAirport": "CDG",
        "breakdown": {
          "groundTo": 120,
          "flight": 75,
          "groundFrom": 30
        }
      },
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[2.3, 48.8], [2.4, 48.8], ...]]
      }
    },
    // ... more cells
  ]
}
```

---

## Success Criteria

1. **Loads in < 3 seconds** with pre-computed data
2. **Visually matches Rome2Rio style**: colored regions over real geography
3. **Accurate-ish**: Within ~30min of actual travel time for major routes
4. **Interactive**: Hover shows breakdown, origin can be changed
5. **Shareable**: Can screenshot or embed

---

## Dependencies

```json
{
  "dependencies": {
    "maplibre-gl": "^4.0.0",
    "h3-js": "^4.0.0",
    "react": "^18.0.0",
    "react-dom": "^18.0.0"
  }
}
```

No API keys required. OpenFreeMap tiles are free and keyless.

---

## Map Tiles Setup

```typescript
// Use OpenFreeMap - no key needed
const MAP_STYLE = 'https://tiles.openfreemap.org/styles/liberty';

// Alternative styles:
// 'https://tiles.openfreemap.org/styles/bright'
// 'https://tiles.openfreemap.org/styles/positron'
```

---

## References

- Rome2Rio 1914 vs 2016 comparison map
- Francis Galton 1881 Isochronic Passage Chart
- Spiekermann & Wegener time-space maps
- L'Hostis "Shrivelled USA" paper
- MapLibre GL JS docs: https://maplibre.org/maplibre-gl-js/docs/
- H3 hexagonal grid: https://h3geo.org/
- OpenFreeMap: https://openfreemap.org/
