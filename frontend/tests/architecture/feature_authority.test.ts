import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const FRONTEND_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const REPOSITORY_ROOT = join(FRONTEND_ROOT, "..");
const SOURCE_ROOT = join(FRONTEND_ROOT, "src");
const FEATURE_ROOT = join(SOURCE_ROOT, "features");
const DIRECTORY_OWNERSHIP_SOURCE = join(
  REPOSITORY_ROOT,
  "docs",
  "canonical",
  "16-repository-architecture",
  "02-directory-ownership.md",
);

const FEATURE_OWNERS = [
  "approval",
  "attachment",
  "conversation",
  "diagnostics",
  "recovery",
  "resource_browser",
  "run",
  "settings",
];

function sourceFiles(root: string): string[] {
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const path = join(root, entry.name);
    return entry.isDirectory() ? sourceFiles(path) : [path];
  }).filter((path) => [".ts", ".tsx"].includes(extname(path)) && !path.endsWith(".test.ts") && !path.endsWith(".test.tsx"));
}

function canonicalResponsibilityManifest(): readonly (readonly [string, string, string])[] {
  const markdown = readFileSync(DIRECTORY_OWNERSHIP_SOURCE, "utf8");
  const section = markdown
    .split("### Frontend exact responsibility manifest", 2)[1]
    ?.split("Frontend naming is deterministic", 1)[0];
  expect(section, "canonical Frontend responsibility manifest").toBeDefined();
  return section!.split("\n")
    .filter((line) => line.startsWith("|") && !line.includes("---") && !line.includes("UI / Functional surface"))
    .map((line) => {
      const cells = line.slice(1, -1).split("|").map((cell) => cell.trim());
      return [
        cells[2].replaceAll("`", "").replace(/^frontend\//, ""),
        cells[3].replaceAll("`", "").replace(/\(\)$/, ""),
        cells[4].replaceAll("`", "").replace(/^frontend\//, ""),
      ] as const;
    });
}

describe("frontend canonical authority", () => {
  test("top-level feature owners equal the canonical closed set", () => {
    const actual = readdirSync(FEATURE_ROOT, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && sourceFiles(join(FEATURE_ROOT, entry.name)).length > 0)
      .map((entry) => entry.name)
      .sort();

    expect(actual).toEqual(FEATURE_OWNERS);
    expect(actual).not.toEqual(expect.arrayContaining(["gmail", "tasks", "calendar"]));
  });

  test("the canonical P0 responsibility manifest fixes exact paths, symbols, and test owners", () => {
    const responsibilityManifest = canonicalResponsibilityManifest();
    expect(responsibilityManifest.length).toBeGreaterThan(0);
    const modules = sourceFiles(SOURCE_ROOT).map((path) => relative(SOURCE_ROOT, path).replace(/\\/g, "/").replace(/\.[^.]+$/, ""));
    for (const [productionPath, primarySymbol, testOwnerPath] of responsibilityManifest) {
      const production = join(FRONTEND_ROOT, productionPath);
      const testOwner = join(FRONTEND_ROOT, testOwnerPath);
      expect(existsSync(production), productionPath).toBe(true);
      expect(existsSync(testOwner), testOwnerPath).toBe(true);

      const productionSource = readFileSync(production, "utf8");
      const escapedSymbol = primarySymbol.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      expect(productionSource, `${productionPath}::${primarySymbol}`).toMatch(
        new RegExp(`\\bexport\\s+(?:default\\s+)?(?:async\\s+)?(?:function|class|const|let|var)\\s+${escapedSymbol}\\b`),
      );
      expect(readFileSync(testOwner, "utf8"), testOwnerPath).toContain("expect(");

      const responsibility = productionPath.split("/").at(-1)?.replace(/\.[^.]+$/, "");
      const owners = modules.filter((module) => module.split("/").at(-1) === responsibility);
      expect(owners, responsibility).toHaveLength(1);
    }
  });

  test("browser transport remains local and has no provider SDK or secret persistence authority", () => {
    const sources = sourceFiles(SOURCE_ROOT).map((path) => readFileSync(path, "utf8")).join("\n");

    expect(sources).not.toMatch(/from\s+["'](?:@google|googleapis|@modelcontextprotocol)\//);
    expect(sources).not.toMatch(/fetch\(\s*["']https?:\/\//);
    expect(sources).not.toMatch(/(?:localStorage|sessionStorage)\.setItem\([^\n]*(?:token|secret|api[_-]?key)/i);
    expect(sources).not.toMatch(/(?:ResourceRef|selection_handle)[^\n]*(?:localStorage|indexedDB)/);
    expect(sources).not.toMatch(/gwa\.(?:theme|shell-preferences)/);
  });
});
