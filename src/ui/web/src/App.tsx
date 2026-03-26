import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { RoleGuard } from './components/common/RoleGuard'
import { AuthProvider } from './context/AuthContext'
import { useAuth } from './hooks/useAuth'
import { AdminPanel } from './views/AdminPanel'
import { Dashboard } from './views/Dashboard'
import { KnowledgeGraphView } from './views/KnowledgeGraphView'
import { LoginPage } from './views/LoginPage'
import { SettingsPage } from './views/SettingsPage'
import { SplitViewer } from './views/SplitViewer'
import { SubmittalReviewViewer } from './views/SubmittalReviewViewer'
import { UploadView } from './views/UploadView'

const DESKTOP_MODE = import.meta.env.VITE_DESKTOP_MODE === 'true'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-teter-dark">
        <span className="text-white/50 text-sm">Loading…</span>
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/tasks/:taskId" element={<SplitViewer />} />
        <Route path="/tasks/:taskId/submittal" element={<SubmittalReviewViewer />} />
        <Route path="/upload" element={<UploadView />} />
        <Route path="/knowledge-graph" element={<KnowledgeGraphView />} />
        {DESKTOP_MODE && (
          <Route path="/settings" element={<SettingsPage />} />
        )}
        <Route
          path="/admin"
          element={
            <RoleGuard
              roles={['ADMIN']}
              fallback={
                <div className="max-w-content mx-auto px-4 py-8 text-sm text-teter-gray-text">
                  Access restricted to ADMIN users.
                </div>
              }
            >
              <AdminPanel />
            </RoleGuard>
          }
        />
      </Route>

      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  )
}
