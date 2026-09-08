import { useState } from "react";

interface WebhookSimulatorProps {
  apiBaseUrl: string;
  onIngested?: () => void;
}

const DEFAULT_PAYLOAD = JSON.stringify(
  { title: "Beispiel-Incident aus Webhook-Simulator", severity: "high" },
  null,
  2,
);

/**
 * Entspricht dem Dev-Default-Secret aus src/api/webhooks.py (WEBHOOK_SECRET). Nur für lokale
 * Entwicklung/Demo gedacht - in Produktion kommt das echte Secret aus einer Umgebungsvariable
 * und wird niemals im Frontend-Code hinterlegt.
 */
const DEV_DEFAULT_SECRET = "super-secret-key";

async function computeHmacSignature(secret: string, payload: string): Promise<string> {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signatureBuffer = await crypto.subtle.sign("HMAC", key, encoder.encode(payload));
  return Array.from(new Uint8Array(signatureBuffer))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";

interface WebhookSimulatorProps {
  apiBaseUrl: string;
  onIngested?: () => void;
}

const DEFAULT_PAYLOAD = JSON.stringify(
  { title: "Beispiel-Incident aus Webhook-Simulator", severity: "high" },
  null,
  2,
);

const DEV_DEFAULT_SECRET = "super-secret-key";

async function computeHmacSignature(secret: string, payload: string): Promise<string> {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signatureBuffer = await crypto.subtle.sign("HMAC", key, encoder.encode(payload));
  return Array.from(new Uint8Array(signatureBuffer))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function WebhookSimulator({ apiBaseUrl, onIngested }: WebhookSimulatorProps) {
  const [payloadText, setPayloadText] = useState(DEFAULT_PAYLOAD);
  const [secret, setSecret] = useState(DEV_DEFAULT_SECRET);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      navigate("/login");
    }
  }, [navigate]);

  const handleSend = async () => {
    setIsSending(true);
    setStatusMessage(null);
    try {
      JSON.parse(payloadText);
      const signature = await computeHmacSignature(secret, payloadText);
      const response = await fetch(`${apiBaseUrl}/webhooks/ingest`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-OpsPilot-Signature": signature,
          "Authorization": `Bearer ${localStorage.getItem("access_token")}`
        },
        body: payloadText,
      });
      if (response.status === 401) {
        localStorage.removeItem("access_token");
        navigate("/login");
        return;
      }
      if (!response.ok) {
        throw new Error(`Backend antwortete mit Status ${response.status}`);
      }
      setStatusMessage("✅ Webhook erfolgreich zugestellt.");
      onIngested?.();
    } catch (error) {
      setStatusMessage(
        `❌ Fehler: ${error instanceof Error ? error.message : "Unbekannter Fehler."}`,
      );
    } finally {
      setIsSending(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", maxWidth: 480 }}>
      <label htmlFor="webhook-secret">
        Signatur-Secret
        <input
          id="webhook-secret"
          type="text"
          value={secret}
          onChange={(event) => setSecret(event.target.value)}
          style={{ display: "block", width: "100%", marginTop: "0.25rem" }}
        />
      </label>
      <label htmlFor="webhook-payload">
        JSON-Payload
        <textarea
          id="webhook-payload"
          value={payloadText}
          onChange={(event) => setPayloadText(event.target.value)}
          rows={6}
          style={{ display: "block", width: "100%", marginTop: "0.25rem", fontFamily: "monospace" }}
        />
      </label>
      <button type="button" onClick={() => void handleSend()} disabled={isSending}>
        {isSending ? "Sende…" : "Webhook senden"}
      </button>
      {statusMessage && <p>{statusMessage}</p>}
    </div>
  );
}

export default WebhookSimulator;
