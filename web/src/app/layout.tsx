import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Kalam, Space_Grotesk } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const spaceGrotesk = Space_Grotesk({ subsets: ["latin"], variable: "--font-space-grotesk", weight: ["500", "700"] });
const kalam = Kalam({ subsets: ["latin"], variable: "--font-kalam", weight: ["400", "700"] });
const jetbrains = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains" });

export const metadata: Metadata = {
  title: "BoardNotes",
  description: "Lecture videos turned into cited notes students can trust",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${inter.variable} ${spaceGrotesk.variable} ${kalam.variable} ${jetbrains.variable}`}>
      <body>{children}</body>
    </html>
  );
}
