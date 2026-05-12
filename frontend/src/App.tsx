import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from '@/lib/auth'
import { ThemeProvider } from '@/lib/theme'
import { GapFilterProvider } from '@/lib/gapFilter'
import AppLayout from '@/components/layout/AppLayout'
import Dashboard   from '@/pages/Dashboard'
import AssetDetail from '@/pages/AssetDetail'
import Screener    from '@/pages/Screener'
import Alerts      from '@/pages/Alerts'
import Watchlist   from '@/pages/Watchlist'
import Movimientos from '@/pages/Movimientos'
import Settings    from '@/pages/Settings'
import ElliottPage from '@/pages/ElliottPage'
import Tendencias  from '@/pages/Tendencias'
import Bonos       from '@/pages/Bonos'
import Login       from '@/pages/Login'

function ProtectedRoutes() {
  const { token, username } = useAuth()
  if (!token) return <Navigate to="/login" replace />

  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/asset/:id" element={<AssetDetail />} />
        <Route path="/screener" element={<Screener />} />
        <Route path="/alerts" element={<Alerts />} />
        <Route path="/watchlist" element={<Watchlist />} />
        <Route path="/elliott" element={<ElliottPage />} />
        <Route path="/tendencias" element={<Tendencias />} />
        <Route path="/bonos" element={<Bonos />} />
        {username === 'albano' && (
          <Route path="/movimientos" element={<Movimientos />} />
        )}
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  )
}

function AppRoutes() {
  const { token } = useAuth()

  return (
    <Routes>
      <Route path="/login" element={token ? <Navigate to="/dashboard" replace /> : <Login />} />
      <Route path="/*" element={<ProtectedRoutes />} />
    </Routes>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <GapFilterProvider>
          <BrowserRouter>
            <AppRoutes />
          </BrowserRouter>
        </GapFilterProvider>
      </AuthProvider>
    </ThemeProvider>
  )
}
