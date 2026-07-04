# PRD: faces-h

**Version:** 1.2  
**Status:** Draft  
**Last updated:** 2026-07-04

---

## 1. Overview

faces-h is a local Windows desktop application that organizes a personal photo library by recognizing faces, allowing users to attach names to recognized individuals, and enabling search and filtering by person. All processing runs on-device. No data leaves the machine. No cloud account is required.

**Target user:** Non-technical individuals with large personal photo archives (hundreds of gigabytes to multiple terabytes), organized by date or year folders, containing photos of family members and friends who may closely resemble one another and who appear across many years and ages.

---

## 2. Problem

Users with large photo libraries (2TB+) cannot find photos of specific people. Photos are buried across thousands of date-organized folders. Existing solutions require cloud upload, subscriptions, or technical setup. The result is that memories become inaccessible even though they are physically present on the user's drive.

---

## 3. Goals

- A user can point the app at their photo folder and have faces detected and clustered automatically.
- A user can attach a name to a face cluster and immediately see all photos of that person.
- A user can search by one or more people and see every photo where those individuals appear together.
- A user can correct a mislabeled face, and the app will re-evaluate similar faces across the entire library using that correction as a signal.
- All of the above works without moving, copying, or modifying any photo files.
- The app is usable by a non-technical person without any setup, CLI, or configuration.

---

## 4. Non-goals (v1)

- No file system changes. The app is a search layer only — it does not move, rename, copy, or reorganize photos.
- No cloud sync, cloud storage, or cloud face recognition.
- No slideshows, highlight reels, or automatic albums.
- No video support.
- No mobile app.
- No sharing or export features.
- No support for operating systems other than Windows.

---

## 5. User stories

### 5.1 Initial setup

**US-01** — As a user, I want to select a root folder so the app knows where my photos are.

**US-02** — As a user, I want to see how many photos were found and an estimated scan time before scanning begins, so I can decide whether to proceed.

**US-03** — As a user, I want scanning to run in the background so I can continue using my computer normally while it processes.

**US-04** — As a user, I want to start seeing and naming faces before the full scan is complete, so I get value immediately rather than waiting hours.

### 5.2 Face naming

**US-05** — As a user, I want to see detected faces grouped into clusters of likely-same-person, so I can name a whole group at once rather than one photo at a time.

**US-06** — As a user, I want to type a name onto a cluster and have all photos in that cluster labeled with that name immediately.

**US-07** — As a user, I want to see a sample of photos from a cluster before naming it, so I can verify who is in it.

**US-08** — As a user, I want low-confidence matches shown separately with a prompt ("Are these also [name]?"), so I am not silently shown incorrect results.

**US-21** — As a user, if I type a name that already exists when naming a cluster, I want the two clusters to automatically merge — not create a duplicate with the same name.

**US-22** — As a user, after I name a cluster, I want the app to automatically search my library for other photos of that person that it hasn't found yet, so I don't have to manually review everything.

**US-23** — As a user, I want to see all the people who appear in a photo (not just the one I searched for) so I can understand the full context of each shot.

### 5.3 Correction and re-evaluation

**US-09** — As a user, I want to flag a photo as incorrectly labeled (e.g. "this is not Mom") directly from any view, so I can fix errors I notice naturally.

**US-10** — As a user, when I correct a face assignment, I want the app to automatically re-scan the affected person's cluster to find similar errors, and surface any additional questionable matches for my review.

**US-11** — As a user, I want to reassign a photo to the correct person and have that correction feed into the re-evaluation, so the model improves based on my input.

**US-12** — As a user, I want to see a summary after re-evaluation ("8 photos were moved from Mom to Aunt Sarah"), so I understand what changed.

### 5.4 Search and browse

**US-13** — As a user, I want to open a person's gallery and see all their photos sorted by date.

**US-14** — As a user, I want to search for photos containing multiple people at once (e.g. "Mom AND Dad"), so I can find group photos.

**US-15** — As a user, I want to filter results by date range so I can browse a specific period.

**US-16** — As a user, I want to click any photo in a result and open it in Windows Photos (or the default OS photo viewer), so I don't need to navigate my file system to find it.

### 5.5 Unknown and unresolved faces

**US-17** — As a user, I want to see a count of faces that have not yet been named, so I know how much work remains.

**US-18** — As a user, I want to hide unnamed faces from my main view without deleting their data, so I can focus on people I've labeled.

**US-19** — As a user, I want to return to unnamed face clusters at any time and name them later.

**US-24** — As a user, I want to point the app at a network share (NAS, Synology, SMB) and have it scan photos there the same way it would a local folder.

**US-25** — As a user, if my NAS goes offline while the app is open, I want to see a warning but still be able to browse photos I've already indexed.

**US-26** — As a user, I want to see a real-time activity log at the bottom of the app showing what the app is doing, with control over how much detail is shown.

---

## 6. Functional requirements

### 6.1 Scanning engine

- **FR-01** The app must scan all image files (JPG, PNG, HEIC, TIFF, RAW where feasible) in the selected root folder and all subfolders recursively.
- **FR-02** Scanning must run as a background process that does not block the UI thread or meaningfully degrade Windows system performance.
- **FR-03** The scan must be pauseable and resumeable. Progress must persist across app restarts.
- **FR-04** Detected faces must be surfaced to the UI progressively — within the first few minutes of scanning, before the full library is processed.
- **FR-05** Each detected face must be stored with: source file path, bounding box coordinates, detected timestamp, and embedding vector.
- **FR-05a** The scanner must accept UNC paths (`\\server\share`) and mapped network drive letters. It must never write, move, or delete any file on a network share.
- **FR-05b** If a network share is unreachable when a scan starts or during a rescan, the app must show a "drive offline" warning and continue serving existing indexed data from the local DB without crashing.
- **FR-05c** If a network share disconnects mid-scan, the scanner must retry up to three times (5 s apart) before stopping cleanly. The DB must remain consistent after a partial network failure.
- **FR-05d** The activity log must include a real-time entry for every major event (scan progress, scan complete, sweep, re-evaluation, drive offline, model download). The user must be able to control verbosity: Off / Errors / Scan / All / Debug. In Debug mode each filename processed during a scan is shown.

### 6.2 Face clustering

- **FR-06** Detected faces must be grouped into clusters using a similarity threshold. Each cluster represents one likely individual.
- **FR-07** The similarity threshold must be set conservatively — prefer a stricter match that requires more user confirmation over a loose match that silently merges different people.
- **FR-08** Clusters must update dynamically as new faces are found during scanning.
- **FR-09** The same person across significant age differences (e.g. childhood vs adulthood) must eventually be clustered together as the user provides naming and correction signals. The model alone may not achieve this; user corrections are the primary mechanism for bridging large age gaps.

### 6.3 Face naming

- **FR-10** A user must be able to assign a name to a cluster. Once named, all photos in that cluster are labeled with that name.
- **FR-11** A name must be editable after assignment.
- **FR-12** A named person must be mergeable with another named person (e.g. if the same person was named twice under different spellings).
- **FR-12a** If the user types an existing name when naming an unnamed cluster, the app must auto-detect the conflict and present a single "Merge" action instead of creating a duplicate. No two people records with the same name may exist after a naming operation.
- **FR-12b** After any naming or merge operation, the app must automatically sweep the library for additional photos of that person (three-pass background job: uncertain queue → unreviewed faces → unnamed clusters), add confirmed matches without user intervention (above threshold only), and notify the user with a count of newly found photos via a toast notification.
- **FR-12c** The photo detail panel must show every assigned person in a photo, not only the person the user navigated from.

### 6.4 Confidence and uncertainty

- **FR-13** Each face-to-cluster assignment must carry a confidence score.
- **FR-14** Faces below a confidence threshold must not be silently assigned. They must be surfaced to the user as "uncertain" and presented for confirmation before appearing in search results.
- **FR-15** The confidence threshold must be tunable per user (advanced setting), with a safe default that errs toward more confirmations rather than fewer.

### 6.5 Correction and re-evaluation

- **FR-16** Any photo visible in the UI must have an accessible "this person is wrong" action (e.g. right-click or a visible icon on hover).
- **FR-17** When a face is marked incorrect and reassigned to another person (or "not this person"), the app must trigger a re-evaluation job.
- **FR-18** Re-evaluation must re-score all faces in the affected cluster(s) against the updated embedding, and surface any newly uncertain assignments for user review.
- **FR-19** Re-evaluation must run in the background and must not block the user from browsing.
- **FR-20** After re-evaluation completes, the user must see a notification summarizing what changed ("5 photos moved from [Name A] to [Name B], 3 photos marked uncertain").

### 6.6 Search and browse

- **FR-21** The app must support searching by person name, returning all photos labeled with that person.
- **FR-22** The app must support multi-person AND queries — returning only photos where all specified people appear.
- **FR-23** Search results must be filterable by date range.
- **FR-24** Any photo in any result view must be openable in the system default photo viewer via double-click, without the app copying or moving the file.
- **FR-25** The app must display the file path of any photo on request, so users can locate it in Windows Explorer if needed.

### 6.7 Data storage

- **FR-26** All app data (face embeddings, cluster assignments, names, confidence scores) must be stored locally in a single database file within the user's AppData folder.
- **FR-27** The database must be portable — the user must be able to back it up and restore it.
- **FR-28** The app must never modify, move, rename, or delete any photo file.

---

## 7. Non-functional requirements

| ID | Requirement |
|----|-------------|
| NFR-01 | The app must install via a single `.exe` installer with no additional dependencies for the end user. |
| NFR-02 | Scanning throughput must sustain at least 500 photos per minute on a mid-range consumer laptop (Intel i5 / AMD Ryzen 5, no dedicated GPU required for inference). |
| NFR-03 | The UI must remain responsive (< 100ms interaction latency) while background scanning or re-evaluation is in progress. |
| NFR-04 | The app must start and be usable within 5 seconds of launch (excluding active scan time). |
| NFR-05 | All face data and embeddings must remain on-device. No network requests to external services. |
| NFR-06 | The app must handle corrupt or unreadable image files gracefully — log the error and continue, never crash. |
| NFR-07 | The app must tolerate a library of at least 100,000 photos without degradation in search or browse performance. |
| NFR-08 | The database must support incremental updates — adding new photos to a folder must not require a full re-scan. |
| NFR-09 | The Windows installer must be code-signed with a trusted certificate. Certificate provided by SignPath Foundation (free OSS programme). |
| NFR-10 | The IPC channel between the Tauri shell and the Python sidecar must be authenticated. A per-session token is generated at startup and required on every HTTP request and WebSocket connection. |
| NFR-11 | The app must set a strict Content Security Policy that blocks all external script, font, and image sources. |

---

## 8. Face recognition accuracy requirements

Given that families share genetic similarity and the library spans decades, face recognition accuracy is a first-class requirement — not a best-effort feature.

- **High confidence bar:** The model must only auto-assign faces with high certainty. All borderline matches must be surfaced for user confirmation.
- **Aging support:** The system must handle the same person across significant age changes. This is achieved through a combination of: (a) model selection that is robust to aging, and (b) the correction loop — when a user corrects a cluster, the system re-evaluates and can bridge age-separated clusters over time.
- **Sibling disambiguation:** Family members who closely resemble one another must not be silently merged. When a face is ambiguous between two known people, it must be surfaced for confirmation rather than assigned automatically.
- **Correction-driven improvement:** Every user correction must make the model more accurate for that person. The correction is not just a one-time fix — it triggers re-evaluation of related faces.

---

## 9. User interface requirements

- The app must be usable by a non-technical user with no instructions beyond the onboarding flow.
- Every destructive or irreversible action (e.g. merging two people) must require explicit confirmation.
- Scan progress must be visible at all times while a scan is running (progress bar, photos processed, estimated time remaining).
- Re-evaluation jobs must be visually distinct from initial scans so users understand what is happening.
- The "unnamed faces" queue must always be accessible and show a count badge so users know work remains.

---

## 10. Out of scope — future versions

The following are explicitly deferred and must not influence v1 architecture decisions unless they happen to be zero-cost:

- Slideshows and automatic memory reels
- Export to person-named folders
- Location tagging or map views
- Facial expression or emotion tagging
- Non-Windows platforms
- Cloud backup of the database
- Sharing photos with other people via the app

---

## 11. Open questions

| # | Question | Owner | Target date |
|---|----------|-------|-------------|
| OQ-01 | Which face recognition model best handles aging + family resemblance at acceptable CPU-only inference speed? (Candidates: InsightFace buffalo_l, DeepFace with Facenet512) | Engineering | Before technical spike |
| OQ-02 | What confidence threshold (cosine similarity score) is appropriate as the default strict cutoff? Needs empirical testing on a family photo dataset. | Engineering | After model selection |
| OQ-03 | What is the UX for merging two clusters that represent the same person (e.g. same person named twice)? Drag-and-drop, explicit merge button? | Design | Before UI spec |
| OQ-04 | How should the app handle photos with more than one face? Both faces are detected and each is independently clustered — confirm this is the intended behavior. | Product | Before development |
| OQ-05 | Should the user be able to delete a named person and remove all their labels without affecting photos? | Product | Before development |
