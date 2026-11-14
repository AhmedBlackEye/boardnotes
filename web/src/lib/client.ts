import { API_MODE, httpApi, type BoardNotesApi } from "@/lib/api";
import { mockApi } from "@/mocks/api";

/** The API the pages use: in memory in mock mode, HTTP otherwise. */
export const api: BoardNotesApi = API_MODE === "mock" ? mockApi : httpApi;
