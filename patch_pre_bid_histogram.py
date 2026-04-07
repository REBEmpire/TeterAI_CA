import re

with open('src/ui/web/src/views/PreBidReviewView.tsx', 'r') as f:
    content = f.read()

# Add state for sort
sort_state = """  const [isClassifying, setIsClassifying] = useState(false)
  const [sortMethod, setSortMethod] = useState<'relevance' | 'date' | 'project'>('relevance')"""

content = content.replace("  const [isClassifying, setIsClassifying] = useState(false)", sort_state)

# Add histogram SVG and sort dropdown before the list
histogram_and_sort = """              {/* Score Distribution Histogram */}
              {results.similar_docs && results.similar_docs.length > 0 && (
                <div className="mb-6 bg-white border border-gray-200 rounded-md p-4 shadow-sm flex flex-col sm:flex-row justify-between items-center gap-4">
                  <div className="flex-1 w-full max-w-sm">
                    <h4 className="text-xs font-semibold text-teter-gray-text uppercase tracking-wider mb-2">Similarity Match Quality</h4>
                    <div className="flex h-4 rounded-full overflow-hidden bg-gray-100">
                      {(() => {
                        const docs = results.similar_docs!
                        const high = docs.filter(d => (d.score || 0) >= 0.85).length
                        const med = docs.filter(d => (d.score || 0) >= 0.75 && (d.score || 0) < 0.85).length
                        const low = docs.filter(d => (d.score || 0) < 0.75).length
                        const total = docs.length
                        return (
                          <>
                            {high > 0 && <div className="bg-red-500 h-full flex items-center justify-center text-[10px] text-white font-bold" style={{ width: `${(high/total)*100}%` }}>{high > 1 ? high : ''}</div>}
                            {med > 0 && <div className="bg-amber-500 h-full flex items-center justify-center text-[10px] text-white font-bold" style={{ width: `${(med/total)*100}%` }}>{med > 1 ? med : ''}</div>}
                            {low > 0 && <div className="bg-green-500 h-full flex items-center justify-center text-[10px] text-white font-bold" style={{ width: `${(low/total)*100}%` }}>{low > 1 ? low : ''}</div>}
                          </>
                        )
                      })()}
                    </div>
                    <div className="flex justify-between text-[10px] text-teter-gray-text mt-1 px-1">
                      <span>High (≥85%)</span>
                      <span>Med (75-84%)</span>
                      <span>Low (&lt;75%)</span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-teter-gray-text">Sort by:</span>
                    <select
                      className="text-sm border-gray-300 rounded shadow-sm focus:border-blue-500 focus:ring-blue-500 py-1"
                      value={sortMethod}
                      onChange={(e) => setSortMethod(e.target.value as any)}
                    >
                      <option value="relevance">Relevance</option>
                      <option value="date">Date</option>
                      <option value="project">Project</option>
                    </select>
                  </div>
                </div>
              )}

              <ul className="space-y-4">"""

content = content.replace('              <ul className="space-y-4">', histogram_and_sort)

# Update the map to use sorted array
sorted_map = """                {results.similar_docs
                  ? [...results.similar_docs].sort((a, b) => {
                      if (sortMethod === 'relevance') {
                        return (b.score || 0) - (a.score || 0)
                      } else if (sortMethod === 'date') {
                        return new Date(b.date_submitted || '').getTime() - new Date(a.date_submitted || '').getTime()
                      } else {
                        return (a.project_name || '').localeCompare(b.project_name || '')
                      }
                    }).map((doc, idx) => {"""

content = content.replace('                {results.similar_docs\n                  ? results.similar_docs.map((doc, idx) => {', sorted_map)

with open('src/ui/web/src/views/PreBidReviewView.tsx', 'w') as f:
    f.write(content)
