import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'

export type InvestorProfile = 'conservador' | 'moderado' | 'agresivo' | null

interface AuthState {
  token:           string | null
  username:        string | null
  investorProfile: InvestorProfile
  profileLoaded:   boolean
}

interface AuthCtx extends AuthState {
  login: (token: string, username: string, profile?: InvestorProfile) => void
  logout: () => void
  setInvestorProfile: (profile: InvestorProfile) => void
}

const AuthContext = createContext<AuthCtx>(null!)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(() => {
    const stored = localStorage.getItem('investor_profile')
    return {
      token:           localStorage.getItem('token'),
      username:        localStorage.getItem('username'),
      investorProfile: (stored as InvestorProfile) || null,
      profileLoaded:   stored !== null,
    }
  })

  const login = (token: string, username: string, profile: InvestorProfile = null) => {
    localStorage.setItem('token', token)
    localStorage.setItem('username', username)
    if (profile) localStorage.setItem('investor_profile', profile)
    else         localStorage.removeItem('investor_profile')
    setState({ token, username, investorProfile: profile, profileLoaded: true })
  }

  const logout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('username')
    localStorage.removeItem('investor_profile')
    setState({ token: null, username: null, investorProfile: null, profileLoaded: false })
  }

  const setInvestorProfile = (profile: InvestorProfile) => {
    if (profile) localStorage.setItem('investor_profile', profile)
    else         localStorage.removeItem('investor_profile')
    setState(s => ({ ...s, investorProfile: profile, profileLoaded: true }))
  }

  // Si hay token pero no sabemos el perfil (refresh de página), preguntarle al backend.
  useEffect(() => {
    if (!state.token || state.profileLoaded) return
    let cancelled = false
    fetch('/api/auth/me', { headers: { Authorization: `Bearer ${state.token}` } })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (cancelled || !data) return
        const p = (data.investor_profile as InvestorProfile) || null
        if (p) localStorage.setItem('investor_profile', p)
        setState(s => ({ ...s, investorProfile: p, profileLoaded: true }))
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [state.token, state.profileLoaded])

  return (
    <AuthContext.Provider value={{ ...state, login, logout, setInvestorProfile }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
