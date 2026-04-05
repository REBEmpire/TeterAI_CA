import re

with open('src/ui/web/src/views/UploadView.tsx', 'r') as f:
    content = f.read()

# Make sure imports are added
if "useNavigate" not in content:
    content = content.replace("import { useState, useRef, useEffect } from 'react'", "import { useState, useRef, useEffect } from 'react'\nimport { useNavigate } from 'react-router-dom'")
    content = content.replace("import { useState, useRef } from 'react'", "import { useState, useRef } from 'react'\nimport { useNavigate } from 'react-router-dom'")

if "const navigate =" not in content:
    content = content.replace("export function UploadView() {", "export function UploadView() {\n  const navigate = useNavigate()")

target = """      setSuccessMsg('Document successfully uploaded and queued for processing.')
      setFiles(null)
      setProjectId('')
      setToolType('auto')
      if (fileInputRef.current) fileInputRef.current.value = ''
    } catch (e: any) {"""

replacement = """      setSuccessMsg('Document successfully uploaded and queued for processing.')
      setFiles(null)
      setProjectId('')
      setToolType('auto')
      if (fileInputRef.current) fileInputRef.current.value = ''

      if (res && res.task_id) {
        navigate(`/task/${res.task_id}`)
      }
    } catch (e: any) {"""

content = content.replace(target, replacement)

with open('src/ui/web/src/views/UploadView.tsx', 'w') as f:
    f.write(content)
