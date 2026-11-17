import type { Metadata, Viewport } from "next";
import { Libre_Franklin, Source_Serif_4 } from "next/font/google";
import type { ReactNode } from "react";

import { Providers } from "./providers";
import "./globals.css";

const franklin = Libre_Franklin({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--fonte-franklin",
  display: "swap",
});

const serifa = Source_Serif_4({
  subsets: ["latin"],
  weight: ["400", "600"],
  style: ["normal", "italic"],
  variable: "--fonte-serifa",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "Confere: seu currículo, conferido", template: "%s · Confere" },
  description:
    "Envie o currículo e a vaga e veja cada requisito com o trecho que o comprova, ou a falta dele. A nota é uma conta à vista.",
};

export const viewport: Viewport = {
  themeColor: "#F7F7F4",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="pt-BR" className={`${franklin.variable} ${serifa.variable}`}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
