<<<<<<< SEARCH
  const pendingTasks = tasks.filter((t) => t.status === 'PENDING_CLASSIFICATION' || t.status === 'CLASSIFYING')
  const reviewTasks = tasks.filter((t) => ['STAGED_FOR_REVIEW', 'ESCALATED_TO_HUMAN'].includes(t.status))
  const completedTasks = tasks.filter((t) => ['APPROVED', 'REJECTED', 'DELIVERED'].includes(t.status))
=======
  const pendingTasks = tasks.filter((t) => t.status === 'PENDING_CLASSIFICATION' || t.status === 'CLASSIFYING')
  const reviewTasks = tasks.filter((t) => ['STAGED_FOR_REVIEW', 'ESCALATED_TO_HUMAN'].includes(t.status))
  const completedTasks = tasks.filter((t) => ['APPROVED', 'REJECTED', 'DELIVERED'].includes(t.status))
  const errorTasks = tasks.filter((t) => t.status === 'ERROR')
>>>>>>> REPLACE
<<<<<<< SEARCH
  // 1. Sort grouped tasks by urgency and age
  const sortTasks = (taskList: Task[]) => {
=======
  // 1. Sort grouped tasks by urgency and age
  const sortTasks = (taskList: Task[]) => {
    return taskList.sort((a, b) => {
>>>>>>> REPLACE
<<<<<<< SEARCH
    return taskList.sort((a, b) => {
      const uA = URGENCY_WEIGHT[a.urgency || 'MEDIUM'] || 0
      const uB = URGENCY_WEIGHT[b.urgency || 'MEDIUM'] || 0
      if (uA !== uB) return uB - uA // Highest urgency first
      // Fallback to oldest first (fifo)
      const dateA = new Date(a.created_at).getTime()
      const dateB = new Date(b.created_at).getTime()
      return dateA - dateB
    })
  }

  const sortedPending = sortTasks(pendingTasks)
  const sortedReview = sortTasks(reviewTasks)
  const sortedCompleted = sortTasks(completedTasks).reverse() // Newest completed first
=======
      const uA = URGENCY_WEIGHT[a.urgency || 'MEDIUM'] || 0
      const uB = URGENCY_WEIGHT[b.urgency || 'MEDIUM'] || 0
      if (uA !== uB) return uB - uA // Highest urgency first
      // Fallback to oldest first (fifo)
      const dateA = new Date(a.created_at).getTime()
      const dateB = new Date(b.created_at).getTime()
      return dateA - dateB
    })
  }

  const sortedPending = sortTasks(pendingTasks)
  const sortedReview = sortTasks(reviewTasks)
  const sortedCompleted = sortTasks(completedTasks).reverse() // Newest completed first
  const sortedErrors = sortTasks(errorTasks)
>>>>>>> REPLACE
<<<<<<< SEARCH
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* Column 1: Inbox / Processing */}
        <div className="flex flex-col h-full bg-white rounded-xl shadow-sm border border-gray-200">
=======
      {sortedErrors.length > 0 && (
        <div className="mb-6 space-y-4">
          <h3 className="text-sm font-semibold text-red-600 uppercase tracking-wider flex items-center gap-2">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            Requires Attention ({sortedErrors.length})
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {sortedErrors.map(task => (
              <ErrorTaskCard key={task.task_id} task={task} onRetry={() => loadTasks()} />
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* Column 1: Inbox / Processing */}
        <div className="flex flex-col h-full bg-white rounded-xl shadow-sm border border-gray-200">
>>>>>>> REPLACE
