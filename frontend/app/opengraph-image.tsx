import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { ImageResponse } from "next/og";
import { SITE_URL } from "@/lib/site";

export const alt = "ZerMap: check an NYC address before you sign a lease";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const INK = "#151515";
const TAXI = "#FFCC00";
const CHECK = 16;

/** One row of the taxi checker stripe; Satori has no conic-gradient, so it is drawn as squares. */
function CheckerRow({ offset }: { offset: number }) {
  return (
    <div style={{ display: "flex" }}>
      {Array.from({ length: Math.ceil(size.width / CHECK) }, (_, i) => (
        <div key={i} style={{ width: CHECK, height: CHECK, background: (i + offset) % 2 ? TAXI : INK }} />
      ))}
    </div>
  );
}

/** Static Archivo cuts (OFL, assets/fonts): Satori can't select a width from the variable font the site uses. */
async function loadFonts() {
  const dir = join(process.cwd(), "assets/fonts");
  const [condensed, text] = await Promise.all([
    readFile(join(dir, "ArchivoCondensed-ExtraBold.ttf")),
    readFile(join(dir, "Archivo-Medium.ttf")),
  ]);
  return [
    { name: "Archivo Condensed", data: condensed, weight: 800 as const, style: "normal" as const },
    { name: "Archivo", data: text, weight: 500 as const, style: "normal" as const },
  ];
}

export default async function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: INK,
          color: "#FFFFFF",
          fontFamily: "Archivo",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", padding: "56px 72px 0" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
              <svg width="60" height="60" viewBox="0 0 64 64">
                <rect width="64" height="64" rx="9" fill={TAXI} />
                <path d="M18 18h28v6L27 40h19v6H18v-6l19-16H18z" fill={INK} />
              </svg>
              <div style={{ display: "flex", fontFamily: "Archivo Condensed", fontSize: 52 }}>ZerMap</div>
            </div>
            <div style={{ display: "flex", fontSize: 28, color: "#B4B3AA" }}>{new URL(SITE_URL).host}</div>
          </div>
          <div style={{ display: "flex", height: 4, marginTop: 40, background: "#FFFFFF" }} />
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              marginTop: 38,
              fontFamily: "Archivo Condensed",
              fontSize: 150,
              lineHeight: 0.9,
              letterSpacing: -1,
            }}
          >
            <div style={{ display: "flex" }}>Don’t sign a</div>
            <div style={{ display: "flex" }}>blind lease.</div>
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <CheckerRow offset={0} />
          <CheckerRow offset={1} />
          <div
            style={{
              display: "flex",
              alignItems: "center",
              height: 104,
              padding: "0 72px",
              background: TAXI,
              color: INK,
              fontSize: 32,
            }}
          >
            Official NYC data about the block, before you sign a lease.
          </div>
        </div>
      </div>
    ),
    { ...size, fonts: await loadFonts() },
  );
}
