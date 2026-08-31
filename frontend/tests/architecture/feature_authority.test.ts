import { readFileSync, readdirSync } from "node:fs";
import { dirname, extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const FRONTEND_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const SOURCE_ROOT = join(FRONTEND_ROOT, "src");
const FEATURE_ROOT = join(SOURCE_ROOT, "features");

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

const RESPONSIBILITY_MODULES = [
  "startup_flow",
  "startup_check",
  "first_run_onboarding",
  "session_bootstrap",
  "api_compatibility_gate",
  "main_shell",
  "top_bar",
  "resource_sidebar",
  "resource_viewer",
  "list_resources",
  "session_page_cache",
  "selected_resource_context",
  "request_composer",
  "subscribe_run_events",
  "run_progress",
  "confirmation_card",
  "execution_status_card",
  "conversation_history_panel",
  "get_conversation_history",
  "action_plan_card",
  "recovery_card",
  "settings_drawer",
  "diagnostics_panel",
  "attachment_list",
  "download_attachment",
  "attachment_picker",
  "stage_attachment",
];

function sourceFiles(root: string): string[] {
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const path = join(root, entry.name);
    return entry.isDirectory() ? sourceFiles(path) : [path];
  }).filter((path) => [".ts", ".tsx"].includes(extname(path)) && !path.endsWith(".test.ts") && !path.endsWith(".test.tsx"));
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

  test("the canonical P0 responsibility manifest is present exactly once", () => {
    const modules = sourceFiles(SOURCE_ROOT).map((path) => relative(SOURCE_ROOT, path).replace(/\\/g, "/").replace(/\.[^.]+$/, ""));
    for (const responsibility of RESPONSIBILITY_MODULES) {
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
  });
});
