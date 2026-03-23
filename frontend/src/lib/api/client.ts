import axios, { AxiosResponse } from "axios";
import { getApiUrl } from "@/lib/config";

// API client with runtime-configurable base URL
// The base URL is fetched from the API config endpoint on first request
// Timeout increased to 10 minutes (600000ms = 600s) to accommodate slow LLM operations
// (transformations, insights generation, chat) especially on slower hardware (Ollama, LM Studio)
// Note: Frontend uses milliseconds, backend uses seconds
// Local LLMs can take several minutes for complex questions with large contexts
export const apiClient = axios.create({
  timeout: 600000, // 600 seconds = 10 minutes
  headers: {
    "Content-Type": "application/json",
  },
  withCredentials: false,
});

// Request interceptor to add base URL and auth header
apiClient.interceptors.request.use(async (config) => {
  // Set the base URL dynamically from runtime config
  if (!config.baseURL) {
    const apiUrl = await getApiUrl();
    config.baseURL = `${apiUrl}/api`;
  }

  if (typeof window !== "undefined") {
    const authStorage = localStorage.getItem("auth-storage");
    if (authStorage) {
      try {
        const { state } = JSON.parse(authStorage);
        if (state?.token) {
          config.headers.Authorization = `Bearer ${state.token}`;
        }
      } catch (error) {
        console.error("Error parsing auth storage:", error);
      }
    }
  }

  // Handle FormData vs JSON content types
  if (config.data instanceof FormData) {
    // Remove any Content-Type header to let browser set multipart boundary
    delete config.headers["Content-Type"];
  } else if (
    config.method &&
    ["post", "put", "patch"].includes(config.method.toLowerCase())
  ) {
    config.headers["Content-Type"] = "application/json";
  }

  return config;
});

// Response interceptor for error handling and token refresh
apiClient.interceptors.response.use(
  (response: AxiosResponse) => response,
  async (error) => {
    const originalRequest = error.config;

    // Handle 401 Unauthorized - try to refresh token
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;

      try {
        // Try to refresh the token
        if (typeof window !== "undefined") {
          const authStorage = localStorage.getItem("auth-storage");
          if (authStorage) {
            const { state } = JSON.parse(authStorage);
            if (state?.token) {
              const refreshResponse = await fetch(
                `${await import("@/lib/config").then((m) => m.getApiUrl())}/api/auth/token/refresh`,
                {
                  method: "POST",
                  headers: {
                    Authorization: `Bearer ${state.token}`,
                    "Content-Type": "application/json",
                  },
                },
              );

              if (refreshResponse.ok) {
                const data = await refreshResponse.json();
                if (data.access_token) {
                  // Update token in storage
                  const updated = JSON.parse(authStorage);
                  updated.state.token = data.access_token;
                  localStorage.setItem("auth-storage", JSON.stringify(updated));

                  // Retry original request with new token
                  originalRequest.headers.Authorization = `Bearer ${data.access_token}`;
                  return apiClient(originalRequest);
                }
              }
            }
          }
        }
      } catch (refreshError) {
        console.error("Token refresh failed:", refreshError);
      }

      // If refresh failed, clear auth and redirect to login
      if (typeof window !== "undefined") {
        localStorage.removeItem("auth-storage");
        window.location.href = "/login";
      }
    }

    return Promise.reject(error);
  },
);

export default apiClient;
