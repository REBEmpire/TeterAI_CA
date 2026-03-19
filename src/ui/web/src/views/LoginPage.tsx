import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

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
 * Login page — branded Teter dark background with Google Sign-In button.
 * Mirrors the professional, minimal aesthetic of teterae.com.
 */
export function LoginPage() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const btnRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (user) {
      navigate('/dashboard', { replace: true })
    }
  }, [user, navigate])

  useEffect(() => {
    if (!window.google || !btnRef.current) return

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

  return (
    <div className="min-h-screen bg-teter-dark flex flex-col items-center justify-center px-4">
      {/* Logo / brand block */}
      <div className="mb-10 text-center">
        <div className="flex items-center justify-center gap-3 mb-3">
          <span className="w-1.5 h-12 bg-teter-orange rounded-sm" />
          <div className="text-left">
            <div className="text-3xl font-semibold text-white tracking-wide leading-tight">
              Teter<span className="text-teter-orange">AI</span>
            </div>
            <div className="text-xs font-normal text-white/40 tracking-widest uppercase mt-0.5">
              Construction Administration
            </div>
          </div>
        </div>
        <p className="text-white/50 text-sm mt-4 max-w-xs text-center">
          Human-in-the-loop review for AI-generated construction documents.
        </p>
      </div>

      {/* Sign-in card */}
      <div className="bg-white rounded-lg shadow-lg p-8 w-full max-w-sm flex flex-col items-center gap-6">
        <div className="text-center">
          <h1 className="text-teter-dark font-semibold text-lg mb-1">Sign in</h1>
          <p className="text-teter-gray-text text-sm">
            Use your <span className="font-semibold">@teter.com</span> Google account.
          </p>
        </div>

        {/* Google Sign-In button rendered by GIS SDK */}
        <div ref={btnRef} className="flex justify-center" />

        {!GOOGLE_CLIENT_ID && (
          <p className="text-xs text-red-500 text-center">
            Google OAuth not configured. Set{' '}
            <code className="bg-gray-100 px-1 rounded">VITE_GOOGLE_CLIENT_ID</code>.
          </p>
        )}
      </div>

      {/* Footer */}
      <p className="mt-8 text-white/25 text-xs text-center">
        © {new Date().getFullYear()} Teter Architects &amp; Engineers
      </p>

      {/* Load Google Identity Services script */}
      <script
        src="https://accounts.google.com/gsi/client"
        async
        defer
      />
    </div>
  )
}
