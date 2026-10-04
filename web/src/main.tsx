import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { ThemeProvider } from "next-themes"

import App from "@/App"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { AppDataProvider } from "@/hooks/app-data"
import "./index.css"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <TooltipProvider>
        <AppDataProvider>
          <App />
          <Toaster richColors position="bottom-right" />
        </AppDataProvider>
      </TooltipProvider>
    </ThemeProvider>
  </StrictMode>,
)
