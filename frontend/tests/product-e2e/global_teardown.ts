export default async function globalTeardown(): Promise<void> {
  try {
    await fetch("http://127.0.0.1:18766/shutdown", { method: "POST" });
  } catch {
    // The supervisor may already be gone after a deliberate process-failure test.
  }
}
