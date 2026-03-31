/**
 * SettingsPage — desktop mode configuration.
 *
 * Allows the user to enter API keys, configure local paths, and view
 * the Knowledge Graph connection status. Data is persisted to
 * ~/.teterai/config.env via the /api/v1/settings endpoint.
 */
import { useEffect, useState } from 'react'

const BASE = '/api/v1'

interface SettingsData {
  anthropic_api_key: string
  google_api_key: string
  xai_api_key: string
  neo4j_uri: string
  neo4j_username: string
  projects_root: string
  db_path: string
  inbox_path: string
  poll_interval_seconds: number
  neo4j_connected: boolean
}

async function fetchSettings(): Promise<SettingsData> {
  const res = await fetch(`${BASE}/settings`)
  if (!res.ok) throw new Error('Failed to load settings')
  return res.json()
}

async function saveSettings(data: Partial<SettingsData & { neo4j_password?: string }>): Promise<void> {
  const res = await fetch(`${BASE}/settings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to save settings')
}

function selectFolder(): Promise<string | null> {
  if (typeof window !== 'undefined' && (window as any).electronAPI?.selectFolder) {
    return (window as any).electronAPI.selectFolder()
  }
  return Promise.resolve(null)
}

export function SettingsPage() {
  const [settings, setSettings] = useState<SettingsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  // Editable fields
  const [anthropicKey, setAnthropicKey] = useState('')
  const [googleKey, setGoogleKey] = useState('')
  const [xaiKey, setXaiKey] = useState('')
  const [neo4jUri, setNeo4jUri] = useState('')
  const [neo4jUsername, setNeo4jUsername] = useState('')
  const [neo4jPassword, setNeo4jPassword] = useState('')
  const [projectsRoot, setProjectsRoot] = useState('')
  const [inboxPath, setInboxPath] = useState('')

  useEffect(() => {
    fetchSettings()
      .then(s => {
        setSettings(s)
        setNeo4jUri(s.neo4j_uri)
        setNeo4jUsername(s.neo4j_username)
        setProjectsRoot(s.projects_root)
        setInboxPath(s.inbox_path)
        setLoading(false)
      })
      .catch(e => {
        setError(e.message)
        setLoading(false)
      })
  }, [])

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError('')
    setSaved(false)
    try {
      const payload: Record<string, string | number> = {
        neo4j_uri: neo4jUri,
        neo4j_username: neo4jUsername,
        projects_root: projectsRoot,
        inbox_path: inboxPath,
      }
      if (anthropicKey) payload.anthropic_api_key = anthropicKey
      if (googleKey) payload.google_api_key = googleKey
      if (xaiKey) payload.xai_api_key = xaiKey
      if (neo4jPassword) payload.neo4j_password = neo4jPassword

      await saveSettings(payload)
      setSaved(true)
      // Clear plaintext key fields after save
      setAnthropicKey('')
      setGoogleKey('')
      setXaiKey('')
      setNeo4jPassword('')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleSelectFolder(setter: (v: string) => void) {
    const path = await selectFolder()
    if (path) setter(path)
  }

  if (loading) {
    return (
      <div className="max-w-content mx-auto px-4 py-8 text-sm text-teter-gray-text">
        Loading settings…
      </div>
    )
  }

  return (
    <div className="max-w-content mx-auto px-4 py-8">
      <h1 className="text-2xl font-semibold text-teter-dark mb-1">Settings</h1>
      <p className="text-sm text-teter-gray-text mb-6">
        Configure API keys and local storage paths. Keys are saved to{' '}
        <code className="bg-gray-100 px-1 rounded text-xs">~/.teterai/config.env</code>.
      </p>

      <form onSubmit={handleSave} className="space-y-8">
        {/* AI Providers */}
        <section>
          <h2 className="text-base font-semibold text-teter-dark mb-3 border-b pb-1">
            AI Provider Keys
          </h2>
          <p className="text-xs text-teter-gray-text mb-4">
            Leave blank to keep the current value. Keys are never displayed after saving.
          </p>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-xs font-medium text-teter-dark mb-1">
                Anthropic API Key
                {settings?.anthropic_api_key === '***' && (
                  <span className="ml-2 text-green-600 font-normal">✓ saved</span>
                )}
              </label>
              <input
                type="password"
                placeholder="sk-ant-…"
                value={anthropicKey}
                onChange={e => setAnthropicKey(e.target.value)}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teter-orange"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-teter-dark mb-1">
                Google AI Key
                {settings?.google_api_key === '***' && (
                  <span className="ml-2 text-green-600 font-normal">✓ saved</span>
                )}
              </label>
              <input
                type="password"
                placeholder="AIza…"
                value={googleKey}
                onChange={e => setGoogleKey(e.target.value)}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teter-orange"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-teter-dark mb-1">
                xAI Key
                {settings?.xai_api_key === '***' && (
                  <span className="ml-2 text-green-600 font-normal">✓ saved</span>
                )}
              </label>
              <input
                type="password"
                placeholder="xai-…"
                value={xaiKey}
                onChange={e => setXaiKey(e.target.value)}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teter-orange"
              />
            </div>
          </div>
        </section>

        {/* Knowledge Graph (optional) */}
        <section>
          <h2 className="text-base font-semibold text-teter-dark mb-3 border-b pb-1">
            Knowledge Graph{' '}
            <span className="text-xs font-normal text-teter-gray-text">(optional)</span>
            {settings?.neo4j_connected ? (
              <span className="ml-3 text-xs text-green-600 font-normal">● Connected</span>
            ) : (
              <span className="ml-3 text-xs text-gray-400 font-normal">○ Not connected</span>
            )}
          </h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-xs font-medium text-teter-dark mb-1">Neo4j URI</label>
              <input
                type="text"
                placeholder="bolt://localhost:7687"
                value={neo4jUri}
                onChange={e => setNeo4jUri(e.target.value)}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teter-orange"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-teter-dark mb-1">Neo4j Username</label>
              <input
                type="text"
                placeholder="neo4j"
                value={neo4jUsername}
                onChange={e => setNeo4jUsername(e.target.value)}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teter-orange"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-teter-dark mb-1">Neo4j Password</label>
              <input
                type="password"
                placeholder="Leave blank to keep current"
                value={neo4jPassword}
                onChange={e => setNeo4jPassword(e.target.value)}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teter-orange"
              />
            </div>
          </div>
        </section>

        {/* Local storage paths */}
        <section>
          <h2 className="text-base font-semibold text-teter-dark mb-3 border-b pb-1">
            Storage Paths
          </h2>
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-teter-dark mb-1">Projects Root</label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={projectsRoot}
                  onChange={e => setProjectsRoot(e.target.value)}
                  className="flex-1 border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teter-orange"
                />
                <button
                  type="button"
                  onClick={() => handleSelectFolder(setProjectsRoot)}
                  className="px-3 py-2 text-xs border border-gray-300 rounded hover:bg-gray-50 text-teter-dark"
                >
                  Browse…
                </button>
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-teter-dark mb-1">
                Inbox Folder{' '}
                <span className="font-normal text-teter-gray-text">
                  — drop .eml or .pdf files here to trigger the pipeline
                </span>
              </label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={inboxPath}
                  onChange={e => setInboxPath(e.target.value)}
                  className="flex-1 border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teter-orange"
                />
                <button
                  type="button"
                  onClick={() => handleSelectFolder(setInboxPath)}
                  className="px-3 py-2 text-xs border border-gray-300 rounded hover:bg-gray-50 text-teter-dark"
                >
                  Browse…
                </button>
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-teter-gray-text mb-1">
                Database path{' '}
                <span className="font-normal">(read-only)</span>
              </label>
              <input
                type="text"
                value={settings?.db_path ?? ''}
                readOnly
                className="w-full border border-gray-200 rounded px-3 py-2 text-sm bg-gray-50 text-teter-gray-text cursor-default"
              />
            </div>
          </div>
        </section>

        {/* Feedback / submit */}
        <div className="flex items-center gap-4">
          <button
            type="submit"
            disabled={saving}
            className="bg-teter-orange text-white font-semibold px-6 py-2 rounded hover:opacity-90 transition disabled:opacity-50 text-sm"
          >
            {saving ? 'Saving…' : 'Save Settings'}
          </button>
          {saved && (
            <span className="text-sm text-green-600">Settings saved successfully.</span>
          )}
          {error && (
            <span className="text-sm text-red-500">{error}</span>
          )}
        </div>
      </form>
    </div>
  )
}
