import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Set a new password",
};

export default function UpdatePasswordLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
