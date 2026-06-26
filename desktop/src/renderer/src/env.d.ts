/// <reference types="vite/client" />

declare namespace JSX {
  interface IntrinsicElements {
    // Electron's own type defs don't augment JSX.IntrinsicElements for this
    // (it's a Chromium-custom-element tag, not a DOM/React-known one) — only
    // the handful of props the AceStep view actually uses.
    webview: React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & {
      src?: string
      style?: React.CSSProperties
      allowpopups?: string
    }
  }
}
