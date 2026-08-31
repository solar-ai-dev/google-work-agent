import type { ReactNode } from "react";
import { API_CONTRACT_VERSION } from "../api/contract";

export type ApiCompatibility = "PENDING" | "COMPATIBLE" | "INCOMPATIBLE" | "UNAVAILABLE";

type Props = {
  compatibility: ApiCompatibility;
  serverApiContractVersion: string | null;
  fallback: ReactNode;
  children: ReactNode;
};

export function ApiCompatibilityGate({
  compatibility,
  serverApiContractVersion,
  fallback,
  children,
}: Props): JSX.Element {
  if (
    compatibility !== "COMPATIBLE"
    || serverApiContractVersion !== API_CONTRACT_VERSION
  ) {
    return <>{fallback}</>;
  }
  return <>{children}</>;
}
