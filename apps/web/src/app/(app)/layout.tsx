import type { ReactNode } from "react";

import { Moldura } from "@/componentes/moldura";
import { SeletorDados } from "@/dev/seletor-dados";

import "./app.css";

export default function LayoutDoApp({ children }: { children: ReactNode }) {
  return (
    <Moldura>
      {children}
      {process.env.NODE_ENV === "development" && <SeletorDados />}
    </Moldura>
  );
}
