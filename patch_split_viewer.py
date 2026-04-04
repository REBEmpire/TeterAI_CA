import re

with open('src/ui/web/src/views/SplitViewer.tsx', 'r') as f:
    content = f.read()

target = """  useEffect(() => {
    if (!taskId) return
    loadTask()
  }, [taskId])"""

replacement = """  useEffect(() => {
    if (!taskId) return
    loadTask()

    // Area B2: Auto-refresh while processing
    const interval = setInterval(() => {
      if (task && PIPELINE_STATUSES.has(task.status)) {
        loadTask()
      }
    }, 15000)

    return () => clearInterval(interval)
  }, [taskId, task?.status])"""

content = content.replace(target, replacement)

with open('src/ui/web/src/views/SplitViewer.tsx', 'w') as f:
    f.write(content)
