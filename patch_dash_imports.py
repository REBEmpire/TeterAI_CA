with open('src/ui/web/src/views/Dashboard.tsx', 'r') as f:
    content = f.read()

content = content.replace("import { listProjects, scanProjects } from '../api/client'", "import { listProjects, scanProjects, apiClient } from '../api/client'")

with open('src/ui/web/src/views/Dashboard.tsx', 'w') as f:
    f.write(content)
