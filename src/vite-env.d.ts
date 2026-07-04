/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DEV_SIDECAR_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare const __APP_VERSION__: string;
