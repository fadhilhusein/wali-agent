import type { Metadata, Viewport } from "next";
import "@fontsource/poppins/latin-500.css";
import "@fontsource/poppins/latin-600.css";
import "./globals.css";

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  interactiveWidget: "resizes-content",
};

export const metadata: Metadata = {
  title: "Wali | Financial workspace",
  description:
    "A local simulation workspace for financial conversations and approvals.",
  icons: {
    icon: [{ url: "/brand/wali.svg", type: "image/svg+xml" }],
    apple: [
      { url: "/brand/wali-180.png", sizes: "180x180", type: "image/png" },
    ],
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
