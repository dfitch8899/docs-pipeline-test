# Attachment System Documentation: Architecture, Flow, and Security Measures

## Overview

The attachment system handles file uploads, storage, and retrieval for documents within the pipeline. It supports uploading files from the client, storing them via a server-side API, and rendering previews and download links in the UI. Key components span the frontend (React components), API routes (Next.js), and a database model for tracking attachment metadata.

---

## Architecture

### Key Files

| File | Purpose |
|---|---|
| `components/AttachmentUploader.tsx` | Main upload UI; handles file selection and submission |
| `components/AttachmentPreview.tsx` | Renders thumbnail, progress bar, and remove button per attachment |
| `components/AttachmentList.tsx` | Lists all attachments for a given document |
| `pages/api/attachments/upload.ts` | API route: receives file, validates, writes to storage |
| `pages/api/attachments/[id].ts` | API route: fetch or delete a single attachment by ID |
| `lib/storage.ts` | Abstraction over file storage (local or S3) |
| `lib/db/models/Attachment.ts` | Prisma model definition for attachment metadata |
| `lib/auth.ts` | Session/token validation helpers used by API routes |

### System Diagram

```
Client (Browser)
  └── AttachmentUploader
        │  multipart/form-data POST
        ▼
  /api/attachments/upload
        │  validate + write
        ▼
  lib/storage.ts  ──►  S3 / Local Disk
        │  save metadata
        ▼
  Prisma (Attachment model)
```

---

## Flow

### Upload Flow

1. **User selects a file** via `AttachmentUploader`. The component validates file size and MIME type client-side before sending.

   ```tsx
   const allowed = ["image/png", "image/jpeg", "application/pdf"];
   if (!allowed.includes(file.type)) {
     setError("Unsupported file type.");
     return;
   }
   ```

2. **Client POSTs** a `multipart/form-data` request to `/api/attachments/upload`, including the file and the parent `documentId`.

3. **API route authenticates** the request by calling `getSession()` from `lib/auth.ts`. Unauthenticated requests are rejected with `401`.

4. **API route validates** file size (max 10 MB) and MIME type server-side, independent of client-side checks.

   ```ts
   if (file.size > 10 * 1024 * 1024) {
     return res.status(413).json({ error: "File too large." });
   }
   ```

5. **`lib/storage.ts` writes** the file to the configured storage backend (S3 bucket or local `./uploads` directory) and returns a stable URL or path.

6. **Attachment metadata is saved** to the database via Prisma, linking the file to the document and recording the uploader's user ID.

7. **API returns** the new attachment record as JSON. `AttachmentUploader` updates state, triggering `AttachmentList` to re-render.

---

### Download / View Flow

1. **User clicks** a file link or thumbnail in `AttachmentPreview`.
2. **Client GETs** `/api/attachments/[id]`.
3. **API route authenticates** the session and verifies the user has read access to the parent document.
4. **API returns** a signed URL (S3) or streams the file directly (local), with appropriate `Content-Type` and `Content-Disposition` headers.

---

### Delete Flow

1. **User clicks the remove button** in `AttachmentPreview`.
2. **Client sends `DELETE`** to `/api/attachments/[id]`.
3. **API authenticates** and checks that the requester is the original uploader or has admin rights.
4. **Storage file is deleted** via `lib/storage.ts`, then the database record is removed.
5. **`AttachmentList` re-fetches** and removes the item from the UI.

---

## Configuration

| Variable | Description | Default |
|---|---|---|
| `STORAGE_BACKEND` | `s3` or `local` | `local` |
| `S3_BUCKET_NAME` | Target S3 bucket for uploads | — |
| `S3_REGION` | AWS region for the S3 bucket | `us-east-1` |
| `AWS_ACCESS_KEY_ID` | AWS credentials for S3 access | — |
| `AWS_SECRET_ACCESS_KEY` | AWS credentials for S3 access | — |
| `LOCAL_UPLOAD_DIR` | Directory path for local storage | `./uploads` |
| `MAX_FILE_SIZE_MB` | Maximum allowed upload size in MB | `10` |
| `NEXTAUTH_SECRET` | Secret used to sign session tokens | — |

---

## Database Schema

```prisma
model Attachment {
  id         String   @id @default(cuid())
  documentId String
  document   Document @relation(fields: [documentId], references: [id])
  uploadedBy String                // User ID of uploader
  filename   String                // Original filename
  mimeType   String
  sizeBytes  Int
  storageKey String                // S3 key or local relative path
  url        String?               // Public or signed URL (S3 only)
  createdAt  DateTime @default(now())
  updatedAt  DateTime @updatedAt
}
```

Each `Attachment` record is linked to a parent `Document`. `storageKey` is the internal identifier used by `lib/storage.ts`; `url` is populated only for S3 backends.

---

## Security Measures

### Authentication
- Every API route calls `getSession()` before any other logic; requests without a valid session receive `401`.
- Session tokens are signed with `NEXTAUTH_SECRET`.

### Authorization
- Read access on `GET /api/attachments/[id]` is gated on membership/read permission for the parent document.
- Delete access requires the requester to be the original uploader (`uploadedBy`) or to hold an admin role.

### Validation
- MIME type is checked both client-side (UX) and server-side (enforcement).
- File size is enforced server-side against `MAX_FILE_SIZE_MB`; the client also blocks oversized files early.
- `documentId` is validated to exist and belong to the authenticated user's accessible documents before writing metadata.

### Storage
- S3 uploads use presigned URLs with short expiry for downloads; files are not publicly readable by default.
- Local uploads are stored outside the web root and served only through the authenticated API route.

### Error Handling
- Errors from `lib/storage.ts` are caught in the API route; storage failures do not leave orphaned database records (write is skipped on storage error).

---

## Error Handling

| Status Code | Description |
|---|---|
| `400` | Missing required field (`documentId`, file) or invalid MIME type |
| `401` | No valid session / unauthenticated request |
| `403` | Authenticated but not authorized (wrong user, insufficient role) |
| `404` | Attachment ID not found in the database |
| `413` | File exceeds the maximum allowed size |
| `500` | Unexpected server error (storage failure, database error) |

---

## UI Components

- **`AttachmentUploader`**: File input with drag-and-drop support; performs client-side type/size validation, shows inline error messages, and POSTs to the upload API.
- **`AttachmentPreview`**: Displays a thumbnail (images) or file-type icon (PDFs, other), an upload progress bar during active uploads, filename, file size, and a remove button that triggers the delete flow.
- **`AttachmentList`**: Fetches and renders all `Attachment` records for a given `documentId`; re-fetches after upload or delete events; shows an empty state when no attachments exist.