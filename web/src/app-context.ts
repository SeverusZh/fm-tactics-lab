import { createContext, useContext } from "react";

import type { Health } from "./lib/api";
import type { Connection } from "./lib/connection";

export type AppContextValue = {
  connection: Connection | null;
  health: Health | null;
  connectionError: string | null;
  refresh: () => void;
};

export const AppContext = createContext<AppContextValue | null>(null);

export function useAppContext(): AppContextValue {
  const value = useContext(AppContext);
  if (value === null) {
    throw new Error("useAppContext must be used inside AppContext");
  }
  return value;
}
