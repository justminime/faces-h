export interface ApiPerson {
  id: number;
  name: string | null;
  photo_count: number;
  medallion_face_id: number | null;
}

export interface ApiFace {
  face_id: number;
  person_id: number | null;
  assign_conf: number | null;
}

export interface ApiPhoto {
  id: number;
  path: string;
  taken_at: number | null;
  faces: ApiFace[];
}

export interface SearchRequest {
  people_ids: number[];
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}

export interface QueueItem {
  face_id: number;
  photo_id: number;
  face_crop_url: string;
  suggested_person_id: number | null;
  suggested_person_name: string | null;
  assign_conf: number | null;
}
