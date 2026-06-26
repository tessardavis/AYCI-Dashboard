import axios from "axios";

// In production, always use relative /api URLs - Vercel's rewrite proxies
// them to Render. This sidesteps mobile Safari's third-party cookie blocking.
// In local dev (localhost:3000) we still honour REACT_APP_BACKEND_URL.
const isLocal =
  typeof window !== "undefined" &&
  (window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1");
const BACKEND_URL = isLocal ? process.env.REACT_APP_BACKEND_URL || "" : "";
export const API = `${BACKEND_URL}/api`;

export const apiClient = axios.create({
  baseURL: API,
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

export function formatApiErrorDetail(detail) {
  if (detail == null) return "Something went wrong. Please try again.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e)))
      .filter(Boolean)
      .join(" ");
  if (detail && typeof detail.msg === "string") return detail.msg;
  return String(detail);
}
