import type { ReactNode } from "react";

import { Moldura } from "@/componentes/moldura";

import "./app.css";

export default function LayoutDoApp({ children }: { children: ReactNode }) {
  return <Moldura>{children}</Moldura>;
}
