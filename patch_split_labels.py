with open('src/ui/web/src/views/SplitViewer.tsx', 'r') as f:
    content = f.read()

content = content.replace("import { UrgencyBadge } from '../components/common/UrgencyBadge'", "import { UrgencyBadge } from '../components/common/UrgencyBadge'\nimport { STATUS_LABELS, DOC_TYPE_LABELS } from '../constants/statusLabels'")

content = content.replace("{PIPELINE_STATUS_LABEL[task.status] ?? task.status}", "{STATUS_LABELS[task.status] || task.status}")
content = content.replace("PIPELINE_STATUS_LABEL[task.status] ?? task.status", "STATUS_LABELS[task.status] || task.status")

content = content.replace("{task.document_type || 'Unknown Type'}", "{DOC_TYPE_LABELS[task.document_type || 'UNKNOWN'] || task.document_type || 'Unknown Type'}")

with open('src/ui/web/src/views/SplitViewer.tsx', 'w') as f:
    f.write(content)
