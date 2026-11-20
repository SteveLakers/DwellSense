import {
  NYC_BOROUGHS,
  NYC_OUTLINE_HEIGHT,
  NYC_OUTLINE_WIDTH,
  milesToOutlineUnits,
  projectLngLat,
} from "@/lib/nycOutline";
import { EXAMPLE_ADDRESS, EXAMPLE_LNG_LAT, SCAN_RADIUS_MILES } from "@/lib/site";

const [CX, CY] = projectLngLat(...EXAMPLE_LNG_LAT);
const R = milesToOutlineUnits(SCAN_RADIUS_MILES);
const STREET = EXAMPLE_ADDRESS.split(",")[0];
const TITLE = `Map of the five boroughs of New York City with a ${SCAN_RADIUS_MILES}-mile circle around ${STREET}`;

// Positions are in outline units (see lib/nycOutline.ts); Manhattan runs along the island.
const LABELS: { name: string; x: number; y: number; rotate?: number }[] = [
  { name: "The Bronx", x: 398, y: 84 },
  { name: "Queens", x: 448, y: 268 },
  { name: "Brooklyn", x: 314, y: 366 },
  { name: "Staten Island", x: 104, y: 452 },
  { name: "Manhattan", x: 318, y: 118, rotate: -66 },
];

/** The five boroughs from NYC Open Data, with the scan radius drawn to scale around EXAMPLE_ADDRESS. Colors assume the black hero band. */
export default function NycRadiusMap() {
  return (
    <figure className="w-full">
      <svg
        viewBox={`0 0 ${NYC_OUTLINE_WIDTH} ${NYC_OUTLINE_HEIGHT}`}
        className="h-auto w-full overflow-visible"
        role="img"
        aria-labelledby="nyc-radius-title"
      >
        <title id="nyc-radius-title">{TITLE}</title>
        <g className="fill-in fill-ink-2 stroke-ink-muted" strokeWidth={1.1} strokeLinejoin="round">
          {NYC_BOROUGHS.map((b) => (
            <path key={b.name} d={b.d} pathLength={1} className="draw-in" />
          ))}
        </g>
        <g className="fade-late fill-[#8A897F] text-[14px] font-semibold" textAnchor="middle">
          {LABELS.map((l) => (
            <text
              key={l.name}
              x={l.x}
              y={l.y}
              transform={l.rotate ? `rotate(${l.rotate} ${l.x} ${l.y})` : undefined}
            >
              {l.name}
            </text>
          ))}
        </g>

        <g className="fill-none stroke-brand" strokeWidth={2}>
          <circle cx={CX} cy={CY} r={R} vectorEffect="non-scaling-stroke" className="sonar" />
          <circle cx={CX} cy={CY} r={R} vectorEffect="non-scaling-stroke" className="sonar sonar-late" />
        </g>
        <g className="pop-in">
          <circle cx={CX} cy={CY} r={R} className="fill-brand" />
          <circle cx={CX} cy={CY} r={3.4} className="fill-fg" />
        </g>

        <g className="fade-late">
          <path d={`M${CX - R - 4} ${CY}H${CX - R - 26}`} className="stroke-white" strokeWidth={1.5} />
          <text x={CX - R - 32} y={CY - 1} textAnchor="end" className="fill-white text-[17px] font-bold">
            {STREET}
          </text>
          <text x={CX - R - 32} y={CY + 18} textAnchor="end" className="fill-ink-muted text-[15px]">
            {SCAN_RADIUS_MILES}-mile radius
          </text>
        </g>

        <g
          transform={`translate(${NYC_OUTLINE_WIDTH - R - 34} ${NYC_OUTLINE_HEIGHT - 30})`}
          className="fade-late fill-ink-muted text-[13px]"
        >
          <path d={`M0 0V6H${R}V0`} fill="none" className="stroke-white" strokeWidth={1.5} />
          <text x={0} y={23} textAnchor="middle">
            0
          </text>
          <text x={R} y={23} textAnchor="middle">
            {SCAN_RADIUS_MILES} mi
          </text>
        </g>
      </svg>
      <figcaption className="mt-4 max-w-sm text-[15px] leading-snug text-ink-muted lg:ml-auto lg:text-right">
        Each report counts city records inside a {SCAN_RADIUS_MILES}-mile circle like this one.{" "}
        <span className="text-[#8A897F]">Borough boundaries: NYC Open Data.</span>
      </figcaption>
    </figure>
  );
}
