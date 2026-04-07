import re

with open('src/ui/web/src/views/ProjectIntelligenceView.tsx', 'r') as f:
    content = f.read()

# Replace PartyTable with sorting logic
party_table_old = r"""function PartyTable\(\{ parties \}: \{ parties: PartyEntry\[\] \}\) \{\n  if \(!parties \|\| parties\.length === 0\) return null\n\n  return \(\n    <div className="overflow-x-auto">\n      <table className="w-full text-left border-collapse">\n        <thead>\n          <tr className="border-b border-gray-200">\n            <th className="py-3 px-4 text-xs font-semibold text-teter-gray-text uppercase tracking-wider">\n              Party\n            <\/th>\n            <th className="py-3 px-4 text-xs font-semibold text-teter-gray-text uppercase tracking-wider">\n              Type\n            <\/th>\n            <th className="py-3 px-4 text-xs font-semibold text-teter-gray-text uppercase tracking-wider">\n              Total Docs\n            <\/th>\n            <th className="py-3 px-4 text-xs font-semibold text-teter-gray-text uppercase tracking-wider">\n              Primary Doc Type\n            <\/th>\n          <\/tr>\n        <\/thead>\n        <tbody>\n          \{parties\.map\(\(p\) => \(\n            <tr key=\{p\.party_name\} className="border-b border-gray-100 last:border-0 hover:bg-gray-50">\n              <td className="py-3 px-4 text-sm font-medium text-teter-dark">\n                \{p\.party_name\}\n              <\/td>\n              <td className="py-3 px-4 text-sm">\n                <span className="px-2 py-0.5 bg-gray-100 text-teter-gray-text rounded text-xs font-medium">\n                  \{p\.party_type\}\n                <\/span>\n              <\/td>\n              <td className="py-3 px-4 text-sm text-teter-dark font-medium">\n                \{p\.total_documents\}\n              <\/td>\n              <td className="py-3 px-4 text-sm text-teter-gray-text">\n                \{p\.primary_doc_type\}\n              <\/td>\n            <\/tr>\n          \)\)\}\n        <\/tbody>\n      <\/table>\n    <\/div>\n  \)\n\}"""

party_table_new = """type SortField = 'party_name' | 'party_type' | 'total_documents' | 'primary_doc_type'

function PartyTable({ parties }: { parties: PartyEntry[] }) {
  const [sortField, setSortField] = useState<SortField>('total_documents')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc')

  if (!parties || parties.length === 0) return null

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(prev => prev === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(field)
      setSortDirection('desc') // Default new sorts to desc
    }
  }

  const sortedParties = [...parties].sort((a, b) => {
    let comparison = 0
    if (sortField === 'total_documents') {
      comparison = (a.total_documents || 0) - (b.total_documents || 0)
    } else {
      const aVal = String(a[sortField] || '')
      const bVal = String(b[sortField] || '')
      comparison = aVal.localeCompare(bVal)
    }
    return sortDirection === 'asc' ? comparison : -comparison
  })

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sortField !== field) return <span className="ml-1 opacity-20 group-hover:opacity-50">↕</span>
    return <span className="ml-1">{sortDirection === 'asc' ? '↑' : '↓'}</span>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="border-b border-gray-200">
            <th
              className="py-3 px-4 text-xs font-semibold text-teter-gray-text uppercase tracking-wider cursor-pointer group hover:text-teter-dark"
              onClick={() => handleSort('party_name')}
            >
              Party <SortIcon field="party_name" />
            </th>
            <th
              className="py-3 px-4 text-xs font-semibold text-teter-gray-text uppercase tracking-wider cursor-pointer group hover:text-teter-dark"
              onClick={() => handleSort('party_type')}
            >
              Type <SortIcon field="party_type" />
            </th>
            <th
              className="py-3 px-4 text-xs font-semibold text-teter-gray-text uppercase tracking-wider cursor-pointer group hover:text-teter-dark"
              onClick={() => handleSort('total_documents')}
            >
              Total Docs <SortIcon field="total_documents" />
            </th>
            <th
              className="py-3 px-4 text-xs font-semibold text-teter-gray-text uppercase tracking-wider cursor-pointer group hover:text-teter-dark"
              onClick={() => handleSort('primary_doc_type')}
            >
              Primary Doc Type <SortIcon field="primary_doc_type" />
            </th>
          </tr>
        </thead>
        <tbody>
          {sortedParties.map((p) => (
            <tr key={p.party_name} className="border-b border-gray-100 last:border-0 hover:bg-gray-50">
              <td className="py-3 px-4 text-sm font-medium text-teter-dark">
                {p.party_name}
              </td>
              <td className="py-3 px-4 text-sm">
                <span className="px-2 py-0.5 bg-gray-100 text-teter-gray-text rounded text-xs font-medium">
                  {p.party_type}
                </span>
              </td>
              <td className="py-3 px-4 text-sm text-teter-dark font-medium">
                {p.total_documents}
              </td>
              <td className="py-3 px-4 text-sm text-teter-gray-text">
                {p.primary_doc_type}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}"""

content = re.sub(party_table_old, party_table_new, content)

with open('src/ui/web/src/views/ProjectIntelligenceView.tsx', 'w') as f:
    f.write(content)
