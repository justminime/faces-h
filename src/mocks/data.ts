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
}

export interface Photo {
  id: number;
  src: string;
  path: string;
  takenAt: string;
  faces: FaceInfo[];
}

export const MOCK_PEOPLE: Person[] = [
  { id: 1, name: "Alice", avatarSrc: "/mock/alice.jpg", photoCount: 23 },
  { id: 2, name: "Bob", avatarSrc: "/mock/bob.jpg", photoCount: 11 },
];

export const MOCK_UNNAMED_COUNT = 7;

export const MOCK_PHOTOS: Photo[] = [
  {
    id: 1,
    src: "/mock/photo1.jpg",
    path: "/photos/2023/IMG_001.jpg",
    takenAt: "2023-08-15",
    faces: [
      { faceId: 1, personId: 1, personName: "Alice", faceSrc: "/mock/alice_face1.jpg" },
    ],
  },
  {
    id: 2,
    src: "/mock/photo2.jpg",
    path: "/photos/2023/IMG_002.jpg",
    takenAt: "2023-09-01",
    faces: [
      { faceId: 2, personId: 2, personName: "Bob", faceSrc: "/mock/bob_face1.jpg" },
      { faceId: 3, personId: null, personName: null, faceSrc: "/mock/unknown_face1.jpg" },
    ],
  },
  {
    id: 3,
    src: "/mock/photo3.jpg",
    path: "/photos/2024/IMG_003.jpg",
    takenAt: "2024-01-20",
    faces: [],
  },
];
