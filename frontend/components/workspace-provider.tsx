"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import {
  type ChatResult,
  type DecisionResult,
  type PendingRequest,
  type Role,
  type WaliInfo,
  waliGet,
  waliPost,
} from "@/lib/wali-api";
import { decisionTone } from "@/lib/decision-tone";

export type Message = {
  id: number;
  author: "you" | "wali";
  text: string;
  blocked?: boolean;
};
export type Notice = { tone: "success" | "error"; text: string };
export type QueueState = "loading" | "ready" | "error";

type WorkspaceContextValue = {
  info: WaliInfo | null;
  infoError: string;
  role: Role | "";
  draft: string;
  setDraft: (text: string) => void;
  messages: Message[];
  sending: boolean;
  resetting: boolean;
  mandating: boolean;
  processingId: string;
  busy: boolean;
  requests: PendingRequest[];
  queueState: QueueState;
  queueError: string;
  chatNotice: Notice | null;
  queueNotice: Notice | null;
  mandateNotice: Notice | null;
  composerFocusVersion: number;
  changeRole: (role: Role) => void;
  retryInfo: () => Promise<void>;
  retryPending: () => Promise<void>;
  sendMessage: () => Promise<void>;
  resetConversation: () => Promise<boolean>;
  draftMandate: () => Promise<void>;
  decide: (
    request: PendingRequest,
    action: "confirm" | "cancel",
  ) => Promise<void>;
};

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

function errorText(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Something went wrong. Please retry.";
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const nextMessageId = useRef(0);
  const pendingGeneration = useRef(0);
  const [info, setInfo] = useState<WaliInfo | null>(null);
  const [infoError, setInfoError] = useState("");
  const [role, setRole] = useState<Role | "">("");
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [sending, setSending] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [mandating, setMandating] = useState(false);
  const [processingId, setProcessingId] = useState("");
  const [requests, setRequests] = useState<PendingRequest[]>([]);
  const [queueState, setQueueState] = useState<QueueState>("loading");
  const [queueError, setQueueError] = useState("");
  const [chatNotice, setChatNotice] = useState<Notice | null>(null);
  const [queueNotice, setQueueNotice] = useState<Notice | null>(null);
  const [mandateNotice, setMandateNotice] = useState<Notice | null>(null);
  const [composerFocusVersion, setComposerFocusVersion] = useState(0);

  const loadPending = useCallback(async (currentRole: Role) => {
    const generation = ++pendingGeneration.current;
    try {
      const result = await waliGet<{ requests: PendingRequest[] }>(
        "pending",
        currentRole,
      );
      if (generation !== pendingGeneration.current) return;
      setRequests(result.requests);
      setQueueError("");
      setQueueState("ready");
    } catch (error) {
      if (generation !== pendingGeneration.current) return;
      setQueueError(errorText(error));
      setQueueState("error");
    }
  }, []);

  useEffect(() => {
    let active = true;
    void waliGet<WaliInfo>("info")
      .then((result) => {
        if (!active) return;
        setInfo(result);
        setRole(result.roles[0] ?? "");
      })
      .catch((error: unknown) => {
        if (active) setInfoError(errorText(error));
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!role) return;
    const generation = ++pendingGeneration.current;
    void waliGet<{ requests: PendingRequest[] }>("pending", role)
      .then((result) => {
        if (generation !== pendingGeneration.current) return;
        setRequests(result.requests);
        setQueueState("ready");
      })
      .catch((error: unknown) => {
        if (generation !== pendingGeneration.current) return;
        setQueueError(errorText(error));
        setQueueState("error");
      });
    return () => {
      pendingGeneration.current += 1;
    };
  }, [role]);

  async function retryInfo() {
    setInfoError("");
    try {
      const result = await waliGet<WaliInfo>("info");
      setInfo(result);
      setRole((current) =>
        current && result.roles.includes(current)
          ? current
          : (result.roles[0] ?? ""),
      );
    } catch (error) {
      setInfoError(errorText(error));
    }
  }

  async function retryPending() {
    if (!role) return;
    setQueueState("loading");
    await loadPending(role);
  }

  function changeRole(nextRole: Role) {
    if (nextRole === role) return;
    pendingGeneration.current += 1;
    setRole(nextRole);
    setQueueState("loading");
    setRequests([]);
    setMessages([]);
    setDraft("");
    setChatNotice(null);
    setQueueNotice(null);
    setMandateNotice(null);
  }

  async function sendMessage() {
    const text = draft.trim();
    if (
      !role ||
      !text ||
      sending ||
      resetting ||
      mandating ||
      processingId ||
      text.length > 4000
    )
      return;
    setSending(true);
    setChatNotice(null);
    setDraft("");
    const submittedId = ++nextMessageId.current;
    setMessages((items) => [
      ...items,
      { id: submittedId, author: "you", text },
    ]);
    try {
      const result = await waliPost<ChatResult>("chat", { role, text });
      setMessages((items) => [
        ...items,
        {
          id: ++nextMessageId.current,
          author: "wali",
          text: result.reply,
          blocked: result.blocked,
        },
      ]);
      if (result.new_requests.length > 0) {
        const count = result.new_requests.length;
        setChatNotice({
          tone: "success",
          text: `${count} new approval ${count === 1 ? "request" : "requests"} added.`,
        });
      }
      await loadPending(role);
    } catch (error) {
      setMessages((items) => items.filter((item) => item.id !== submittedId));
      setDraft(text);
      setChatNotice({
        tone: "error",
        text: `Message not completed. ${errorText(error)}`,
      });
    } finally {
      setSending(false);
      setComposerFocusVersion((value) => value + 1);
    }
  }

  async function resetConversation(): Promise<boolean> {
    if (!role || sending || resetting || mandating || processingId)
      return false;
    setResetting(true);
    setChatNotice(null);
    try {
      await waliPost<{ status: string }>("reset", { role });
      setMessages([]);
      setDraft("");
      setChatNotice({
        tone: "success",
        text: "Conversation reset for this role.",
      });
      await loadPending(role);
      setComposerFocusVersion((value) => value + 1);
      return true;
    } catch (error) {
      setChatNotice({
        tone: "error",
        text: `Could not reset conversation. ${errorText(error)}`,
      });
      return false;
    } finally {
      setResetting(false);
    }
  }

  async function draftMandate() {
    if (role !== "owner" || sending || resetting || mandating || processingId)
      return;
    setMandating(true);
    setMandateNotice(null);
    try {
      const result = await waliPost<DecisionResult>("mandate", { role });
      setMandateNotice({
        tone: decisionTone(result.status, ["needs_confirmation"]),
        text: result.message,
      });
      await loadPending(role);
    } catch (error) {
      setMandateNotice({
        tone: "error",
        text: `Mandate draft failed. ${errorText(error)}`,
      });
    } finally {
      setMandating(false);
    }
  }

  async function decide(request: PendingRequest, action: "confirm" | "cancel") {
    if (!role || sending || resetting || mandating || processingId) return;
    setProcessingId(request.subject_id);
    setQueueNotice(null);
    try {
      const result = await waliPost<DecisionResult>(action, {
        role,
        subject_id: request.subject_id,
      });
      setQueueNotice({
        tone: decisionTone(result.status, ["executed", "declined", "active"]),
        text: result.message,
      });
      await loadPending(role);
    } catch (error) {
      setQueueNotice({
        tone: "error",
        text: `${action === "confirm" ? "Confirm" : "Decline"} failed. ${errorText(error)}`,
      });
    } finally {
      setProcessingId("");
    }
  }

  const busy = sending || resetting || mandating || Boolean(processingId);

  return (
    <WorkspaceContext.Provider
      value={{
        info,
        infoError,
        role,
        draft,
        setDraft,
        messages,
        sending,
        resetting,
        mandating,
        processingId,
        busy,
        requests,
        queueState,
        queueError,
        chatNotice,
        queueNotice,
        mandateNotice,
        composerFocusVersion,
        changeRole,
        retryInfo,
        retryPending,
        sendMessage,
        resetConversation,
        draftMandate,
        decide,
      }}
    >
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace(): WorkspaceContextValue {
  const context = useContext(WorkspaceContext);
  if (!context) throw new Error("Wali workspace is missing its provider.");
  return context;
}
