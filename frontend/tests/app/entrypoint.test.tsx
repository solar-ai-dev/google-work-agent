import { beforeEach, describe, expect, test, vi } from "vitest";

const renderMock = vi.fn();
const createRootMock = vi.fn(() => ({ render: renderMock }));

vi.mock("react-dom/client", () => ({
  default: {
    createRoot: createRootMock,
  },
}));

vi.mock("../../src/app/App", () => ({
  App: () => <div>Mock App</div>,
}));

describe("main entrypoint", () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="root"></div>';
    createRootMock.mockClear();
    renderMock.mockClear();
    vi.resetModules();
  });

  test("mounts the app into the root element", async () => {
    await import("../../src/main");

    expect(createRootMock).toHaveBeenCalledWith(document.getElementById("root"));
    expect(renderMock).toHaveBeenCalledTimes(1);
  });
});
