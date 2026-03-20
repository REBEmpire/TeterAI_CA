import React, {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react'
import { getMe, loginWithGoogleToken, loginWithPassword, ApiError } from '../api/client'
import type { UserInfo } from '../types'

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

  // On mount: validate stored JWT and fetch current user
  useEffect(() => {
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
    const resp = await loginWithGoogleToken(googleIdToken)
    localStorage.setItem('teterai_token', resp.access_token)
    setUser(resp.user)
  }, [])

  const loginPassword = useCallback(async (username: string, password: string) => {
    const resp = await loginWithPassword(username, password)
    localStorage.setItem('teterai_token', resp.access_token)
    setUser(resp.user)
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem('teterai_token')
    setUser(null)
  }, [])

  const value = useMemo(
    () => ({ user, loading, login, loginPassword, logout }),
    [user, loading, login, loginPassword, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
