import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "Miraaj — Video Studio", description: "Turn a script and talking-head recording into a polished short." };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
