import type { ReactNode } from "react"

export default function Decorator({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        padding: 24,
        fontFamily: "system-ui",
        background: "#f1f5f9",
        minHeight: "100vh",
      }}
    >
      {children}
    </div>
  )
}
