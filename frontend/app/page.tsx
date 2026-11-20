import type { Metadata } from "next";
import Footer from "@/components/Footer";
import HomeClient from "@/components/HomeClient";
import NycRadiusMap from "@/components/NycRadiusMap";

export const metadata: Metadata = {
  alternates: { canonical: "/" },
};

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col pt-16">
      <HomeClient heroAside={<NycRadiusMap />} />
      <Footer />
    </div>
  );
}
