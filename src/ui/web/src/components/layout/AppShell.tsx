import { Outlet } from 'react-router-dom'
import { NavBar } from './NavBar'

/**
 * Root layout shell: NavBar + page content area.
 * All authenticated views are rendered via <Outlet />.
 */
export function AppShell() {
  return (
    <div className="min-h-screen flex flex-col bg-gray-50">
      <NavBar />
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
