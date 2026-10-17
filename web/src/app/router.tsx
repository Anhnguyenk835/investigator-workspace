import { Navigate, Route, Routes, useParams, useSearchParams } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { LoginPage } from '@/features/auth/LoginPage'
import { RequireAuth } from '@/features/auth/RequireAuth'
import { ConnectorsPage } from '@/features/connectors/ConnectorsPage'
import { DirectoryPage } from '@/features/directory/DirectoryPage'
import { InvestigationsPage } from '@/features/investigations/InvestigationsPage'
import { NewInvestigationPage } from '@/features/investigations/NewInvestigationPage'
import { ResponseRedirect } from '@/features/investigations/ResponsePage'
import { WorkspacePage } from '@/features/investigations/WorkspacePage'
import { SettingsPage } from '@/features/settings/SettingsPage'
import { DesignSystemPage } from '@/pages/DesignSystemPage'
import { NotFoundPage } from '@/pages/NotFoundPage'

/** /investigations/:id/evidence/:evidenceId opens the workspace with the evidence drawer. */
function EvidenceRedirect() {
  const { id = '', evidenceId = '' } = useParams()
  const [params] = useSearchParams()
  const next = new URLSearchParams(params)
  next.set('evidence', evidenceId)
  return <Navigate replace to={`/investigations/${id}?${next.toString()}`} />
}

export function AppRouter() {
  return (
    <Routes>
      <Route path="login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
      <Route element={<AppShell />}>
        <Route index element={<Navigate replace to="/investigations" />} />
        <Route path="investigations" element={<InvestigationsPage />} />
        <Route path="investigations/new" element={<NewInvestigationPage />} />
        <Route path="investigations/:id" element={<WorkspacePage />} />
        <Route path="investigations/:id/response" element={<ResponseRedirect />} />
        <Route path="investigations/:id/evidence/:evidenceId" element={<EvidenceRedirect />} />
        <Route path="sources/*" element={<Navigate to="/investigations" replace />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="settings/connectors" element={<ConnectorsPage />} />
        <Route path="settings/directory" element={<DirectoryPage />} />
        <Route path="settings/connectors/*" element={<Navigate to="/settings/connectors" replace />} />
        <Route path="activity" element={<Navigate to="/investigations" replace />} />
        <Route path="system" element={<DesignSystemPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
      </Route>
    </Routes>
  )
}
