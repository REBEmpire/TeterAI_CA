with open('src/ui/web/src/api/client.ts', 'r') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if line.startswith("export const apiClient = {"):
        break
    new_lines.append(line)

new_lines.append("export const apiClient = {\n")
new_lines.append("  getSettings: () => request<any>('GET', '/settings'),\n")
new_lines.append("  post: (path: string, data: any) => request<any>('POST', path, data),\n")
new_lines.append("  getHealth: () => request<any>('GET', '/health'),\n")
new_lines.append("  retryTask: (taskId: string) => request<any>('POST', `/tasks/${taskId}/retry`)\n")
new_lines.append("}\n")

with open('src/ui/web/src/api/client.ts', 'w') as f:
    f.writelines(new_lines)
