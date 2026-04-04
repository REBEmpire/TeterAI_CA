with open('src/ui/web/src/views/Dashboard.tsx', 'r') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if line.startswith('import { useState, useEffect } from \'react\''):
        new_lines.append(line)
    elif line.startswith('import { apiClient } from \'../../api/client\''):
        new_lines.append(line)
    else:
        new_lines.append(line)

with open('src/ui/web/src/views/Dashboard.tsx', 'w') as f:
    f.writelines(new_lines)
