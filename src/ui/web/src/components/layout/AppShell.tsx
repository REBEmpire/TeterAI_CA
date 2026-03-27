import { Outlet } from 'react-router-dom'
import { NavBar } from './NavBar'

/**
 * Root layout shell: NavBar + page content area.
 * All authenticated views are rendered via <Outlet />.
 * Subtle dot-grid background adds architectural texture without distraction.
 */
export function AppShell() {
  return (
    <div
      className="min-h-screen flex flex-col"
      style={{
        backgroundColor: '#f4f4f5',
        backgroundImage: 'radial-gradient(circle, #c8c8ca 1px, transparent 1px)',
        backgroundSize: '24px 24px',
      }}
    >
      <NavBar />
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
