import re

with open('src/ui/web/src/views/Dashboard.tsx', 'r') as f:
    content = f.read()

target = """export function Dashboard() {
  const { user } = useAuth()
  const { tasks, loading, loadTasks } = useTaskQueue()"""

replacement = """export function Dashboard() {
  const { user } = useAuth()
  const { tasks, loading, loadTasks } = useTaskQueue()

  // Area D1: Onboarding State
  const [showOnboarding, setShowOnboarding] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    const hasOnboarded = localStorage.getItem('teterai_onboarded') === 'true'
    if (!hasOnboarded) {
      listProjects().then(projects => {
        if (projects.length === 0) {
          setShowOnboarding(true)
        } else {
          localStorage.setItem('teterai_onboarded', 'true')
        }
      })
    }
  }, [])

  const dismissOnboarding = () => {
    localStorage.setItem('teterai_onboarded', 'true')
    setShowOnboarding(false)
  }
"""

if "Area D1" not in content:
    content = content.replace(target, replacement)

target_render = """      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">"""

replacement_render = """      {showOnboarding && (
        <div className="mb-6 bg-blue-50 border border-blue-200 rounded-xl p-6 relative overflow-hidden">
          <div className="absolute top-0 right-0 p-4">
            <button onClick={dismissOnboarding} className="text-blue-400 hover:text-blue-600">
              <span className="sr-only">Dismiss</span>
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <h2 className="text-lg font-bold text-blue-900 mb-2">Welcome to TeterAI Desktop!</h2>
          <p className="text-sm text-blue-800 mb-4 max-w-2xl">
            Let's get you set up. Complete these three steps to start using AI for construction administration.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-white rounded-lg p-4 shadow-sm border border-blue-100 flex flex-col">
              <div className="flex items-center gap-2 mb-2">
                <div className="w-6 h-6 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center font-bold text-xs">1</div>
                <h3 className="font-semibold text-gray-900">Connect AI Keys</h3>
              </div>
              <p className="text-xs text-gray-600 mb-4 flex-grow">Add your API keys so the application can process documents.</p>
              <button onClick={() => navigate('/settings')} className="text-sm bg-blue-600 text-white px-3 py-1.5 rounded w-full hover:bg-blue-700 transition-colors">Go to Settings</button>
            </div>

            <div className="bg-white rounded-lg p-4 shadow-sm border border-blue-100 flex flex-col">
              <div className="flex items-center gap-2 mb-2">
                <div className="w-6 h-6 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center font-bold text-xs">2</div>
                <h3 className="font-semibold text-gray-900">Add a Project</h3>
              </div>
              <p className="text-xs text-gray-600 mb-4 flex-grow">Create your first project to organize your documents.</p>
              <button onClick={() => navigate('/admin')} className="text-sm bg-blue-600 text-white px-3 py-1.5 rounded w-full hover:bg-blue-700 transition-colors">Open Admin Panel</button>
            </div>

            <div className="bg-white rounded-lg p-4 shadow-sm border border-blue-100 flex flex-col">
              <div className="flex items-center gap-2 mb-2">
                <div className="w-6 h-6 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center font-bold text-xs">3</div>
                <h3 className="font-semibold text-gray-900">Upload Document</h3>
              </div>
              <p className="text-xs text-gray-600 mb-4 flex-grow">Add an RFI, Submittal, or Pay App to see the AI in action.</p>
              <button onClick={() => navigate('/upload')} className="text-sm bg-blue-600 text-white px-3 py-1.5 rounded w-full hover:bg-blue-700 transition-colors">Upload File</button>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">"""

if "showOnboarding &&" not in content:
    content = content.replace(target_render, replacement_render)

with open('src/ui/web/src/views/Dashboard.tsx', 'w') as f:
    f.write(content)
