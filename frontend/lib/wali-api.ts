export type Role = "owner" | "bookkeeper" | "staff";

export type WaliInfo = {
  simulation: string;
  roles: Role[];
  screening_model: boolean;
};

export type RiskWarning = { message: string };

export type PaymentSummary = {
  supplier_name: string;
  invoice_number: string;
  due_date: string;
  amount: string | number;
  currency: string;
  registered_account: string;
  balance_after: string | number;
};

export type PendingRequest = {
  kind: string;
  subject_id: string;
  required_role: Role;
  requested_by: string;
  expires_at: string;
  summary: PaymentSummary | null;
  changes: string[];
  risk_warnings: RiskWarning[];
};

export type ChatResult = {
  reply: string;
  blocked: boolean;
  new_requests: PendingRequest[];
};

export type DecisionResult = { status: string; message: string };

export async function waliGet<T>(
  action: "info" | "pending",
  role?: Role,
): Promise<T> {
  const params = role ? `?role=${encodeURIComponent(role)}` : "";
  return waliRequest<T>(`/api/wali/${action}${params}`);
}

export async function waliPost<T>(
  action: "chat" | "confirm" | "cancel" | "mandate" | "reset",
  body: Record<string, string>,
): Promise<T> {
  return waliRequest<T>(`/api/wali/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function waliRequest<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { ...init, cache: "no-store" });
  } catch {
    throw new Error(
      "The local Wali service is unavailable. Check both servers and retry.",
    );
  }
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new Error("Wali returned an unreadable response. Please retry.");
  }
  if (!response.ok) {
    const detail =
      isRecord(data) && typeof data.detail === "string" ? data.detail : null;
    throw new Error(detail ?? `Wali request failed (${response.status}).`);
  }
  return data as T;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
