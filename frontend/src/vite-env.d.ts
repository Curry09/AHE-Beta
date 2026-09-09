/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_STATIC_SITE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
