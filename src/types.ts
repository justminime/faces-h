/** UI-facing domain types, mapped from API responses in App.tsx.
 *  Kept out of src/mocks/ so production code never imports mock fixtures (#109). */

export interface Person {
  id: number;
  name: string | null;
  avatarSrc: string;
  photoCount: number;
}

export interface FaceInfo {
  faceId: number;
  personId: number | null;
  personName: string | null;
  faceSrc: string;
  assignStatus?: "assigned" | "uncertain" | "unreviewed" | "dismissed";
}

export interface Photo {
  id: number;
  src: string;
  path: string;
  takenAt: string;
  faces: FaceInfo[];
}
