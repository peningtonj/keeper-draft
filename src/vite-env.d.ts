/// <reference types="vite/client" />

declare module '*.json?url' {
  const src: string
  export default src
}
