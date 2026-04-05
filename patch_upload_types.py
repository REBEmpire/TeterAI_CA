import re

with open('src/ui/web/src/components/upload/DocumentUploadPanel.tsx', 'r') as f:
    content = f.read()

target = """const TOOL_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: 'auto',      label: 'Auto-detect from filename' },
  { value: 'rfi',       label: 'RFI Analyzer' },
  { value: 'submittal', label: 'Submittal Reviewer' },
  { value: 'cost',      label: 'Cost Analyzer' },
  { value: 'payapp',    label: 'Pay App Review' },
  { value: 'schedule',  label: 'Schedule Review' },
]"""

replacement = """const TOOL_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: 'auto',      label: 'Let the AI decide' },
  { value: 'rfi',       label: 'Request for Information (RFI)' },
  { value: 'submittal', label: 'Submittal' },
  { value: 'cost',      label: 'Cost Analysis / PCO' },
  { value: 'payapp',    label: 'Pay Application' },
  { value: 'schedule',  label: 'Schedule' },
]"""

content = content.replace(target, replacement)

with open('src/ui/web/src/components/upload/DocumentUploadPanel.tsx', 'w') as f:
    f.write(content)
