import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Smart Ward · AI Monitor",
  description: "Research patient monitoring with local trained models",
  appleWebApp: { capable: true, title: "Smart Ward", statusBarStyle: "default" },
  icons: { icon: "/smart-ward-mark.svg", apple: "/smart-ward-180.png" },
};

export const viewport: Viewport = { themeColor: "#176e53", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="th"
      className="h-full antialiased"
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
