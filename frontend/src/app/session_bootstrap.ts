import { bootstrapSession } from "../api";
import type { BootstrapResponse } from "../api/contract";

export type BootstrapFragment = {
  bootstrapSecret: string;
  serviceInstanceId: string;
};

export function readBootstrapFragment(hash: string): BootstrapFragment | null {
  const source = hash.startsWith("#") ? hash.slice(1) : hash;
  if (!source) return null;
  const params = new URLSearchParams(source);
  const bootstrapSecret =
    params.get("bootstrap_secret") ?? params.get("bootstrapSecret") ?? params.get("bootstrap");
  const serviceInstanceId =
    params.get("service_instance_id") ?? params.get("serviceInstanceId");
  if (!bootstrapSecret || !serviceInstanceId) return null;
  return { bootstrapSecret, serviceInstanceId };
}

export async function bootstrapLocalSession(
  fragment: BootstrapFragment,
  clearFragment: () => void = clearBrowserFragment,
): Promise<BootstrapResponse> {
  try {
    const response = await bootstrapSession({ bootstrap_secret: fragment.bootstrapSecret });
    if (response.service_instance_id !== fragment.serviceInstanceId) {
      throw new Error("Bootstrap response service instance does not match the launch fragment.");
    }
    return response;
  } finally {
    clearFragment();
  }
}

function clearBrowserFragment(): void {
  window.history.replaceState(
    null,
    "",
    `${window.location.pathname}${window.location.search}`,
  );
}
