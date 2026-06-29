import type { ApiPerson, ApiPhoto, QueueItem, SearchRequest } from "./types";
export type { ApiPerson, ApiPhoto, QueueItem, SearchRequest };

let _baseUrl = "";

export function initClient(url: string): void {
  _baseUrl = url;
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${_baseUrl}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json() as Promise<T>;
}

export function fetchPeople(): Promise<ApiPerson[]> {
  return apiFetch<ApiPerson[]>("/people");
}

export function fetchPersonPhotos(
  personId: number,
  offset = 0,
  limit = 50,
): Promise<ApiPhoto[]> {
  return apiFetch<ApiPhoto[]>(
    `/people/${personId}/photos?offset=${offset}&limit=${limit}`,
  );
}

export function renamePerson(
  personId: number,
  name: string,
): Promise<{ id: number; name: string }> {
  return apiFetch<{ id: number; name: string }>(`/people/${personId}/name`, {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function mergePeople(
  sourceId: number,
  targetId: number,
): Promise<{ surviving_id: number; merged_count: number }> {
  return apiFetch<{ surviving_id: number; merged_count: number }>(
    "/people/merge",
    {
      method: "POST",
      body: JSON.stringify({
        source_id: sourceId,
        target_id: targetId,
        confirmed: true,
      }),
    },
  );
}

export function searchPhotos(req: SearchRequest): Promise<ApiPhoto[]> {
  return apiFetch<ApiPhoto[]>("/search", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export function fetchQueueCount(): Promise<{ count: number }> {
  return apiFetch<{ count: number }>("/queue/count");
}

export function fetchUncertainQueue(
  offset = 0,
  limit = 50,
): Promise<QueueItem[]> {
  return apiFetch<QueueItem[]>(
    `/queue/uncertain?offset=${offset}&limit=${limit}`,
  );
}

export function confirmFace(
  faceId: number,
  personId: number,
): Promise<{ face_id: number; person_id: number; assign_status: string }> {
  return apiFetch<{ face_id: number; person_id: number; assign_status: string }>(
    `/queue/${faceId}/confirm`,
    {
      method: "POST",
      body: JSON.stringify({ person_id: personId }),
    },
  );
}
