/**
 * UploadView — page wrapper for the document upload flow (Phase C).
 *
 * Renders a branded page header followed by DocumentUploadPanel.
 */
import { DocumentUploadPanel } from '../components/upload/DocumentUploadPanel'

export function UploadView() {
  return (
    <div className="max-w-wide mx-auto px-4 py-6">
      {/* Page header — matches Dashboard layout */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-teter-dark">Upload Document</h1>
          <p className="text-sm text-teter-gray-text mt-0.5">
            Submit a construction document for AI-assisted review
          </p>
        </div>
        {/* Orange accent bar — matches teterae.com section headers */}
        <div className="hidden sm:block w-1 h-8 bg-teter-orange rounded-sm" />
      </div>

      <DocumentUploadPanel />
    </div>
  )
}
