import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import Header  from './Header'
import InvestorProfileModal from '@/components/shared/InvestorProfileModal'
import { useAuth } from '@/lib/auth'

export default function AppLayout() {
  const { token, investorProfile, profileLoaded } = useAuth()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const needsProfile = !!token && profileLoaded && !investorProfile

  return (
    <div className="flex h-screen overflow-hidden bg-bg">
      {/* Sidebar — fija en desktop, drawer en móvil */}
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      {/* Main */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <Header onOpenSidebar={() => setSidebarOpen(true)} />
        <main className="flex-1 overflow-y-auto px-3 py-4 md:px-6 md:py-5">
          <Outlet />
        </main>
      </div>

      {/* Modal de perfil de inversor — bloquea hasta que el usuario lo defina */}
      {needsProfile && <InvestorProfileModal />}
    </div>
  )
}
