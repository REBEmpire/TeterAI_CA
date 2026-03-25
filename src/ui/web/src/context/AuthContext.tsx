import React, {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react'
import { getMe, loginWithGoogleToken, loginWithPassword, ApiError } from '../api/client'
import type { UserInfo } from '../types'

const DESKTOP_MODE = import.meta.env.VITE_DESKTOP_MODE === 'true'

const DESKTOP_USER: UserInfo = {
  uid: 'local',
  email: 'local@desktop',
  display_name: 'Desktop User',
  role: 'ADMIN',
}

interface AuthState {
  user: UserInfo | null
  loading: boolean
  login: (googleIdToken: string) => Promise<void>
  loginPassword: (username: string, password: string) => Promise<void>
  logout: () => void
}

export const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // Desktop mode: auto-login as local ADMIN, no token needed
    if (DESKTOP_MODE) {
      setUser(DESKTOP_USER)
      setLoading(false)
      return
    }

    // Cloud mode: validate stored JWT
    const token = localStorage.getItem('teterai_token')
    if (!token) {
      setLoading(false)
      return
    }
    getMe()
      .then(setUser)
      .catch(() => {
        localStorage.removeItem('teterai_token')
      })
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (googleIdToken: string) => {
    if (DESKTOP_MODE) return
    const resp = await loginWithGoogleToken(googleIdToken)
    localStorage.setItem('teterai_token', resp.access_token)
    setUser(resp.user)
  }, [])

  const loginPassword = useCallback(async (username: string, password: string) => {
    if (DESKTOP_MODE) return
    const resp = await loginWithPassword(username, password)
    localStorage.setItem('teterai_token', resp.access_token)
    setUser(resp.user)
  }, [])

  const logout = useCallback(() => {
    if (DESKTOP_MODE) return  // no logout in single-user desktop mode
    localStorage.removeItem('teterai_token')
    setUser(null)
  }, [])

  const value = useMemo(
    () => ({ user, loading, login, loginPassword, logout }),
    [user, loading, login, loginPassword, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
