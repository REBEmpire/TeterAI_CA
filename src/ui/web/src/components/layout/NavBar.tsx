import { Link, useLocation } from 'react-router-dom'
import { useAuth } from '../../hooks/useAuth'
import { RoleGuard } from '../common/RoleGuard'

const DESKTOP_MODE = import.meta.env.VITE_DESKTOP_MODE === 'true'

/**
 * Top navigation bar — frosted glass treatment over Teter's #313131 dark header.
 * Active nav links are underlined with the brand orange for precise visual cues.
 */
export function NavBar() {
  const { user, logout } = useAuth()
  const location = useLocation()

  const navLink = (to: string, label: string) => {
    const active = location.pathname.startsWith(to)
    return (
      <Link
        to={to}
        className={`relative px-4 py-2 text-sm font-medium rounded-md transition-all duration-200 ${
          active
            ? 'text-teter-orange bg-white/10'
            : 'text-white/75 hover:text-white hover:bg-white/8'
        }`}
      >
        {label}
        {active && (
          <span className="absolute bottom-0 left-3 right-3 h-[2px] bg-teter-orange rounded-full" />
        )}
      </Link>
    )
  }

  return (
    <header
      className="sticky top-0 z-40 border-b border-white/8"
      style={{
        backgroundColor: 'rgba(49,49,49,0.96)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        boxShadow: '0 1px 0 rgba(255,255,255,0.06), 0 4px 24px rgba(0,0,0,0.25)',
      }}
    >
      <div className="max-w-wide mx-auto px-4 flex items-center h-14 gap-2">
        {/* Brand mark */}
        <Link to="/dashboard" className="flex items-center gap-3 mr-6 group">
          <span className="w-[3px] h-9 bg-teter-orange rounded-sm transition-all duration-200 group-hover:h-10" />
          <span className="font-semibold text-base tracking-tight text-white leading-none">
            Teter<span className="text-teter-orange">AI</span>
            <span className="block text-[10px] font-normal text-white/45 tracking-widest uppercase mt-0.5">
              Construction Administration
            </span>
          </span>
        </Link>

        {/* Nav links */}
        <nav className="flex items-center gap-0.5">
          {navLink('/dashboard', 'Action Dashboard')}
          {/* Upload nav item */}
          <NavIconLink
            to="/upload"
            label="Upload"
            active={location.pathname.startsWith('/upload')}
            icon={
              <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
              </svg>
            }
          />
          {/* Knowledge Graph nav item */}
          <NavIconLink
            to="/knowledge-graph"
            label="Knowledge Graph"
            active={location.pathname.startsWith('/knowledge-graph')}
            icon={
              <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                <circle cx="5"  cy="12" r="2" />
                <circle cx="19" cy="5"  r="2" />
                <circle cx="19" cy="19" r="2" />
                <circle cx="12" cy="12" r="2" />
                <line x1="7"  y1="12" x2="10" y2="12" />
                <line x1="14" y1="12" x2="17" y2="6.5" />
                <line x1="14" y1="12" x2="17" y2="17.5" />
              </svg>
            }
          />
          {/* Project Intelligence nav item */}
          <NavIconLink
            to="/project-intelligence"
            label="Project Intelligence"
            active={location.pathname.startsWith('/project-intelligence')}
            icon={
              <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                <rect x="3"  y="12" width="4" height="9" rx="1" />
                <rect x="10" y="7"  width="4" height="14" rx="1" />
                <rect x="17" y="3"  width="4" height="18" rx="1" />
              </svg>
            }
          />
          {/* Pre-Bid Lessons Learned nav item */}
          <NavIconLink
            to="/prebid-review"
            label="Pre-Bid Review"
            active={location.pathname.startsWith('/prebid-review')}
            icon={
              <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2" />
                <rect x="9" y="3" width="6" height="4" rx="1" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4" />
              </svg>
            }
          />
          {DESKTOP_MODE && navLink('/settings', 'Settings')}
          {!DESKTOP_MODE && (
            <RoleGuard roles={['ADMIN']}>
              {navLink('/admin', 'Admin')}
            </RoleGuard>
          )}
        </nav>

        {/* Right side: user info + logout */}
        <div className="ml-auto flex items-center gap-3">
          {user && (
            <>
              <span className="text-sm text-white/65 hidden sm:block font-light tracking-wide">
                {user.display_name}
              </span>
              <span className="text-[11px] px-2.5 py-1 rounded-full border border-teter-orange/30 bg-teter-orange/15 text-teter-orange-light font-semibold uppercase tracking-wider">
                {user.role.replace('_', ' ')}
              </span>
              <button
                onClick={logout}
                className="text-sm text-white/50 hover:text-white/90 transition-colors duration-150 font-medium"
              >
                Logout
              </button>
            </>
          )}
        </div>
      </div>
    </header>
  )
}

/** Nav link with an inline SVG icon and orange underline on active state. */
function NavIconLink({
  to, label, active, icon,
}: {
  to: string
  label: string
  active: boolean
  icon: React.ReactNode
}) {
  return (
    <Link
      to={to}
      className={`
        relative flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-md
        transition-all duration-200
        ${active
          ? 'text-teter-orange bg-white/10'
          : 'text-white/75 hover:text-white hover:bg-white/8'}
      `}
    >
      {icon}
      {label}
      {active && (
        <span className="absolute bottom-0 left-3 right-3 h-[2px] bg-teter-orange rounded-full" />
      )}
    </Link>
  )
}
