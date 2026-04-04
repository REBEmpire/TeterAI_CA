with open('src/ui/web/src/views/Dashboard.tsx', 'r') as f:
    content = f.read()

content = content.replace("import { UrgencyBadge } from '../components/common/UrgencyBadge'", "import { UrgencyBadge } from '../components/common/UrgencyBadge'\nimport { STATUS_LABELS, STATUS_COLORS, DOC_TYPE_LABELS } from '../constants/statusLabels'")

# Fix PIPELINE_STATUS_LABEL usage
content = content.replace("{PIPELINE_STATUS_LABEL[task.status] ?? task.status}", "{STATUS_LABELS[task.status] || task.status}")

# Fix status coloring if it exists
if "const statusColor = isPipeline" in content:
    pass # we might need to look at how it renders

# Let's write it and look at TaskCard
with open('src/ui/web/src/views/Dashboard.tsx', 'w') as f:
    f.write(content)
