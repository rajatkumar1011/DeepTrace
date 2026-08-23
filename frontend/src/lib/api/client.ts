import axios from "axios";
import { API_BASE_URL } from "@/config/constants";

export const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 45000,
  headers: {
    Accept: "application/json",
  },
});

export function getApiError(error: unknown, fallback = "Something went wrong. Please try again.") {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (typeof error.response?.data === "string" && error.response.data.trim()) return error.response.data;
    if (error.code === "ECONNABORTED") return "The server took too long to respond. Please try again.";
    if (!error.response) return "DeepTrace could not reach the analysis server. Check that the FastAPI backend is running.";
    return error.message || fallback;
  }
  if (error instanceof Error) return error.message;
  return fallback;
}
