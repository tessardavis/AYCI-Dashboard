import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { apiClient, formatApiErrorDetail } from "@/lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null); // null = checking
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const { data } = await apiClient.get("/auth/me");
      setUser(data);
    } catch {
      setUser(false);
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const login = async (email, password) => {
    try {
      const { data } = await apiClient.post("/auth/login", { email, password });
      setUser(data);
      return { ok: true };
    } catch (e) {
      return { ok: false, error: formatApiErrorDetail(e.response?.data?.detail) || e.message };
    }
  };

  const logout = async () => {
    try {
      await apiClient.post("/auth/logout");
    } catch {
      /* ignore */
    }
    setUser(false);
  };

  return (
    <AuthContext.Provider value={{ user, ready, login, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
