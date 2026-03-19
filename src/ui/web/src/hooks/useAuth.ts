/**
 * Authentication hook — wraps Google OAuth + JWT storage.
 *
 * The app uses Google Identity Services (GIS) for the sign-in button.
 * After Google returns an ID token, we exchange it with our backend for a JWT.
 */
import { useContext } from 'react'
import { AuthContext } from '../context/AuthContext'

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
