import { useEffect, useRef, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { ApiError } from '../api/client'

const DESKTOP_MODE = import.meta.env.VITE_DESKTOP_MODE === 'true'

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: object) => void
          renderButton: (element: HTMLElement, config: object) => void
        }
      }
    }
  }
}

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID ?? ''

/**
 * Login page — architectural grid background with Teter brand statement.
 * In DESKTOP_MODE this page is never shown; the app auto-redirects to /dashboard.
 * Google Sign-In is shown only when VITE_GOOGLE_CLIENT_ID is configured.
 */
export function LoginPage() {
  // Desktop mode: skip login entirely
  if (DESKTOP_MODE) {
    return <Navigate to="/dashboard" replace />
  }
  const { user, login, loginPassword } = useAuth()
  const navigate = useNavigate()
  const btnRef = useRef<HTMLDivElement>(null)

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (user) {
      navigate('/dashboard', { replace: true })
    }
  }, [user, navigate])

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID || !window.google || !btnRef.current) return

    window.google.accounts.id.initialize({
      client_id: GOOGLE_CLIENT_ID,
      callback: async (response: { credential: string }) => {
        try {
          await login(response.credential)
          navigate('/dashboard', { replace: true })
        } catch (err) {
          console.error('Login failed:', err)
        }
      },
      hosted_domain: import.meta.env.VITE_ALLOWED_EMAIL_DOMAIN ?? 'teter.com',
    })

    window.google.accounts.id.renderButton(btnRef.current, {
      theme: 'outline',
      size: 'large',
      width: 280,
      text: 'signin_with',
    })
  }, [login, navigate])

  async function handlePasswordSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await loginPassword(username.trim(), password)
      navigate('/dashboard', { replace: true })
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError('Invalid username or password.')
      } else {
        setError('Login failed. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center px-4"
      style={{
        backgroundColor: '#1e1e1e',
        backgroundImage: `
          linear-gradient(rgba(208,111,26,0.05) 1px, transparent 1px),
          linear-gradient(90deg, rgba(208,111,26,0.05) 1px, transparent 1px)
        `,
        backgroundSize: '40px 40px',
      }}
    >
      {/* Logo / brand block */}
      <div className="mb-10 text-center animate-grid-in">
        <div className="flex items-center justify-center gap-3 mb-3">
          <span className="w-[3px] h-14 bg-teter-orange rounded-sm" />
          <div className="text-left">
            <div className="text-3xl font-semibold text-white tracking-tight leading-tight">
              Teter<span className="text-teter-orange">AI</span>
            </div>
            <div className="text-xs font-normal text-white/40 tracking-widest uppercase mt-1">
              Construction Administration
            </div>
          </div>
        </div>
        <p className="text-white/40 text-sm mt-5 max-w-xs text-center leading-relaxed font-light">
          Human-in-the-loop review for AI-generated construction documents.
        </p>
      </div>

      {/* Sign-in card */}
      <div
        className="bg-white rounded-[14px] p-9 w-full max-w-sm flex flex-col items-center gap-6"
        style={{
          boxShadow: '0 24px 64px rgba(0,0,0,0.4), 0 4px 16px rgba(0,0,0,0.2)',
          borderTop: '3px solid #d06f1a',
        }}
      >
        <div className="text-center">
          <h1 className="text-teter-ink font-semibold text-lg mb-1 tracking-tight">Sign in</h1>
          <p className="text-teter-gray-text text-sm">
            Use your <span className="font-semibold">TeterAI</span> credentials.
          </p>
        </div>

        {/* Username / password form */}
        <form onSubmit={handlePasswordSubmit} className="w-full flex flex-col gap-3">
          <input
            type="text"
            placeholder="Username"
            autoComplete="username"
            value={username}
            onChange={e => setUsername(e.target.value)}
            required
            className="input"
          />
          <input
            type="password"
            placeholder="Password"
            autoComplete="current-password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
            className="input"
          />
          {error && (
            <p className="text-xs text-red-500 text-center font-medium">{error}</p>
          )}
          <button
            type="submit"
            disabled={submitting}
            className="btn-primary w-full justify-center"
          >
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        {/* Google Sign-In button — shown only when Client ID is configured */}
        {GOOGLE_CLIENT_ID && (
          <>
            <div className="w-full flex items-center gap-3 text-xs text-teter-gray-text">
              <hr className="flex-1 border-teter-gray-mid" />
              or
              <hr className="flex-1 border-teter-gray-mid" />
            </div>
            <div ref={btnRef} className="flex justify-center" />
          </>
        )}
      </div>

      {/* Footer */}
      <p className="mt-8 text-white/20 text-xs text-center font-light tracking-wide">
        © {new Date().getFullYear()} Teter Architects &amp; Engineers
      </p>

      {/* Load Google Identity Services script (only needed when Client ID is set) */}
      {GOOGLE_CLIENT_ID && (
        <script
          src="https://accounts.google.com/gsi/client"
          async
          defer
        />
      )}
    </div>
  )
}
