import { API_CONTRACT_VERSION, type ErrorEnvelope } from "./contract";

export class ApiClientError extends Error {
  status: number;
  envelope: ErrorEnvelope | null;

  constructor(status: number, message: string, envelope: ErrorEnvelope | null) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.envelope = envelope;
  }
}

type RequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
};

export async function requestJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  if (!path.startsWith("/")) {
    throw new Error("same-origin relative path is required");
  }
  const isFormData = options.body instanceof FormData;
  const requestBody: BodyInit | undefined =
    options.body === undefined
      ? undefined
      : options.body instanceof FormData
        ? options.body
        : JSON.stringify(options.body);
  const response = await fetch(path, {
    method: options.method ?? "GET",
    credentials: "same-origin",
    headers: {
      "X-Api-Contract-Version": API_CONTRACT_VERSION,
      ...(options.body === undefined || isFormData
        ? {}
        : { "Content-Type": "application/json" }),
    },
    body: requestBody,
  });
  const text = await response.text();
  const contentType = response.headers.get("content-type") ?? "";
  const json = contentType.includes("application/json") && text ? tryParseJson(text) : null;
  if (!response.ok) {
    const envelope = isErrorEnvelope(json) ? json : null;
    throw new ApiClientError(
      response.status,
      envelope?.user_message ?? "API 요청을 처리하지 못했습니다.",
      envelope,
    );
  }
  if (json === null) {
    throw new ApiClientError(response.status, "예상하지 못한 응답 형식입니다.", null);
  }
  return json as T;
}

export async function requestBlob(path: string): Promise<Blob> {
  if (!path.startsWith("/")) {
    throw new Error("same-origin relative path is required");
  }
  const response = await fetch(path, {
    method: "GET",
    credentials: "same-origin",
    headers: { "X-Api-Contract-Version": API_CONTRACT_VERSION },
  });
  if (!response.ok) {
    const contentType = response.headers.get("content-type") ?? "";
    const json = contentType.includes("application/json")
      ? tryParseJson(await response.text())
      : null;
    const envelope = isErrorEnvelope(json) ? json : null;
    throw new ApiClientError(
      response.status,
      envelope?.user_message ?? "Attachment download failed.",
      envelope,
    );
  }
  return response.blob();
}

function tryParseJson(text: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (!value || typeof value !== "object") {
    return false;
  }
  const candidate = value as Partial<ErrorEnvelope>;
  return typeof candidate.error_code === "string" && typeof candidate.user_message === "string";
}
