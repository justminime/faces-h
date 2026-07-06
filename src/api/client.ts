import type { ApiPerson, ApiPhoto, QueueItem, SearchRequest } from "./types";
export type { ApiPerson, ApiPhoto, QueueItem, SearchRequest };

let _baseUrl = "";
let _token = "";

export function initClient(url: string, token = ""): void {
  _baseUrl = url;
  _token = token;
}

/** Absolute URL of a downscaled JPEG thumbnail for a photo. */
export function photoThumbUrl(photoId: number, size = 256): string {
  const t = _token ? `&token=${encodeURIComponent(_token)}` : "";
  return `${_baseUrl}/photos/${photoId}/thumbnail?size=${size}${t}`;
}

/** Absolute URL of a face bounding-box crop, used for medallions and avatars. */
export function faceCropUrl(faceId: number): string {
  const t = _token ? `?token=${encodeURIComponent(_token)}` : "";
  return `${_baseUrl}/faces/${faceId}/crop${t}`;
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${_baseUrl}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(_token ? { "X-Faces-Token": _token } : {}),
      ...(options?.headers as Record<string, string> | undefined),
    },
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
  order: "date" | "random" = "date",
  seed = 0,
): Promise<ApiPhoto[]> {
  // seed (#145): keeps the shuffled order stable across pages of one visit,
  // so "load more" never repeats photos and eventually covers all of them.
  const seedParam = order === "random" ? `&seed=${seed}` : "";
  return apiFetch<ApiPhoto[]>(
    `/people/${personId}/photos?offset=${offset}&limit=${limit}&order=${order}${seedParam}`,
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

export function fetchModelsStatus(): Promise<{
  ready: boolean;
  downloading: boolean;
  progress: number;
}> {
  return apiFetch<{ ready: boolean; downloading: boolean; progress: number }>(
    "/models/status",
  );
}

export function preloadModels(): Promise<{ status: string }> {
  return apiFetch<{ status: string }>("/models/preload", { method: "POST" });
}

export function startScan(rootPath: string): Promise<{ status: string }> {
  return apiFetch<{ status: string }>("/scan/start", {
    method: "POST",
    body: JSON.stringify({ root_path: rootPath }),
  });
}

export function rescan(): Promise<{ status: string }> {
  return apiFetch<{ status: string }>("/scan/rescan", { method: "POST" });
}

export function correctFace(
  photoId: number,
  faceId: number,
  newPersonId: number | null,
): Promise<{ status: string; face_id: number }> {
  return apiFetch<{ status: string; face_id: number }>(
    `/photos/${photoId}/faces/${faceId}/correct`,
    {
      method: "POST",
      body: JSON.stringify({ new_person_id: newPersonId }),
    },
  );
}

export function fetchQueueCount(): Promise<{ count: number }> {
  return apiFetch<{ count: number }>("/queue/count");
}

export interface LibraryBundle {
  version: number;
  exported_at: number;
  people: { name: string; centroid_b64: string }[];
}

export interface ImportSummary {
  applied: number;
  unmatched: string[];
  conflicts: string[];
  total: number;
}

/** Download the portable bundle of named people + centroids (no photos). */
export function exportLibrary(): Promise<LibraryBundle> {
  return apiFetch<LibraryBundle>("/export");
}

/** Apply an exported bundle's names to matching clusters in this library. */
export function importLibrary(bundle: unknown): Promise<ImportSummary> {
  return apiFetch<ImportSummary>("/import", {
    method: "POST",
    body: JSON.stringify(bundle),
  });
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

/** Persistently mark a queued face as "not relevant" (#168) — unlike the
 *  client-only Skip, this survives reload; the face moves to the secondary
 *  Not Relevant view and can be restored from there. */
export function dismissFace(
  faceId: number,
): Promise<{ face_id: number; assign_status: string }> {
  return apiFetch<{ face_id: number; assign_status: string }>(
    `/queue/${faceId}/dismiss`,
    { method: "POST" },
  );
}

export interface DismissedItem {
  face_id: number;
  photo_id: number;
  face_crop_url: string;
}

/** Faces dismissed as "not relevant" — the secondary review window (#168). */
export function fetchDismissedQueue(
  offset = 0,
  limit = 50,
): Promise<DismissedItem[]> {
  return apiFetch<DismissedItem[]>(
    `/queue/dismissed?offset=${offset}&limit=${limit}`,
  );
}

/** Bring a dismissed face back into normal review/evaluation (#168). */
export function restoreDismissedFace(
  faceId: number,
): Promise<{ face_id: number; assign_status: string }> {
  return apiFetch<{ face_id: number; assign_status: string }>(
    `/queue/${faceId}/restore`,
    { method: "POST" },
  );
}

export interface BlurryPhoto {
  id: number;
  path: string;
  taken_at: number | null;
  blur_score: number;
  file_size: number | null;
  is_network: boolean;
}

/** Photos below the sharpness cutoff, most blurred first (#154).
 *  threshold: slider-driven cutoff; omit to use the configured default. */
export function fetchBlurryPhotos(
  offset = 0,
  limit = 100,
  threshold?: number,
): Promise<BlurryPhoto[]> {
  const t = threshold !== undefined ? `&threshold=${threshold}` : "";
  return apiFetch<BlurryPhoto[]>(`/photos/blurry?offset=${offset}&limit=${limit}${t}`);
}

export interface TrashResult {
  trashed: number;
  deleted_permanently: number;
  failed: { id: number; error: string }[];
}

/** Delete photos — local and network folders behave identically (#164):
 *  every file is backed up in the app first, then Recycle Bin is attempted,
 *  falling back to a (safe, already-backed-up) permanent removal. */
export function trashPhotos(photoIds: number[]): Promise<TrashResult> {
  return apiFetch<TrashResult>("/photos/trash", {
    method: "POST",
    body: JSON.stringify({ photo_ids: photoIds, confirmed: true }),
  });
}

export interface DuplicatePhoto {
  id: number;
  path: string;
  folder: string;
  filename: string;
  file_size: number | null;
  taken_at: number | null;
  is_network: boolean;
}

export interface DuplicateGroup {
  kind: "exact" | "similar";
  photos: DuplicatePhoto[];
}

/** Duplicate groups — exact (byte-identical) and similar (same shot,
 *  different size/format), biggest space-savers first (#155). */
export function fetchDuplicates(): Promise<DuplicateGroup[]> {
  return apiFetch<DuplicateGroup[]>("/photos/duplicates");
}

export interface RotationSuggestion {
  id: number;
  path: string;
  folder: string;
  filename: string;
  file_size: number | null;
  degrees: number;
  source: "faces" | "exif";
  is_network: boolean;
  rotatable: boolean;
}

/** Photos that look sideways — EXIF-tagged or face-probed (#160). */
export function fetchRotationSuggestions(): Promise<RotationSuggestion[]> {
  return apiFetch<RotationSuggestion[]>("/photos/rotation-suggestions");
}

/** Kick off a background probe of faceless photos at 90/180/270°. */
export function startRotationScan(): Promise<{ status: string }> {
  return apiFetch<{ status: string }>("/photos/rotation-scan", { method: "POST" });
}

export interface RotateResult {
  rotated: number;
  recycled: number;
  permanent: number;
  failed: { id: number; error: string }[];
}

/** Rotate original files in place — undoable everywhere alike (#160/#164):
 *  every original is backed up in the app first, then Recycle Bin is
 *  attempted, falling back to a (safe, already-backed-up) permanent removal. */
export function rotatePhotos(
  items: { photo_id: number; degrees: number }[],
): Promise<RotateResult> {
  return apiFetch<RotateResult>("/photos/rotate", {
    method: "POST",
    body: JSON.stringify({ items, confirmed: true }),
  });
}

export interface BackupEntry {
  backup: string;
  original_path: string;
  filename: string;
  folder: string;
  file_size: number;
  backed_up_at: number;
  expires_in_days: number;
}

/** Pre-deletion backups still within their retention window (#161/#162). */
export function fetchBackups(): Promise<BackupEntry[]> {
  return apiFetch<BackupEntry[]>("/backups");
}

/** Restore a backup to its original location (overwrites what's there now). */
export function restoreBackup(backup: string): Promise<{ restored: string }> {
  return apiFetch<{ restored: string }>("/backups/restore", {
    method: "POST",
    body: JSON.stringify({ backup, confirmed: true }),
  });
}
