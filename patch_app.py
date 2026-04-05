with open('src/ui/web/src/App.tsx', 'r') as f:
    content = f.read()

# We will intercept API errors and show plain language
target = """import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'"""
replacement = """import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'
import { ErrorBoundary } from 'react-error-boundary'

function ErrorFallback({ error }: { error: Error }) {
  let message = "Something went wrong. The team has been notified."
  if (error.message.includes("503") || error.message.includes("Failed to fetch")) {
    message = "The app is starting up or unavailable. Please try again in a few seconds."
  } else if (error.message.includes("404")) {
    message = "That resource wasn't found. Please check your link and try again."
  } else if (error.message.includes("timeout")) {
    message = "The request took too long. Check your connection or file size and try again."
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 p-4">
      <div className="bg-white rounded-lg shadow p-6 max-w-sm w-full border border-red-100">
        <h2 className="text-lg font-semibold text-red-600 mb-2">Oops! Something went wrong</h2>
        <p className="text-gray-600 text-sm mb-4">{message}</p>
        <button onClick={() => window.location.href = '/'} className="bg-teter-orange text-white px-4 py-2 rounded font-medium text-sm w-full">Return to Dashboard</button>
      </div>
    </div>
  )
}"""

content = content.replace(target, replacement)

target2 = """    <AuthProvider>
      <Router>"""

replacement2 = """    <AuthProvider>
      <ErrorBoundary FallbackComponent={ErrorFallback}>
      <Router>"""

target3 = """      </Router>
    </AuthProvider>"""

replacement3 = """      </Router>
      </ErrorBoundary>
    </AuthProvider>"""

content = content.replace(target2, replacement2)
content = content.replace(target3, replacement3)

with open('src/ui/web/src/App.tsx', 'w') as f:
    f.write(content)
