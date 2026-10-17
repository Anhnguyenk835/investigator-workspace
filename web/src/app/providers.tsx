import { type ReactNode } from 'react'
import { BrowserRouter } from 'react-router-dom'
import { ToastProvider } from '@/components/ui/Toast'
import { AuthProvider } from '@/features/auth/AuthProvider'
import { TourProvider } from '@/features/tour'
import { EvidenceIndexProvider } from '@/features/evidence/EvidenceIndex'
import { SettingsProvider } from '@/hooks/useSettings'

type AppProvidersProps = {
  children: ReactNode
}

export function AppProviders({ children }: AppProvidersProps) {
  return (
    <BrowserRouter>
      <AuthProvider>
        <SettingsProvider>
          <ToastProvider>
            <EvidenceIndexProvider>
              <TourProvider>{children}</TourProvider>
            </EvidenceIndexProvider>
          </ToastProvider>
        </SettingsProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}
