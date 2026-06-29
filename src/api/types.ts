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
