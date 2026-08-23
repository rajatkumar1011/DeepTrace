import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DeepTrace | Digital Impersonation Evidence Assistance",
  description: "Victim-centred evidence preservation and forensic analysis support for suspected digital impersonation and deepfake incidents.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
