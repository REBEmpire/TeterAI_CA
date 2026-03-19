import React from 'react'
import { useAuth } from '../../hooks/useAuth'
import type { UserRole } from '../../types'

interface Props {
  roles: UserRole[]
  fallback?: React.ReactNode
  children: React.ReactNode
}

/**
 * Renders children only if the current user holds one of the given roles.
 * Renders `fallback` (or nothing) otherwise.
 */
export function RoleGuard({ roles, fallback = null, children }: Props) {
  const { user } = useAuth()
  if (!user || !roles.includes(user.role)) return <>{fallback}</>
  return <>{children}</>
}
