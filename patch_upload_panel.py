import re

with open('src/ui/web/src/components/upload/DocumentUploadPanel.tsx', 'r') as f:
    content = f.read()

target_nav = "import { useEffect, useRef, useState } from 'react'"
replacement_nav = "import { useEffect, useRef, useState } from 'react'\nimport { useNavigate } from 'react-router-dom'"

if "useNavigate" not in content:
    content = content.replace(target_nav, replacement_nav)

if "const navigate =" not in content:
    content = content.replace("export function DocumentUploadPanel() {", "export function DocumentUploadPanel() {\n  const navigate = useNavigate()\n  const [projects, setProjects] = useState<ProjectSummary[]>([])\n  const [projectSearch, setProjectSearch] = useState('')\n  const [showProjectDropdown, setShowProjectDropdown] = useState(false)\n\n  useEffect(() => {\n    listProjects().then(setProjects).catch(() => {})\n  }, [])\n")

target_submit = """      setSuccessMsg('Document successfully uploaded and queued for processing.')
      setFiles(null)
      setProjectId('')
      setToolType('auto')
      if (fileInputRef.current) fileInputRef.current.value = ''
    } catch (e: any) {"""

replacement_submit = """      setSuccessMsg('Document successfully uploaded and queued for processing.')
      setFiles(null)
      setProjectId('')
      setToolType('auto')
      if (fileInputRef.current) fileInputRef.current.value = ''

      if (res && res.task_id) {
        navigate(`/task/${res.task_id}`)
      }
    } catch (e: any) {"""

content = content.replace(target_submit, replacement_submit)

target_project_field = """            <input
              type="text"
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-teter-orange focus:ring-teter-orange sm:text-sm"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              placeholder="e.g. 11900 or 'WHCCD Instructional Center'"
            />"""

replacement_project_field = """            <div className="relative mt-1">
              <input
                type="text"
                className="block w-full rounded-md border-gray-300 shadow-sm focus:border-teter-orange focus:ring-teter-orange sm:text-sm"
                value={projectSearch || projectId}
                onChange={(e) => {
                  setProjectSearch(e.target.value);
                  setProjectId(e.target.value);
                  setShowProjectDropdown(true);
                }}
                onFocus={() => setShowProjectDropdown(true)}
                placeholder="e.g. 11900 or 'WHCCD Instructional Center'"
              />
              {showProjectDropdown && (
                <ul className="absolute z-10 mt-1 max-h-60 w-full overflow-auto rounded-md bg-white py-1 text-base shadow-lg ring-1 ring-black ring-opacity-5 focus:outline-none sm:text-sm">
                  {projects.filter(p => !projectSearch || p.project_number.includes(projectSearch) || p.project_name.toLowerCase().includes(projectSearch.toLowerCase())).length === 0 ? (
                    <li className="relative cursor-default select-none py-2 pl-3 pr-9 text-gray-500">
                      No projects found. Check number or contact admin.
                    </li>
                  ) : (
                    projects.filter(p => !projectSearch || p.project_number.includes(projectSearch) || p.project_name.toLowerCase().includes(projectSearch.toLowerCase())).map((p) => (
                      <li
                        key={p.project_id}
                        className="relative cursor-pointer select-none py-2 pl-3 pr-9 text-gray-900 hover:bg-teter-orange hover:text-white"
                        onMouseDown={() => {
                          setProjectId(p.project_id);
                          setProjectSearch(`${p.project_number} — ${p.project_name}`);
                          setShowProjectDropdown(false);
                        }}
                      >
                        <span className="block truncate font-medium">{p.project_number}</span>
                        <span className="block truncate text-xs opacity-80">{p.project_name}</span>
                      </li>
                    ))
                  )}
                </ul>
              )}
            </div>"""

content = content.replace(target_project_field, replacement_project_field)

target_types = """const TOOL_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: 'auto',      label: 'Auto-detect from filename' },
  { value: 'rfi',       label: 'RFI Analyzer' },
  { value: 'submittal', label: 'Submittal Reviewer' },
  { value: 'cost',      label: 'Cost Analyzer' },
  { value: 'payapp',    label: 'Pay App Review' },
  { value: 'schedule',  label: 'Schedule Review' },
]"""

replacement_types = """const TOOL_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: 'auto',      label: 'Let the AI decide' },
  { value: 'rfi',       label: 'Request for Information (RFI)' },
  { value: 'submittal', label: 'Submittal' },
  { value: 'cost',      label: 'Cost Analysis / PCO' },
  { value: 'payapp',    label: 'Pay Application' },
  { value: 'schedule',  label: 'Schedule' },
]"""

if "Let the AI decide" not in content:
    content = content.replace(target_types, replacement_types)

with open('src/ui/web/src/components/upload/DocumentUploadPanel.tsx', 'w') as f:
    f.write(content)
