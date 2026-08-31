import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { ApiCompatibilityGate } from "../../src/app/api_compatibility_gate";

test("admits protected UI only for the exact compatible contract", () => {
  const { rerender } = render(
    <ApiCompatibilityGate compatibility="PENDING" serverApiContractVersion="1" fallback={<p>blocked</p>}>
      <p>protected</p>
    </ApiCompatibilityGate>,
  );
  expect(screen.getByText("blocked")).toBeInTheDocument();
  expect(screen.queryByText("protected")).not.toBeInTheDocument();

  rerender(
    <ApiCompatibilityGate compatibility="COMPATIBLE" serverApiContractVersion="1" fallback={<p>blocked</p>}>
      <p>protected</p>
    </ApiCompatibilityGate>,
  );
  expect(screen.getByText("protected")).toBeInTheDocument();
});
