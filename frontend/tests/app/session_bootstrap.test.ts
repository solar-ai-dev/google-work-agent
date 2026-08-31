import { beforeEach, describe, expect, test, vi } from "vitest";
import { bootstrapLocalSession, readBootstrapFragment } from "../../src/app/session_bootstrap";
import { bootstrapSession } from "../../src/api";

vi.mock("../../src/api", () => ({ bootstrapSession: vi.fn() }));

const response = {
  schema_version: 1 as const,
  session_established: true,
  service_instance_id: "service-1",
  api_contract_version: "1",
  compatibility: "COMPATIBLE" as const,
};

describe("bootstrapLocalSession", () => {
  beforeEach(() => vi.mocked(bootstrapSession).mockReset());

  test("reads the one-time secret only from the URL fragment", () => {
    expect(readBootstrapFragment("#bootstrap_secret=secret&service_instance_id=service-1")).toEqual({
      bootstrapSecret: "secret",
      serviceInstanceId: "service-1",
    });
    expect(readBootstrapFragment("#bootstrap_secret=secret")).toBeNull();
  });

  test("exchanges the exact bootstrap request and clears the fragment", async () => {
    const clearFragment = vi.fn();
    vi.mocked(bootstrapSession).mockResolvedValue(response);

    await expect(bootstrapLocalSession({ bootstrapSecret: "secret", serviceInstanceId: "service-1" }, clearFragment)).resolves.toEqual(response);

    expect(bootstrapSession).toHaveBeenCalledWith({ bootstrap_secret: "secret" });
    expect(clearFragment).toHaveBeenCalledOnce();
  });

  test("fails closed on service-instance mismatch and still clears the fragment", async () => {
    const clearFragment = vi.fn();
    vi.mocked(bootstrapSession).mockResolvedValue({ ...response, service_instance_id: "other" });

    await expect(bootstrapLocalSession({ bootstrapSecret: "secret", serviceInstanceId: "service-1" }, clearFragment)).rejects.toThrow("service instance");
    expect(clearFragment).toHaveBeenCalledOnce();
  });
});
