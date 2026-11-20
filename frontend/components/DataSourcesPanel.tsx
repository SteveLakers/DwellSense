import { DataSource } from "@/lib/types";
import { formatCount, formatDateRange, formatIsoDay, plural } from "@/lib/format";
import SectionHeading from "./SectionHeading";

interface Props {
  dataSources: DataSource[];
  /** Day (YYYY-MM-DD) the NYC comparison counts were measured; the line is left out when unknown. */
  comparisonAsOf?: string | null;
}

export default function DataSourcesPanel({ dataSources, comparisonAsOf }: Props) {
  if (!dataSources.length) return null;
  const comparisonDay = formatIsoDay(comparisonAsOf);

  return (
    <section aria-labelledby="data-as-of" className="wrap mt-20 lg:mt-28">
      <SectionHeading
        id="data-as-of"
        title="Data as of"
        description="The records behind each count, with their date range and the newest record each source had published."
        size="md"
      />
      <table className="mt-8 w-full border-collapse border-t-2 border-fg text-left text-[15px] sm:border-t-0">
        <thead className="hidden sm:table-header-group">
          <tr className="border-b-2 border-fg text-sm text-fg-3">
            <th scope="col" className="w-[36%] pb-3 pr-6 font-semibold">Source</th>
            <th scope="col" className="w-[24%] pb-3 pr-6 font-semibold">Records used</th>
            <th scope="col" className="pb-3 font-semibold">Date range</th>
          </tr>
        </thead>
        <tbody>
          {dataSources.map((src) => {
            const count = src.status === "ok" ? src.count : null;
            const range = src.status === "ok" ? formatDateRange(src.window_start, src.window_end) : null;
            const newest = src.status === "ok" ? formatIsoDay(src.as_of) : null;
            return (
              <tr key={src.key} className="block border-b border-line py-4 sm:table-row sm:py-0">
                <th scope="row" className="block font-semibold text-fg sm:table-cell sm:py-4 sm:pr-6 sm:align-top">
                  {src.label}
                </th>
                <td className="mt-1 block sm:mt-0 sm:table-cell sm:py-4 sm:pr-6 sm:align-top">
                  {count != null ? (
                    <span className="tnum font-semibold text-fg">
                      {formatCount(count)} {src.key === "flights" ? plural(count, "position") : plural(count, "record")}
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-2 font-semibold text-fg-2">
                      <span aria-hidden className="hatch h-3 w-3 border border-fg-3" />
                      Unavailable
                    </span>
                  )}
                </td>
                <td className="mt-1 block text-fg-2 sm:mt-0 sm:table-cell sm:py-4 sm:align-top">
                  {range ? <span className="block">{range}</span> : null}
                  {newest ? <span className="block text-sm text-fg-3">Newest record {newest}</span> : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-5 max-w-3xl text-sm leading-relaxed text-fg-3">
        Not live: NYPD publishes its data quarterly, so its counts end at the newest records NYPD has released. Map pins
        are a sample of the newest records; counts and the Wellness Score use every record in range.
        {comparisonDay
          ? ` The NYC comparison counts (apartment locations across the city) were last measured on ${comparisonDay}.`
          : null}
      </p>
    </section>
  );
}
